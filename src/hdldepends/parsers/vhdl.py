"""VHDL source parsing: comment/protected-code stripping and entity/dependency extraction."""

import re
from pathlib import Path

from ..constants import LIB_DEFAULT
from ..logging_util import log
from ..model import FileType, Name, SourceFile
from ..util import add_unique, read_text_file_contents


# VHDL file parsing {{{
def vhdl_remove_comments(vhdl_code: str) -> str:
    # Remove single-line comments
    code_without_single_comments = re.sub(r"--.*$", "", vhdl_code, flags=re.MULTILINE)

    # Remove multi-line comments
    code_without_comments = re.sub(r"/\*.*?\*/", "", code_without_single_comments, flags=re.DOTALL)

    return code_without_comments


_PROTECT_BEGIN_RE = re.compile(r"[ \t]*`protect\s+begin_protected[^\n]*\n?")
_PROTECT_END_RE = re.compile(r"[ \t]*`protect\s+end_protected[^\n]*\n?")


def vhdl_remove_protected_code(vhdl_code: str) -> str:
    """Removes protected code from VHDL code.

    Strips every `` `protect begin_protected `` .. `` `protect end_protected ``
    span (leading whitespace before the marker and trailing text after it on the
    same line are both tolerated). Xilinx encrypted netlists sometimes start
    mid-region -- an end marker with no preceding begin marker -- in which case
    everything from the start of the file through that end marker is dropped,
    since there is no way to know how much of the (already-truncated) file is
    protected. That drop-the-prefix handling applies ONLY at the very start of
    the scan (offset 0, before any region has been processed): a later, orphan
    end marker (no begin marker since the last processed region) is assumed to
    be a stray/duplicate marker instead, and only the marker line itself is
    dropped -- the code around it (which is not inside any begin/end pair) is
    kept.

    Args:
        vhdl_code (str): Single string of VHDL code from file read.

    Returns:
        str: Single string of VHDL code without any protected code
    """
    out = []
    pos = 0
    end_of_text = len(vhdl_code)
    while pos < end_of_text:
        begin_m = _PROTECT_BEGIN_RE.search(vhdl_code, pos)
        end_m = _PROTECT_END_RE.search(vhdl_code, pos)
        if end_m is not None and (begin_m is None or end_m.start() < begin_m.start()):
            if pos == 0:
                # An end marker with no matching begin marker before it, right
                # at the start of the file: nothing before it can be trusted
                # to be un-protected (a truncated encrypted netlist), so drop
                # it all.
                pos = end_m.end()
                continue
            # A later, orphan end marker: keep the code since `pos`, drop just
            # the marker line itself.
            log.debug(f"orphan `protect end_protected` marker at offset {end_m.start()}, dropping the marker line only")
            out.append(vhdl_code[pos:end_m.start()])
            pos = end_m.end()
            continue
        if begin_m is None:
            out.append(vhdl_code[pos:])
            break
        out.append(vhdl_code[pos:begin_m.start()])
        end_m = _PROTECT_END_RE.search(vhdl_code, begin_m.end())
        if end_m is None:
            # Unterminated protected region: drop through EOF.
            break
        pos = end_m.end()
    return "".join(out)


vhdl_regex_patterns = {
    "package_decl": re.compile(
        r"(?<!:)\bpackage\s+(\w+)\s+is.*?end(?:\s+(?:package|\1)|;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "entity_decl": re.compile(
        # \b (not \W) so an entity at file offset 0 is matched; end(?:\s+name|\s*;)
        # so `end;` with no whitespace is matched (mirrors package_decl).
        r"(?<!:)\bentity\s+(\w+)\s+is.*?end(?:\s+(?:entity|\1)|\s*;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "vhdl_component_decl": re.compile(
        r"(?<!:)\bcomponent\s+(\w+)\s+(?:is|).*?end(?:\s+(?:component|\1)|\s*;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "component_inst": re.compile(
        # allow the optional explicit `component` keyword: `u0 : component foo port map(...)`
        # No leading `\s*` (unlike the other patterns here, this one has no
        # literal-keyword anchor before the first capture group) -- findall's
        # global scan already tries every start position, so a leading `\s*`
        # captures no extra matches, but on a long run of non-`\w` characters
        # (e.g. a huge comment/whitespace-only file) it forces catastrophic
        # backtracking: `\s*` greedily eats the whole run, `(\w+)` fails, and
        # it must retry one character shorter at every position tried by the
        # scan, which is O(n) per start x O(n) starts = O(n^2). Confirmed via
        # a differential check (identical findall() results with/without it
        # on every fixture .vhd plus hand-built edge cases) and by timing:
        # ~30KB of blank lines already exceeded an 8s budget with the leading
        # `\s*`, vs sub-millisecond without it.
        r"(\w+)\s*:(?:\s*component|)\s*(\w+)(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "direct_inst": re.compile(
        # Same catastrophic-backtracking hazard (and same fix) as component_inst above.
        r"(\w+)\s*:\s*(?:entity\s+)?(\w+)\.(\w+)(?:\s*\(\s*\w+\s*\))?(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    # the trailing selector (`.all` / `.name`) is optional, so `use lib.pkg;` matches too
    "package_use": re.compile(r"\buse\s+(\w+)\.(\w+)(?:\.\w+)?\s*;", re.IGNORECASE | re.MULTILINE),
    "c_coef_file": re.compile(r'_?attribute\s+C_COEF_FILE?\s+of\s+(\w+)\s*:\s*label\s+is\s+"([^"]+)"\s*;', re.IGNORECASE),
    "is_du_within_envelope": re.compile(
        r'_?attribute\s+is_du_within_envelope?\s+of\s+(\w+)\s*:\s*label\s+is\s+"true"\s*;', re.IGNORECASE
    ),
}


def parse_vhdl_file(loc: Path, lib=LIB_DEFAULT, ver=None) -> SourceFile:
    """Parse a VHDL file into a :class:`SourceFile` (provides/requires/direct_deps)."""
    log.info(f"parsing VHDL file {lib}: {loc}")
    vhdl = vhdl_remove_protected_code(vhdl_remove_comments(read_text_file_contents(loc)))
    sf = SourceFile(loc, FileType.VHDL, lib=lib, ver=ver)
    folder = Path(loc).parent

    by_inst = {}  # instance label -> required Name (to drop encrypted-IP instances)
    to_remove = []
    matches = {key: pattern.findall(vhdl) for key, pattern in vhdl_regex_patterns.items()}
    for construct, found in matches.items():
        if construct in ("package_decl", "entity_decl"):
            for item in found:
                add_unique(sf.provides, Name(lib, item))
        elif construct == "vhdl_component_decl":
            pass  # declarations are not dependencies
        elif construct == "component_inst":
            for inst, component in found:
                name = Name(lib, component)
                by_inst[inst] = name
                add_unique(sf.requires, name)
        elif construct == "direct_inst":
            for inst, dep_lib, ent in found:
                name = Name(lib if dep_lib == LIB_DEFAULT else dep_lib, ent)
                by_inst[inst] = name
                add_unique(sf.requires, name)
        elif construct == "package_use":
            for dep_lib, pkg in found:
                add_unique(sf.requires, Name(lib if dep_lib == LIB_DEFAULT else dep_lib, pkg))
        elif construct == "c_coef_file":
            for _instance, coef in found:
                sf.direct_deps.append(folder / coef)
        elif construct == "is_du_within_envelope":
            to_remove.extend(found)
        else:
            raise Exception(f"error construct '{construct}'")

    # Drop dependencies of encrypted-IP instances.
    for inst in to_remove:
        dep_name = by_inst.get(inst)
        if dep_name is not None and dep_name in sf.requires:
            sf.requires.remove(dep_name)
    return sf


# }}}
