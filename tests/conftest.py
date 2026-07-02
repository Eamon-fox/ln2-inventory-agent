"""Shared pytest fixtures for the SnowFox test suite.

Goals:
- Default GUI/PySide6 tests to headless (offscreen) rendering without
  overriding an already-configured platform (respect CI or local overrides).
- Provide a session-scoped QApplication fixture that reuses the singleton so
  it never conflicts with the 17+ GUI test files that create their own via
  ``QApplication.instance() or QApplication([])``.
- Degrade gracefully when PySide6 is not installed (non-GUI runs still work).
"""

from __future__ import annotations

import os

import pytest

# Set the headless platform before any Qt import happens. ``setdefault`` keeps
# an explicit override (e.g. CI exporting QT_QPA_PLATFORM) intact.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """Return a process-wide QApplication, or skip if PySide6 is unavailable.

    QApplication is a singleton: if one already exists (e.g. a GUI test created
    it during collection), we reuse it instead of constructing a second one.
    """
    QApplication = pytest.importorskip(
        "PySide6.QtWidgets",
        reason="PySide6 not installed; GUI tests are skipped",
    ).QApplication
    app = QApplication.instance() or QApplication([])
    return app
