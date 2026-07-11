"""Core data model: a name, a file type, and a single source-file record.

Every HDL source (VHDL / Verilog / SystemVerilog) and every vendor file (Xilinx
``.bd`` / ``.xci``) is represented by one :class:`SourceFile`. A parser's only job
is to read a file and fill in what it *provides* (entities / packages / modules)
and what it *requires* (instantiations / ``use`` / ``import`` / includes). The
:class:`~hdldepends.resolver.Resolver` then walks those requires to build the
compile order.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional

from .constants import LIB_DEFAULT
from .util import resolve_abs_path


class Name:
    """A library-qualified HDL name (case-insensitive, hashable)."""

    __slots__ = ("lib", "name")

    def __init__(self, lib: str, name: str):
        self.lib = lib.lower()
        self.name = name.lower()

    def __eq__(self, other):
        return isinstance(other, Name) and self.lib == other.lib and self.name == other.name

    def __hash__(self):
        return hash((self.lib, self.name))

    def __repr__(self):
        return f"{self.lib}.{self.name}"


def str_to_name(s: str) -> Name:
    parts = s.split(".")
    if len(parts) == 1:
        return Name(LIB_DEFAULT, parts[0])
    if len(parts) == 2:
        return Name(parts[0], parts[1])
    raise ValueError(f"cannot convert {s!r} to a lib.name")


class FileType(Enum):
    VHDL = auto()
    VERILOG = auto()
    OTHER = auto()
    X_BD = auto()
    X_XCI = auto()
    DIRECT = auto()
    VERILOG_INCLUDE = auto()


def string_to_filetype(s: str) -> FileType:
    try:
        return FileType[s.upper()]
    except KeyError as e:
        raise ValueError(f"unknown file type: {s}") from e


@dataclass
class SourceFile:
    """One parsed source file: what it provides, what it requires, and extras."""

    loc: Path
    ftype: FileType
    lib: str = LIB_DEFAULT
    ver: Optional[str] = None
    #: names this file defines (entities, packages, modules, IP/BD name)
    provides: List[Name] = field(default_factory=list)
    #: names this file needs (instantiations, use/import clauses)
    requires: List[Name] = field(default_factory=list)
    #: extra files emitted just before this one (e.g. Xilinx coefficient files)
    direct_deps: List[Path] = field(default_factory=list)
    #: resolved Verilog `include file locations, emitted before this file
    include_locs: List[Path] = field(default_factory=list)
    #: Xilinx selection metadata (empty for non-vendor files)
    x_tool_version: str = ""
    x_device: str = ""
    #: for X_XCI files: the VHDL file whose library this one inherited (so a
    #: netlist generated from the XCI gets a valid library). None until inherited.
    lib_inherited_from: Optional[Path] = None
    #: depth in the dependency tree, set while computing the compile order
    level: int = 0

    def __post_init__(self):
        self.loc = resolve_abs_path(self.loc)

    @property
    def is_x(self) -> bool:
        return self.ftype in (FileType.X_BD, FileType.X_XCI)

    @property
    def type_str(self) -> str:
        # The custom @tag (e.g. VHDL2008) takes the place of the bare file type in
        # the output, so a downstream tool can tell e.g. VHDL-93 from VHDL-2008.
        return self.ver if self.ver else self.ftype.name
