"""Shared context-manager behavior for objects that own resources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class ClosableContext(ABC):
    """Context manager that releases its resource through ``close()``."""

    @abstractmethod
    def close(self) -> None:
        """Release the resource owned by this object."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
