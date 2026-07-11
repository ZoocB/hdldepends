"""Minimal stderr logger.

A hand-rolled logger is used (rather than :mod:`logging`) because the original
tool relied heavily on f-strings at call sites and a trivial verbosity gate.
``log_level`` is a module global mutated by :func:`set_log_level`; the
:class:`log` methods read it at call time.
"""

import sys
from typing import Any, Optional

log_level = 0


# created own crappy logger because logging doesn't work with f strings
class log:
    @staticmethod
    def _log(severity: str, *args: object, **kwargs: Any) -> None:
        print(f"[{severity}]", *args, **kwargs, file=sys.stderr)

    @staticmethod
    def error(*args: object, **kwargs: Any) -> None:
        log._log("ERROR", *args, **kwargs)

    @staticmethod
    def warning(*args: object, **kwargs: Any) -> None:
        if log_level >= 0:
            log._log("WARNING", *args, **kwargs)

    @staticmethod
    def info(*args: object, **kwargs: Any) -> None:
        if log_level >= 1:
            log._log("INFO", *args, **kwargs)

    @staticmethod
    def debug(*args: object, **kwargs: Any) -> None:
        if log_level >= 2:
            log._log("DEBUG", *args, **kwargs)


def set_log_level(verbosity: Optional[int]) -> None:
    global log_level
    if verbosity is not None:
        log_level = verbosity
