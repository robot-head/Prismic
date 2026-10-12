from pathlib import Path

from prismic import bootstrap


def test_run_passes_the_collection_path_to_the_initial_window(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Application:
        def __init__(self, args: list[str]) -> None:
            captured["args"] = args

        def setOrganizationName(self, _name: str) -> None:
            pass

        def setApplicationName(self, _name: str) -> None:
            pass

        def setWindowIcon(self, _icon: object) -> None:
            pass

        def setStyleSheet(self, _style: str) -> None:
            pass

        def exec(self) -> int:
            return 17

    class _Window:
        def __init__(self, initial_path: Path | None) -> None:
            captured["initial_path"] = initial_path

        def show(self) -> None:
            captured["shown"] = True

    supplied = ["prismic", "trip.prismic"]
    monkeypatch.setattr(bootstrap, "QApplication", _Application)
    monkeypatch.setattr(bootstrap, "MainWindow", _Window)
    monkeypatch.setattr(bootstrap, "QIcon", lambda _path: object())

    result = bootstrap.run(supplied)

    assert result == 17
    assert captured["args"] is supplied
    assert captured["initial_path"] == Path("trip.prismic")
    assert captured["shown"] is True


def test_icon_path_points_to_the_bundled_application_icon() -> None:
    from prismic.assets import ICON_PATH

    assert ICON_PATH.name == "prismic.ico"
    assert ICON_PATH.parent.name == "icon"
    assert ICON_PATH.is_file()
