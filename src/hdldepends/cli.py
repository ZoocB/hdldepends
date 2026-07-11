"""Command-line interface and console-script entry point."""

import argparse
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from . import output
from .config import build_resolver
from .constants import HDL_DEPENDS_VERSION_NUM, LIB_DEFAULT, __version__
from .errors import ConfigError
from .logging_util import set_log_level
from .model import Name, SourceFile, string_to_filetype
from .resolver import Resolver

#: KINDs accepted by -o/--output, and the selector keys each allows.
OUTPUT_KINDS: Dict[str, Set[Optional[str]]] = {
    "compile-order": {None, "lib", "type"},
    "compile-order-paths": {None},
    "compile-order-json": {None},
    "file-list": {None, "lib", "type"},
    "ext-list": {None, "tag"},
}
_NEEDS_TOP = {"compile-order", "compile-order-paths", "compile-order-json"}


def _parse_output_kind(token: str) -> Tuple[str, Optional[str], Optional[str]]:
    if ":" in token:
        kind, sel = token.split(":", 1)
        if "=" not in sel:
            raise argparse.ArgumentTypeError(f"output selector for '{kind}' must be SELKEY=VALUE, got '{sel}'")
        sel_key, sel_val = sel.split("=", 1)
    else:
        kind, sel_key, sel_val = token, None, None
    if kind not in OUTPUT_KINDS:
        raise argparse.ArgumentTypeError(f"unknown output kind '{kind}'; expected one of {', '.join(sorted(OUTPUT_KINDS))}")
    if sel_key not in OUTPUT_KINDS[kind]:
        allowed = ", ".join(sorted(s for s in OUTPUT_KINDS[kind] if s)) or "(none)"
        raise argparse.ArgumentTypeError(f"output kind '{kind}' does not accept selector '{sel_key}'; allowed: {allowed}")
    return kind, sel_key, sel_val


def _top_from_loc(parser: argparse.ArgumentParser, resolver: Resolver, loc: Path, what: str) -> SourceFile:
    """Look ``loc`` up in the resolver's index, or exit via ``parser.error``
    naming it with ``what`` (e.g. ``"--top-file foo.vhd"`` / ``"config top
    file /abs/foo.vhd"``)."""
    top = resolver.by_loc.get(loc)
    if top is None:
        parser.error(f"{what} is not in the project")
    return top


def _top_from_name(parser: argparse.ArgumentParser, resolver: Resolver, name: Name) -> SourceFile:
    """Resolve ``name`` to its providing file via the resolver, or exit via
    ``parser.error`` with the same message :meth:`Resolver.find_top` raises."""
    try:
        return resolver.find_top(name)
    except KeyError as e:
        parser.error(str(e.args[0]) if e.args else str(e))


def _emit(resolver, order, kind, sel_key, sel_val, file_str):
    loc = Path(file_str)
    ftype = string_to_filetype(sel_val) if sel_key == "type" else None
    lib = sel_val if sel_key == "lib" else None
    if kind == "compile-order":
        output.write_compile_order(order, loc, ftype=ftype, lib=lib)
    elif kind == "compile-order-paths":
        output.write_compile_order(order, loc, paths_only=True)
    elif kind == "compile-order-json":
        output.write_compile_order_json(order, resolver.tag_2_ext, loc)
    elif kind == "file-list":
        output.write_file_list(resolver.files, loc, ftype=ftype, lib=lib)
    elif kind == "ext-list":
        output.write_ext_list(resolver.tag_2_ext, loc, tag=sel_val)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HDL dependency parser")
    p.add_argument(
        "--version", action="version", version=f"hdldepends {__version__} (config schema {HDL_DEPENDS_VERSION_NUM})"
    )
    p.add_argument("-v", "--verbose", action="count", help="verbosity (repeat for more)")
    p.add_argument("config_file", nargs="+", help="config file(s): TOML / JSON / YAML")
    p.add_argument("--top-file", type=str, help="path to the top-level file (must already be in the project)")
    p.add_argument("--top-entity", type=str, help="top-level entity/module name")
    p.add_argument("--top-vhdl-lib", type=str, help="default VHDL library for the top entity")
    p.add_argument(
        "-o", "--output", action="append", nargs=2, metavar=("KIND[:SEL=VAL]", "FILE"),
        help=(
            "write an output. KIND: compile-order, compile-order-paths, compile-order-json, "
            "file-list, ext-list. Selector: compile-order/file-list accept ':lib=LIB' or "
            "':type=TYPE'; ext-list accepts ':tag=TAG'. Repeatable."
        ),
    )
    p.add_argument("--x-tool-version", type=str, help="Xilinx tool version (selects among .bd/.xci variants)")
    p.add_argument("--x-device", type=str, help="Xilinx device (selects among .bd/.xci variants)")
    return p


def hdldepends():
    parser = _build_parser()
    args = parser.parse_args()
    set_log_level(args.verbose)

    requests = []
    for kind_token, file_str in args.output or []:
        try:
            requests.append((*_parse_output_kind(kind_token), file_str))
        except argparse.ArgumentTypeError as e:
            parser.error(str(e))

    top_lib = args.top_vhdl_lib or LIB_DEFAULT
    try:
        resolver = build_resolver(args.config_file, work_dir=Path("."), top_lib=top_lib)
    except (ConfigError, RuntimeError, OSError, ValueError) as e:
        # Config loading/validation and file parsing raise these typed
        # exceptions (with a message naming the offending file) for anything
        # a malformed config or a file it references could plausibly trigger
        # -- report them the same clean, argparse-style way as the top-lookup
        # errors below, not a raw traceback. OSError (rather than just
        # FileNotFoundError, one of its subclasses) also covers e.g. a
        # PermissionError on a config/source file.
        parser.error(str(e))
    if args.x_tool_version is not None:
        resolver.x_tool_version = args.x_tool_version
    if args.x_device is not None:
        resolver.x_device = args.x_device

    # Top-selection precedence: --top-file > --top-entity > config top_*_file
    # (resolver.top_loc) > config top_entity (resolver.top_name).
    top: Optional[SourceFile] = None
    if args.top_file:
        top = _top_from_loc(parser, resolver, Path(args.top_file).resolve(), f"--top-file {args.top_file}")
    elif args.top_entity:
        top = _top_from_name(parser, resolver, Name(top_lib, args.top_entity))
    elif resolver.top_loc is not None:
        top = _top_from_loc(parser, resolver, resolver.top_loc, f"config top file {resolver.top_loc}")
    elif resolver.top_name is not None:
        top = _top_from_name(parser, resolver, resolver.top_name)

    order = []
    if top is not None:
        order = resolver.compile_order(top)
        # Force-include any init/forced files not already reached by the walk.
        in_order = {sf.loc for sf in order}
        forced = [sf for sf in resolver.init_files if sf.loc not in in_order]
        order = forced + order
        output.print_compile_order(order)

    for kind, sel_key, sel_val, file_str in requests:
        if kind in _NEEDS_TOP and top is None:
            parser.error(f"output '{kind}' requires a top (--top-entity / --top-file or a top_* config key)")
        try:
            _emit(resolver, order, kind, sel_key, sel_val, file_str)
        except OSError as e:
            # e.g. the FILE half of `-o KIND FILE` names a directory that
            # doesn't exist -- a raw FileNotFoundError otherwise propagates
            # straight out of output.py's `open(loc, "w")`.
            parser.error(f"could not write output '{kind}' to {file_str}: {e}")
        except ValueError as e:
            # e.g. `-o compile-order:type=BOGUS` -- string_to_filetype raises
            # ValueError for a selector value that isn't a known file type.
            parser.error(f"invalid output selector for '{kind}': {e}")


if __name__ == "__main__":
    hdldepends()
