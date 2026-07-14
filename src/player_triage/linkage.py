"""Repeat-contact linkage per ``policy/linkage_policy.json``.

Groups messages by the raw player identifier (which stays inside this module),
then applies the two linkage rules from the policy file:

* ``LINK_SAME_PLAYER_AND_EXPLICIT_REFERENCE`` — same player, same normalized
  ``W-`` / ``T-`` reference in both messages, within the linkage window.
* ``LINK_SAME_PLAYER_FOLLOWUP`` — same player, later message contains
  follow-up wording (``follow up``, ``no reply``, ``second email``,
  ``still waiting``, ``still no response``, …), within the linkage window.

Neither rule uses raw message-text hashing as a primary identifier. Linkage
outputs contain only ``msg_id`` values — never a player identifier.

Ground truth expects ``M31`` → ``M09`` with ``first_contact_message_id=M09``
and ``previous_contact_count=1``; the tests confirm that behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Iterable, Mapping, Sequence

from .records import LinkageResult, RawMessage

# 30-day window is generous enough to catch the dataset's authentic linkage
# (M09 and M31 arrive on the same day) and is documented as the "configured
# linkage window" from ``policy/linkage_policy.json``.
_LINKAGE_WINDOW: Final[timedelta] = timedelta(days=30)

_FOLLOWUP_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:follow[\s-]*up|following up|no reply|no response|second (?:email|message|attempt|time)|"
    r"still (?:no|waiting|haven[’']?t)|another (?:email|reminder)|reminder|"
    r"escalat(?:e|ing|ion)|no answer)\b"
)
_REFERENCE_RE: Final[re.Pattern[str]] = re.compile(r"\b((?:W|T)-\d{5})\b")


@dataclass(frozen=True, slots=True)
class _LinkedPair:
    earlier: str
    later: str
    rule_id: str


def _followup_hits(text: str) -> bool:
    return bool(_FOLLOWUP_RE.search(text))


def _references(text: str) -> frozenset[str]:
    return frozenset(match.group(1).upper() for match in _REFERENCE_RE.finditer(text))


def build_linkage(messages: Sequence[RawMessage]) -> Mapping[str, LinkageResult]:
    """Return a mapping from ``msg_id`` → :class:`LinkageResult`."""

    by_player: dict[str, list[RawMessage]] = {}
    for message in messages:
        by_player.setdefault(message.player_id, []).append(message)

    edges: list[_LinkedPair] = []
    for player_messages in by_player.values():
        ordered = sorted(player_messages, key=lambda m: m.received_utc)
        for later_index, later in enumerate(ordered):
            later_text = later.combined_text()
            later_refs = _references(later_text)
            later_followup = _followup_hits(later_text)
            for earlier in ordered[:later_index]:
                if later.received_utc - earlier.received_utc > _LINKAGE_WINDOW:
                    continue
                if later.received_utc <= earlier.received_utc:
                    continue
                earlier_refs = _references(earlier.combined_text())
                shared_refs = earlier_refs & later_refs
                if shared_refs:
                    edges.append(
                        _LinkedPair(
                            earlier=earlier.msg_id,
                            later=later.msg_id,
                            rule_id="LINK_SAME_PLAYER_AND_EXPLICIT_REFERENCE",
                        )
                    )
                elif later_followup:
                    edges.append(
                        _LinkedPair(
                            earlier=earlier.msg_id,
                            later=later.msg_id,
                            rule_id="LINK_SAME_PLAYER_FOLLOWUP",
                        )
                    )

    return _assemble(messages, edges)


def _assemble(
    messages: Iterable[RawMessage], edges: Sequence[_LinkedPair]
) -> Mapping[str, LinkageResult]:
    inbound: dict[str, list[_LinkedPair]] = {}
    for edge in edges:
        inbound.setdefault(edge.later, []).append(edge)

    all_ids: set[str] = {message.msg_id for message in messages}
    ordered_ids = sorted(all_ids, key=lambda mid: mid)
    results: dict[str, LinkageResult] = {}
    for msg_id in ordered_ids:
        related_edges = inbound.get(msg_id, [])
        related_ids = sorted({edge.earlier for edge in related_edges})
        first_contact = related_ids[0] if related_ids else None
        rule_ids = tuple(sorted({edge.rule_id for edge in related_edges}))
        results[msg_id] = LinkageResult(
            msg_id=msg_id,
            related_message_ids=tuple(related_ids),
            first_contact_message_id=first_contact,
            previous_contact_count=len(related_ids),
            linkage_rule_ids=rule_ids,
        )
    return results
