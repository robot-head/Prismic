from pathlib import Path

import pytest

from prismic import _packaging


def test_find_iscc_prefers_executable_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_packaging.shutil, "which", lambda name: "/tools/iscc.exe")

    assert _packaging._find_iscc() == "/tools/iscc.exe"


def test_find_iscc_checks_the_documented_default_windows_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = tmp_path / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"
    default.parent.mkdir(parents=True)
    default.touch()
    monkeypatch.setattr(_packaging.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(_packaging.shutil, "which", lambda _name: None)

    assert _packaging._find_iscc() == str(default)


def test_build_exe_skips_installer_when_inno_setup_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def record_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(_packaging.subprocess, "run", record_run)
    monkeypatch.setattr(_packaging, "_find_iscc", lambda: None)

    _packaging.build_exe()

    assert len(calls) == 1
    assert calls[0][1]["check"] is True
    assert "Inno Setup not found" in capsys.readouterr().out


def test_run_inno_setup_checks_the_subprocess_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def record_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(_packaging.subprocess, "run", record_run)

    _packaging._run_inno_setup("ISCC.exe")

    assert calls == [
        (
            (["ISCC.exe", "packaging/windows/prismic.iss"],),
            {"cwd": _packaging.REPO_ROOT, "check": True},
        )
    ]


def test_build_installer_reports_missing_iscc_at_the_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_packaging.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(_packaging, "_find_iscc", lambda: None)
    expected = tmp_path / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"

    with pytest.raises(SystemExit, match=str(expected)):
        _packaging.build_installer()
