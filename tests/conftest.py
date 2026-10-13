"""Unit tests never scan the user's application catalog or launch desktop apps.

Component fixtures supply explicit discovery records and injected OS executors.
Real Windows discovery and action acceptance use the separate diagnostics.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_application_discovery(monkeypatch):
    from jarvis import applications

    monkeypatch.setattr(applications, "_known_candidates", lambda: {})
    monkeypatch.setattr(applications, "_app_paths", lambda: [])
    monkeypatch.setattr(applications, "_start_menu_entries", lambda: [])
    monkeypatch.setattr(applications, "_packaged_entries", lambda: [])
