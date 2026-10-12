"""Load a fresh lockfile module under a mocked Windows runtime."""

import importlib.util
import sys
from types import ModuleType
from typing import Any

import prismic.persistence.lockfile as lockfile


def load_windows_lockfile(monkeypatch: Any, platform: str, msvcrt: object) -> ModuleType:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    spec = importlib.util.spec_from_file_location(
        "_test_prismic_windows_lockfile", lockfile.__file__
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
