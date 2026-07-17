"""Streamlit entry point for the local rules-only control console."""

from __future__ import annotations

import streamlit as st

from player_triage.console_service import ConsoleService, ConsoleServiceError
from player_triage.errors import ConfigurationError
from player_triage.paths import resolve_app_root
from player_triage.ui.pages import PAGE_RENDERERS


def _service() -> ConsoleService:
    return ConsoleService(resolve_app_root())


def main() -> None:
    st.set_page_config(
        page_title="Player Triage Control Console",
        page_icon=":shield:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        [data-testid="stMetric"] {background: #f4f7fb; border: 1px solid #dce4ef; padding: 0.8rem; border-radius: 0.65rem;}
        .safe-banner {padding: .7rem 1rem; border-radius: .55rem; background: #eaf6ef; border: 1px solid #a8d5b8; color: #173f27;}
        .warning-banner {padding: .7rem 1rem; border-radius: .55rem; background: #fff7e6; border: 1px solid #e3c477; color: #58400b;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    service = _service()
    st.sidebar.title("Control Console")
    st.sidebar.caption("Local synthetic demonstration")
    page = st.sidebar.radio("Navigate", tuple(PAGE_RENDERERS), key="navigation")
    st.sidebar.divider()
    st.sidebar.markdown("**Approved mode:** `rules_only`")
    st.sidebar.markdown("**Model:** rejected and unavailable")
    st.sidebar.caption("No production authentication or multi-user authorization.")
    try:
        PAGE_RENDERERS[page](service)
    except (ConfigurationError, ConsoleServiceError, ValueError, OSError):
        st.error("The requested operation failed safely. No active configuration was changed.")


if __name__ == "__main__":
    main()
