"""Verilog / SystemVerilog parsing: tokeniser helpers and dependency extraction."""

import re
from pathlib import Path

from ..constants import LIB_DEFAULT
from ..logging_util import log
from ..model import FileType, Name, SourceFile
from ..util import add_unique, read_text_file_contents, resolve_abs_path


# Verilog file parsing {{{
# Pre-process Verilog code to remove comments
def verilog_remove_comments(verilog_code):
    # Remove single-line comments
    code_without_single_comments = re.sub(r"//.*$", "", verilog_code, flags=re.MULTILINE)

    # Remove multi-line comments
    code_without_comments = re.sub(r"/\*.*?\*/", "", code_without_single_comments, flags=re.DOTALL)

    return code_without_comments


WHITESPACE_CHARS = " \t\n\r\v\f"


def get_idx_of_next_char(text, idx_start, c):
    for idx in range(idx_start, len(text)):
        if text[idx] in c:
            return idx
    return None


def get_idx_of_next_char_not(text, idx_start, c):
    for idx in range(idx_start, len(text)):
        if text[idx] not in c:
            return idx
    return None


def skip_matching_brackets(text, idx):
    assert text[idx] == "("
    depth = 1
    while depth > 0:
        idx += 1
        idx = get_idx_of_next_char(text, idx, "()")
        if idx is None:
            return None
        if text[idx] == "(":
            depth += 1
        elif text[idx] == ")":
            depth -= 1

    return idx


def parse_inside_verilog_module_instantiation_map(verilog_code, idx):
    valid = True
    idx = get_idx_of_next_char_not(verilog_code, idx, WHITESPACE_CHARS)
    if idx is None:
        # Truncated/malformed input (e.g. a file that ends mid-instantiation): no
        # more non-whitespace text to check, so this cannot be a valid port map.
        return None, False
    if verilog_code[idx] != ".":
        valid = False

    while valid:
        idx = get_idx_of_next_char(verilog_code, idx, ",()")
        if idx is None:
            valid = False
            break
        c = verilog_code[idx]
        idx += 1
        if c == ")":
            break
        elif c == ",":
            idx = get_idx_of_next_char_not(verilog_code, idx, WHITESPACE_CHARS)
            if idx is None:
                valid = False
                break
            if verilog_code[idx] != ".":
                valid = False
                break
        elif c == "(":
            idx = skip_matching_brackets(verilog_code, idx - 1)
            if idx is None:
                valid = False
                break
            idx += 1
    return idx, valid


VERILOG_KEYWORDS = frozenset([
    "always",
    "always_comb",
    "always_ff",
    "always_latch",
    "assign",
    "begin",
    "case",
    "else",
    "end",
    "endcase",
    "endfunction",
    "endmodule",
    "endprimitive",
    "endtable",
    "endtask",
    "enum",
    "for",
    "forever",
    "function",
    "if",
    "initial",
    "input",
    "int",
    "localparam",
    "logic",
    "module",
    "negedge",
    "output",
    "parameter",
    "posedge",
    "primitive",
    "real",
    "reg",
    "repeat",
    "table",
    "task",
    "time",
    "timescale",
    "typedef",
    "while",
    "wire",
])


def token_is_valid_name(token):
    if token in VERILOG_KEYWORDS:
        return False
    return all(char.isalnum() or char == "_" for char in token)


_INST_IDENT_RE = re.compile(r"[A-Za-z_]\w*")

_STRING_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"')


def _blank_string_literals(code: str) -> str:
    """Replace the contents of every string literal with an empty string.

    Keeps offsets/structure otherwise intact but prevents code-looking text
    *inside* a string (e.g. a log message like ``$display("entering module
    foo; init done")``) from being mistaken by the regexes below for a real
    declaration, package, import, or instantiation.
    """
    return _STRING_LITERAL_RE.sub('""', code)


def verilog_extract_module_instantiations(verilog_code):
    """Extract module instantiations of the form

        module_name [#(...)] instance_name (.port(sig), ...);

    Only named-connection port maps are recognised (matching the original
    heuristic). Candidate module names are found with a regex (every
    identifier); each candidate is then validated *forward*: an optional
    ``#(...)`` parameter list, an instance name, and a ``(...)`` port map that
    the shared validator accepts, ending in ``;``. Nested parentheses in the
    parameter/port lists are handled by ``parse_inside_...`` /
    ``skip_matching_brackets``, so no full grammar is needed.
    """
    instances = set()
    # `include "file" path extraction (verilog_extract_include_files) operates
    # on the original, un-blanked text -- see the comment there.
    code = _blank_string_literals(verilog_code)

    for m in _INST_IDENT_RE.finditer(code):
        module = m.group(0)
        if not token_is_valid_name(module):
            continue

        idx = get_idx_of_next_char_not(code, m.end(), WHITESPACE_CHARS)
        if idx is None:
            break

        # optional #(...) parameter list
        if code[idx] == "#":
            after_hash = get_idx_of_next_char_not(code, idx + 1, WHITESPACE_CHARS)
            if after_hash is None or code[after_hash] != "(":
                continue
            idx, _valid = parse_inside_verilog_module_instantiation_map(code, after_hash + 1)
            if idx is None:
                continue
            idx = get_idx_of_next_char_not(code, idx, WHITESPACE_CHARS)
            if idx is None:
                continue

        # instance name: a valid identifier starting at idx
        inst_m = _INST_IDENT_RE.match(code, idx)
        if inst_m is None:
            continue
        instance_name = inst_m.group(0)
        if not token_is_valid_name(instance_name):
            continue

        idx = get_idx_of_next_char_not(code, inst_m.end(), WHITESPACE_CHARS)
        if idx is None or code[idx] != "(":
            continue

        # Port map: the validator advances past a well-formed named map but for a
        # positional/invalid map it returns an index that is not at the closing
        # ';', so the check below rejects it (this is how positional ports and
        # function calls are excluded).
        idx, _valid = parse_inside_verilog_module_instantiation_map(code, idx + 1)
        if idx is None:
            continue
        idx = get_idx_of_next_char_not(code, idx, WHITESPACE_CHARS)
        if idx is None or code[idx] != ";":
            continue

        log.info(f"module {module} {instance_name}")
        instances.add(module)

    return list(instances)


# Function to extract include files from Verilog code
def verilog_extract_include_files(verilog_code):
    #TODO: Modify verilog_code by replacing it with the include statment with the included file
    # Deliberately does NOT call _blank_string_literals: the `include target
    # itself IS a string literal (`` `include "file.vh"``), so blanking it
    # here would erase the very text this function needs to extract.
    include_regex = r'`include\s+(["<])([^">]+)[">]'
    matches = re.finditer(include_regex, verilog_code)
    includes = []
    for match in matches:
        # inc_is_sys = match.group(1) == "<"
        inc_name = match.group(2)
        includes.append(inc_name)

    return includes

def verilog_extract_packages(verilog_code):
    # Blank string literals first so e.g. $display("... package foo; ...")
    # cannot phantom-declare a package `foo` -- see _blank_string_literals.
    code = _blank_string_literals(verilog_code)
    pattern = r'\bpackage\s+(\w+)\s*;'
    matches = re.finditer(pattern, code, re.DOTALL)

    packages = []
    for match in matches:
        pkg_name = match.group(1)
        packages.append(pkg_name)

    return packages

def verilog_extract_package_imports(verilog_code):
    # Blank string literals first -- same reasoning as verilog_extract_packages.
    code = _blank_string_literals(verilog_code)
    pattern = r'\bimport\s+(\w+)::([\w\*]+)\s*;'
    matches = re.finditer(pattern, code, re.DOTALL)

    packages = []
    for match in matches:
        pkg_name = match.group(1)
        # item_name = match.group(2)
        packages.append(pkg_name)

    return packages

def verilog_extract_module_declarations(verilog_code):
    # Blank string literals first -- same reasoning as verilog_extract_packages
    # (e.g. $display("entering module foo; init done") must not phantom-
    # declare a module `foo`).
    code = _blank_string_literals(verilog_code)
    # \bmodule\b so e.g. `rand_module u_inst (...)` does not phantom-declare a
    # module `u_inst`, and so `endmodule` is never matched as a declaration. The
    # declaration itself may end in `(` (ported) or `;` (portless -- every
    # testbench with no top-level ports), optionally after a `#(...)` parameter
    # list; `endmodule` is excluded by the leading \b, not by the ending char.
    # The parameter-list group allows one level of nested parens (e.g.
    # `#(parameter int W = $clog2(8))`) via the `\([^()]*\)` alternative --
    # both alternatives are disjoint character classes (no shared prefix to
    # backtrack between), so this stays linear; a second level of nesting
    # (e.g. `$foo($bar(8))`) is still unsupported (see
    # test_verilog_module_declaration_doubly_nested_parameter_still_unsupported
    # in tests/test_adversarial_parsers.py).
    module_declaration_regex = r"\bmodule\b\s+(\w+)\s*(?:\#\s*\((?:[^()]|\([^()]*\))*\))?\s*[(;]"
    matches = re.finditer(module_declaration_regex, code)
    declarations = []

    for match in matches:
        module_name = match.group(1)
        declarations.append(module_name)

    return declarations


def parse_verilog_file(loc: Path, ver, include_dir_list, include_file_locs) -> SourceFile:
    """Parse a Verilog/SV file into a :class:`SourceFile`.

    ``include_dir_list`` and ``include_file_locs`` are the project's `include
    search directories and known include-file locations (passed in, not looked
    up), used to resolve ``\\`include`` directives to concrete files.
    """
    log.info(f"parsing Verilog file {loc}")
    if Path(loc).suffix not in (".v", ".sv"):
        log.warning(f"unexpected verilog extension on {loc}, expected .v or .sv")

    clean = verilog_remove_comments(read_text_file_contents(loc))
    sf = SourceFile(loc, FileType.VERILOG, ver=ver)
    f_dir = Path(sf.loc).parent
    dirs = [Path(".")] + list(include_dir_list)
    known_includes = {resolve_abs_path(Path(p)) for p in include_file_locs}

    for inc_name in verilog_extract_include_files(clean):
        found = None
        for h_dir in dirs:
            base = h_dir if h_dir.is_absolute() else (f_dir / h_dir)
            cand = resolve_abs_path(base / inc_name)
            if cand in known_includes:
                found = cand
                break  # first match wins (this file's dir, then include dirs in order)
        if found is not None:
            sf.include_locs.append(found)
        else:
            log.warning(f"Verilog {loc} includes {inc_name} but file cannot be found")

    for pkg in verilog_extract_packages(clean):
        add_unique(sf.provides, Name(LIB_DEFAULT, pkg))
    for pkg in verilog_extract_package_imports(clean):
        add_unique(sf.requires, Name(LIB_DEFAULT, pkg))
    for mod in verilog_extract_module_declarations(clean):
        add_unique(sf.provides, Name(LIB_DEFAULT, mod))
    for mod in verilog_extract_module_instantiations(clean):
        add_unique(sf.requires, Name(LIB_DEFAULT, mod))
    return sf


# }}}
