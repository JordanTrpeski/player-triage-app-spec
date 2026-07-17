"""Single-process isolation for interruptible local llama.cpp inference.

Python cannot safely interrupt a native llama.cpp call running in a thread.
This worker owns the runtime in a child process. A timeout terminates that
process and waits for it to exit before returning deterministic fallback.
Only one request is ever outstanding; replacement workers are started
sequentially, never concurrently.
"""

from __future__ import annotations

import ctypes
import importlib
import multiprocessing
import os
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class ModelWorkerError(Exception):
    """Sanitized isolated-worker failure."""


class ModelWorkerTimeout(ModelWorkerError):
    """The worker was terminated after exceeding its deadline."""


class ModelWorkerRuntimeError(ModelWorkerError):
    """The worker reported a sanitized load or inference failure."""


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    model_path: Path
    runtime_version: str
    context_limit: int
    output_token_limit: int
    temperature: float


@dataclass(frozen=True, slots=True)
class WorkerInference:
    response: object
    rss_bytes: int | None


WorkerTarget = Callable[[Connection, WorkerSettings], None]


class IsolatedModelWorker:
    """Persistent, sequential child process with a hard termination timeout."""

    def __init__(
        self,
        settings: WorkerSettings,
        *,
        startup_timeout_seconds: float,
        worker_target: WorkerTarget | None = None,
    ) -> None:
        self.settings = settings
        self.startup_timeout_seconds = startup_timeout_seconds
        self.worker_target = worker_target or _llama_worker_main
        # multiprocessing returns context-specific Process/Connection concrete
        # classes whose stubs do not share a public structural base type.
        self._process: Any = None
        self._connection: Any = None
        self.load_time_ms = 0.0
        self.rss_bytes: int | None = None

    @property
    def is_alive(self) -> bool:
        return bool(self._process and self._process.is_alive())

    def start(self) -> None:
        if self.is_alive:
            return
        self.close()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=self.worker_target,
            args=(child, self.settings),
            name="player-triage-local-model",
            daemon=True,
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        if not parent.poll(self.startup_timeout_seconds):
            self._terminate()
            raise ModelWorkerTimeout("local model worker startup timed out")
        try:
            ready = parent.recv()
        except (EOFError, OSError) as exc:
            self._terminate()
            raise ModelWorkerRuntimeError("local model worker startup failed") from exc
        if not isinstance(ready, Mapping) or ready.get("status") != "ready":
            self._terminate()
            raise ModelWorkerRuntimeError("local model worker startup failed")
        self.load_time_ms = float(ready.get("load_time_ms", 0.0))
        rss = ready.get("rss_bytes")
        self.rss_bytes = int(rss) if isinstance(rss, int) else None

    def infer(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> WorkerInference:
        self.start()
        connection = self._connection
        if connection is None:  # pragma: no cover - guarded by start
            raise ModelWorkerRuntimeError("local model worker is unavailable")
        try:
            connection.send(
                {"command": "infer", "messages": list(messages), "schema": dict(schema)}
            )
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._terminate()
            raise ModelWorkerRuntimeError("local model worker communication failed") from exc
        if not connection.poll(timeout_seconds):
            self._terminate()
            raise ModelWorkerTimeout("local inference timed out and worker was terminated")
        try:
            payload = connection.recv()
        except (EOFError, OSError) as exc:
            self._terminate()
            raise ModelWorkerRuntimeError("local model worker exited during inference") from exc
        if not isinstance(payload, Mapping) or payload.get("status") != "ok":
            self._terminate()
            raise ModelWorkerRuntimeError("local model inference failed")
        rss = payload.get("rss_bytes")
        self.rss_bytes = int(rss) if isinstance(rss, int) else self.rss_bytes
        return WorkerInference(response=payload.get("response"), rss_bytes=self.rss_bytes)

    def close(self) -> None:
        process = self._process
        connection = self._connection
        if process is not None and process.is_alive() and connection is not None:
            try:
                connection.send({"command": "shutdown"})
                process.join(timeout=2.0)
            except (BrokenPipeError, EOFError, OSError):
                pass
        if process is not None and process.is_alive():
            self._terminate()
        elif connection is not None:
            connection.close()
        self._process = None
        self._connection = None

    def _terminate(self) -> None:
        process = self._process
        connection = self._connection
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=5.0)
        if connection is not None:
            connection.close()
        self._process = None
        self._connection = None

    def __del__(self) -> None:  # pragma: no cover - defensive interpreter cleanup
        try:
            self.close()
        except Exception:
            pass


def _llama_worker_main(connection: Connection, settings: WorkerSettings) -> None:
    """Child entry point. Never logs prompts, output, or runtime exceptions."""

    try:
        module = importlib.import_module("llama_cpp")
        if str(getattr(module, "__version__", "")) != settings.runtime_version:
            connection.send({"status": "initialization_error"})
            return
        started = time.perf_counter()
        runtime = module.Llama(
            model_path=str(settings.model_path),
            n_ctx=settings.context_limit,
            verbose=False,
        )
        connection.send(
            {
                "status": "ready",
                "load_time_ms": (time.perf_counter() - started) * 1000,
                "rss_bytes": _resident_bytes(),
            }
        )
        while True:
            command = connection.recv()
            if not isinstance(command, Mapping):
                connection.send({"status": "runtime_error"})
                continue
            if command.get("command") == "shutdown":
                return
            if command.get("command") != "infer":
                connection.send({"status": "runtime_error"})
                continue
            response = runtime.create_chat_completion(
                messages=command.get("messages"),
                temperature=settings.temperature,
                max_tokens=settings.output_token_limit,
                response_format={"type": "json_object", "schema": command.get("schema")},
            )
            connection.send(
                {"status": "ok", "response": response, "rss_bytes": _resident_bytes()}
            )
    except (EOFError, KeyboardInterrupt):
        return
    except Exception:
        try:
            connection.send({"status": "runtime_error"})
        except Exception:
            pass
    finally:
        connection.close()


def hanging_test_worker(connection: Connection, settings: WorkerSettings) -> None:
    """Test target proving that timeout terminates a genuinely running process."""

    _ = settings
    connection.send({"status": "ready", "load_time_ms": 0.0, "rss_bytes": _resident_bytes()})
    try:
        command = connection.recv()
        if isinstance(command, Mapping) and command.get("command") == "infer":
            time.sleep(60.0)
    finally:
        connection.close()


def _resident_bytes() -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    )
    get_process_memory_info.restype = ctypes.c_int
    handle = get_current_process()
    ok = get_process_memory_info(handle, ctypes.byref(counters), counters.cb)
    return int(counters.WorkingSetSize) if ok else None
