"""hdldepends: HDL (VHDL/Verilog/Xilinx) dependency compile-order resolution.

Besides the ``hdldepends`` console script (see :mod:`hdldepends.cli`), the
package exposes a small Python API -- :func:`analyze` -- for callers that want
the resolved compile order in-process rather than as a written output file.
"""

from .api import AnalysisResult, analyze
from .constants import __version__

__all__ = ["AnalysisResult", "analyze", "__version__"]
