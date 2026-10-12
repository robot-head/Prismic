import sys
from pathlib import Path

import pytest

import prismic
from prismic import bootstrap


def test_entrypoint_runs_when_name_is_equal_but_not_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_codes: list[int] = []
    monkeypatch.setattr(bootstrap, "run", lambda: 23)
    monkeypatch.setattr(sys, "exit", exit_codes.append)
    entrypoint = Path(prismic.__file__).with_name("__main__.py")
    source = entrypoint.read_text(encoding="utf-8")
    script_name = "".join(("__", "main__"))

    assert script_name == "__main__"
    assert id(script_name) != id(sys.intern("__main__"))
    exec(compile(source, str(entrypoint), "exec"), {"__name__": script_name})

    assert exit_codes == [23]
