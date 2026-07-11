# vi: foldmethod=marker
"""Facade for the hdldepends package.

The implementation is split into focused modules:

* :mod:`hdldepends.constants`, :mod:`hdldepends.logging_util`,
  :mod:`hdldepends.util`, :mod:`hdldepends.discovery` -- leaf helpers
* :mod:`hdldepends.model` -- ``Name``, ``FileType`` and the single ``SourceFile`` record
* :mod:`hdldepends.parsers` / :mod:`hdldepends.vendors.xilinx` -- parsers (jobs)
* :mod:`hdldepends.resolver` -- the flat index + compile-order walk
* :mod:`hdldepends.config` -- config loading + Resolver construction
* :mod:`hdldepends.output` -- writing the compile order / file lists
* :mod:`hdldepends.cli` -- argument parsing / entry point

It re-exports the public surface so ``hdldepends.hdldepends:hdldepends`` (the
console-script entry point) keeps working.
"""

from .constants import *  # noqa: F401,F403
from .logging_util import *  # noqa: F401,F403
from .util import *  # noqa: F401,F403
from .discovery import *  # noqa: F401,F403
from .model import *  # noqa: F401,F403
from .parsers.vhdl import *  # noqa: F401,F403
from .parsers.verilog import *  # noqa: F401,F403
from .vendors.xilinx.xci import *  # noqa: F401,F403
from .vendors.xilinx.bd import *  # noqa: F401,F403
from .resolver import Resolver  # noqa: F401
from .config import build_resolver, load_config  # noqa: F401
from .cli import hdldepends  # noqa: F401


if __name__ == "__main__":
    hdldepends()
