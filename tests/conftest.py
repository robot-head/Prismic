import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from prismic.persistence import database, migrations

pytest_plugins = ("tests._reconciliation_test_context",)

_SLOW_STATE_PATH = Path(__file__).parent.parent / ".slow_test_state.json"
_SLOW_STATE_HISTORY_LENGTH = 3


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Track last-run time and recent durations for `@pytest.mark.slow` tests.

    Written to a gitignored state file that tools/run_tests.py reads to
    decide which slow tests are stale enough to re-run, and that an audit
    reads to spot ones that no longer earn their `slow` mark.
    """
    if report.when != "call" or "slow" not in report.keywords:
        return
    try:
        state = json.loads(_SLOW_STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    entry = state.setdefault(report.nodeid, {"last_run": 0.0, "recent_durations": []})
    entry["last_run"] = time.time()
    entry["recent_durations"] = (entry["recent_durations"] + [report.duration])[
        -_SLOW_STATE_HISTORY_LENGTH:
    ]
    _SLOW_STATE_PATH.write_text(json.dumps(state, indent=2))


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point app-wide preferences at a temp directory for every test.

    Preferences (shortcut bindings, so far) live in the real per-user
    config directory by default. Without this, the suite would read
    whatever shortcuts the developer running it has customized -- making
    tests pass or fail depending on whose machine they're on -- and,
    worse, overwrite those customizations the first time a test changed a
    binding.

    Redirected by setting the environment variables
    `preferences_directory()` actually reads, rather than by patching that
    function out, so tests keep exercising the real resolution logic --
    including `test_preferences.py`, which asserts things about it
    directly.
    """
    base = tmp_path / "config"
    base.mkdir()
    monkeypatch.setenv("APPDATA", str(base))  # Windows
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))  # Linux/other
    monkeypatch.setenv("HOME", str(base))  # macOS, via Path.home()
    return base


@pytest.fixture
def migrated_connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = database.connect(tmp_path / "test.prismic")
    migrations.migrate(connection, tmp_path / "test.prismic")
    try:
        yield connection
    finally:
        connection.close()
