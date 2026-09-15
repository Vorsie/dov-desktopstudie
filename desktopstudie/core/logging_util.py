"""Tiny structured logger: '[core LEVEL module] message'. The sink is injectable
(print, list.append, QgsMessageLog in the shell)."""
from __future__ import annotations

from typing import Callable


class Log:
    def __init__(
        self,
        module: str,
        sink: Callable[[str], None] | None = None,
        scope: str = "core",
    ):
        self.module = module
        self.sink = sink or print
        self.scope = scope

    def child(self, module: str) -> Log:
        return Log(module, self.sink, self.scope)

    def _emit(self, level: str, message: str) -> None:
        self.sink(f"[{self.scope} {level} {self.module}] {message}")

    def debug(self, message: str) -> None:
        self._emit("DEBUG", message)

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def warning(self, message: str) -> None:
        self._emit("WARNING", message)

    def error(self, message: str) -> None:
        self._emit("ERROR", message)
