"""Adversarial parser probes.

These deliberately stress the regex/heuristic assumptions in the VHDL and
Verilog parsers. Each test asserts the *correct* behaviour; failures reveal
where the heuristics break. Confirmed breakages are marked xfail with a reason
so the suite stays green while documenting the bug.
"""

import time
from pathlib import Path

from hdldepends.parsers.verilog import (
    parse_verilog_file,
    verilog_extract_module_declarations,
    verilog_extract_module_instantiations,
    verilog_extract_package_imports,
    verilog_extract_packages,
)
from hdldepends.parsers.vhdl import parse_vhdl_file, vhdl_remove_protected_code
from hdldepends.util import resolve_abs_path


def _vhdl(tmp_path: Path, src: str, lib: str = "work"):
    p = tmp_path / "f.vhd"
    p.write_text(src)
    return parse_vhdl_file(p, lib=lib, ver=None)


def _verilog(tmp_path: Path, src: str, suffix: str = ".sv"):
    p = tmp_path / f"f{suffix}"
    p.write_text(src)
    return parse_verilog_file(p, None, [], [])


def _names(name_list):
    return {(n.lib, n.name) for n in name_list}


# --- VHDL ------------------------------------------------------------------

def test_vhdl_entity_uppercase_detected(tmp_path):
    # case-insensitive (not at file offset 0 -- see xfail below for that bug)
    f = _vhdl(tmp_path, "library ieee;\nENTITY Foo IS\nEND ENTITY;\n")
    assert ("work", "foo") in _names(f.provides)


def test_vhdl_entity_at_file_start(tmp_path):
    # Fixed: entity regex now uses `\b` so an entity at file offset 0 is detected.
    f = _vhdl(tmp_path, "entity foo is\nend entity;\n")
    assert ("work", "foo") in _names(f.provides)


def test_vhdl_entity_end_no_space_before_semicolon(tmp_path):
    # Fixed: entity regex now matches `end;` (no whitespace) as well as `end ;`.
    f = _vhdl(tmp_path, "library ieee;\nentity foo is\nend;\n")
    assert ("work", "foo") in _names(f.provides)


def test_vhdl_entity_in_line_comment_not_detected(tmp_path):
    f = _vhdl(tmp_path, "-- entity ghost is\nentity real_ent is\nend entity;\n")
    assert ("work", "ghost") not in _names(f.provides)
    assert ("work", "real_ent") in _names(f.provides)


def test_vhdl_entity_in_block_comment_not_detected(tmp_path):
    f = _vhdl(tmp_path, "/* entity ghost is end; */\nentity real_ent is\nend entity;\n")
    assert ("work", "ghost") not in _names(f.provides)


def test_vhdl_entity_name_in_string_literal_not_a_dependency(tmp_path):
    # A string mentioning entity-like text must not create a dependency.
    src = (
        "entity top is end entity;\n"
        "architecture a of top is begin\n"
        '  assert false report "entity work.fake port map" severity note;\n'
        "end architecture;\n"
    )
    f = _vhdl(tmp_path, src)
    assert ("work", "fake") not in _names(f.requires)


def test_vhdl_two_entities_one_file(tmp_path):
    f = _vhdl(tmp_path, "library ieee;\nentity a is end entity;\nentity b is end entity;\n")
    assert ("work", "a") in _names(f.provides)
    assert ("work", "b") in _names(f.provides)


def test_vhdl_use_clause_package_dep(tmp_path):
    f = _vhdl(tmp_path, "library foo;\nuse foo.bar.all;\nentity e is end entity;\n")
    assert ("foo", "bar") in _names(f.requires)


def test_vhdl_direct_instantiation_dep(tmp_path):
    src = (
        "entity top is end entity;\n"
        "architecture a of top is begin\n"
        "  i_sub : entity work.sub port map (clk => clk);\n"
        "end architecture;\n"
    )
    f = _vhdl(tmp_path, src)
    assert ("work", "sub") in _names(f.requires)


def test_vhdl_tabs_and_irregular_whitespace(tmp_path):
    f = _vhdl(tmp_path, "library ieee;\nentity\t\tfoo\tis\nend\tentity\t;\n")
    assert ("work", "foo") in _names(f.provides)


# --- VHDL catastrophic-backtracking regression ------------------------------

def test_vhdl_large_comment_only_file_does_not_hang(tmp_path):
    # Regression: component_inst / direct_inst previously opened with an
    # unanchored `\s*` before their first capture group. It sat outside any
    # capture group, so it added no matching power (findall()'s global scan
    # already tries every start position) -- but on a long run of non-`\w`
    # characters it forced catastrophic backtracking: `\s*` greedily eats the
    # whole run, `(\w+)` fails, and the engine retries one character shorter
    # at every one of the O(n) scan positions, i.e. O(n^2). A comment-only
    # file (which reduces to a long run of blank lines after comment
    # stripping) is a completely ordinary, non-adversarial way to trigger
    # this: measured before the fix, a mere 64,000-char blank-line string
    # already exceeded an 8s budget; this uses a larger, still-realistic
    # ~2.9MB file (80,000 comment lines) and asserts it parses in well under
    # a second, not minutes/hours.
    src = "-- padding comment line filler text\n" * 80_000
    f = tmp_path / "big.vhd"
    f.write_text(src)
    t0 = time.perf_counter()
    sf = parse_vhdl_file(f)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"parse_vhdl_file took {dt:.1f}s on a comment-only file (expected a fraction of a second)"
    assert sf.provides == [] and sf.requires == []


# --- VHDL protected-code stripping ------------------------------------------

def test_vhdl_remove_protected_duplicate_blank_lines_before_marker():
    # The previous implementation de-duplicated lines with dict.fromkeys() and
    # then used the index found in that DEDUPED list to slice the ORIGINAL
    # lines, so duplicate blank lines before the marker shifted the cut and
    # leaked the marker line itself (and everything before it) into the output.
    src = "a\n\nb\n\n`protect end_protected\nsecret_after"
    assert vhdl_remove_protected_code(src) == "secret_after"


def test_vhdl_remove_protected_begin_end_pair_mid_file():
    src = "before\n`protect begin_protected\nsecret\n`protect end_protected\nafter\n"
    assert vhdl_remove_protected_code(src) == "before\nafter\n"


def test_vhdl_remove_protected_two_regions():
    src = (
        "x\n`protect begin_protected\nsecret1\n`protect end_protected\n"
        "y\n`protect begin_protected\nsecret2\n`protect end_protected\n"
        "z\n"
    )
    assert vhdl_remove_protected_code(src) == "x\ny\nz\n"


def test_vhdl_remove_protected_end_marker_only_drops_from_start():
    # Xilinx encrypted netlists sometimes start mid-region: an end marker with
    # no preceding begin marker means everything before it is untrustworthy.
    src = "leaked license header\nmore leaked text\n`protect end_protected\nreal code\n"
    assert vhdl_remove_protected_code(src) == "real code\n"


def test_vhdl_remove_protected_no_marker_passthrough():
    src = "library ieee;\nentity foo is\nend entity;\n"
    assert vhdl_remove_protected_code(src) == src


def test_vhdl_remove_protected_marker_to_eof():
    # A begin marker with no matching end: drop through EOF, keep what came before.
    src = "before\n`protect begin_protected\nsecret with no terminator"
    assert vhdl_remove_protected_code(src) == "before\n"


def test_vhdl_remove_protected_tolerates_indent_and_trailing_text():
    src = "before\n    `protect begin_protected extra\nsecret\n\t`protect end_protected junk\nafter\n"
    assert vhdl_remove_protected_code(src) == "before\nafter\n"


def test_vhdl_remove_protected_later_orphan_end_marker_keeps_surrounding_code():
    # The "drop everything before an unmatched end marker" branch
    # previously fired on EVERY iteration, not just at the start of the scan,
    # so a SECOND, orphan end_protected marker occurring AFTER a legitimate
    # begin/end pair deleted the legitimate code between that pair and the
    # stray marker. It must now only strip the marker line itself.
    src = "a\n`protect begin_protected\nsecret1\n`protect end_protected\nmiddle_code\n`protect end_protected\nafter"
    result = vhdl_remove_protected_code(src)
    assert result == "a\nmiddle_code\nafter"
    assert "secret1" not in result


# --- Verilog ---------------------------------------------------------------

def test_verilog_module_basic(tmp_path):
    f = _verilog(tmp_path, "module top (input a); endmodule\n")
    assert ("work", "top") in _names(f.provides)


def test_verilog_module_in_comment_not_detected(tmp_path):
    f = _verilog(tmp_path, "// module ghost (\nmodule real_mod (input a); endmodule\n")
    assert ("work", "ghost") not in _names(f.provides)
    assert ("work", "real_mod") in _names(f.provides)


def test_verilog_parameterized_instantiation(tmp_path):
    src = (
        "module top;\n"
        "  sub #(.W(8)) u_sub (.clk(clk), .d(d));\n"
        "endmodule\n"
    )
    f = _verilog(tmp_path, src)
    assert ("work", "sub") in _names(f.requires)


def test_verilog_package_import(tmp_path):
    f = _verilog(tmp_path, "module top; import mypkg::*; endmodule\n")
    assert ("work", "mypkg") in _names(f.requires)


def test_verilog_instantiation_name_in_string_not_dep(tmp_path):
    src = 'module top;\n  initial $display("sub u_sub (.x(y));");\nendmodule\n'
    f = _verilog(tmp_path, src)
    assert ("work", "sub") not in _names(f.requires)


# --- declaration/package/import extraction must also blank ------------------
# string literals first. Only verilog_extract_module_instantiations did this;
# a log string containing code-like text (e.g. a `$display` with a `;`
# terminator) phantom-declared a module/package/import from inside the string.

def test_verilog_display_string_does_not_phantom_declare_module(tmp_path):
    # `$display("entering module foo; init done")` previously phantom-declared
    # a module named "foo" (module_declaration_regex ran on un-blanked text).
    src = 'module tb;\n  initial $display("entering module foo; init done");\nendmodule\n'
    f = _verilog(tmp_path, src)
    assert ("work", "foo") not in _names(f.provides)
    assert ("work", "tb") in _names(f.provides)


def test_verilog_extract_module_declarations_ignores_text_in_string_literal():
    src = 'module tb;\n  initial $display("entering module foo; init done");\nendmodule\n'
    assert verilog_extract_module_declarations(src) == ["tb"]


def test_verilog_extract_packages_ignores_text_in_string_literal():
    src = 'module tb;\n  initial $display("package fake_pkg;");\nendmodule\npackage real_pkg;\n'
    assert verilog_extract_packages(src) == ["real_pkg"]


def test_verilog_extract_package_imports_ignores_text_in_string_literal():
    src = 'module tb;\n  initial $display("import fake_pkg::*;");\n  import real_pkg::*;\nendmodule\n'
    assert verilog_extract_package_imports(src) == ["real_pkg"]


def test_verilog_nested_param_instantiation(tmp_path):
    # parameter list with nested parens, e.g. $clog2(32)
    src = "module top;\n  sub #(.W($clog2(32)), .D(8)) u (.clk(c), .d(d));\nendmodule\n"
    f = _verilog(tmp_path, src)
    assert ("work", "sub") in _names(f.requires)


def test_verilog_multiple_distinct_instantiations(tmp_path):
    src = (
        "module top;\n"
        "  alpha u0 (.a(x));\n"
        "  beta  u1 (.b(y));\n"
        "endmodule\n"
    )
    f = _verilog(tmp_path, src)
    assert ("work", "alpha") in _names(f.requires)
    assert ("work", "beta") in _names(f.requires)


def test_verilog_function_call_not_instantiation(tmp_path):
    # `result = compute(a, b);` is a call, not an instantiation.
    src = "module top;\n  assign result = compute(a, b);\nendmodule\n"
    f = _verilog(tmp_path, src)
    assert ("work", "compute") not in _names(f.requires)


def test_verilog_positional_ports_not_detected(tmp_path):
    # Current heuristic only detects named (.port(...)) connections; positional
    # port maps are not treated as instantiations. Lock this behaviour.
    src = "module top;\n  sub u (a, b, c);\nendmodule\n"
    f = _verilog(tmp_path, src)
    assert ("work", "sub") not in _names(f.requires)


def test_verilog_keyword_not_treated_as_instantiation(tmp_path):
    # `if (...)` etc must not be read as a module instantiation.
    src = (
        "module top;\n"
        "  always @(posedge clk) if (en) q <= d;\n"
        "endmodule\n"
    )
    f = _verilog(tmp_path, src)
    assert ("work", "if") not in _names(f.requires)
    assert ("work", "always") not in _names(f.requires)


def test_verilog_module_regex_requires_word_boundary():
    # Without a `\bmodule\b` boundary, "rand_module u_inst (...)" phantom-
    # declares a module named after its own instance ("u_inst").
    assert verilog_extract_module_declarations("rand_module u_inst (.a(b));") == []


def test_verilog_portless_module_declaration_detected():
    # Every Verilog testbench is portless (no top-level ports); previously the
    # declaration regex required a trailing "(" so no testbench module was ever
    # detected as a provider.
    assert verilog_extract_module_declarations("module tb;\nendmodule") == ["tb"]
    assert verilog_extract_module_declarations("endmodule") == []  # never matched


def test_verilog_portless_module_end_to_end(tmp_path):
    f = _verilog(tmp_path, "module tb;\n  initial begin end\nendmodule\n")
    assert ("work", "tb") in _names(f.provides)


def test_verilog_portless_module_with_parameters():
    decls = verilog_extract_module_declarations("module tb #(parameter W = 8);\nendmodule")
    assert decls == ["tb"]


# --- module declaration parameter list, one level of nested -----------------
# parens. The old `[^)]*` group could not span nested parens at all, so e.g.
# `#(parameter int W = $clog2(8))` (a very ordinary construct) was missed --
# either silently dropping the declaration ('(' form) or, for the ';' form,
# causing the whole match to fail outright (see the portless case below).

def test_verilog_module_declaration_nested_paren_default_portless():
    decls = verilog_extract_module_declarations("module tb #(parameter int W = $clog2(8));\nendmodule")
    assert decls == ["tb"]


def test_verilog_module_declaration_nested_paren_default_ported():
    decls = verilog_extract_module_declarations("module tb #(parameter int W = $clog2(8)) (input clk);\nendmodule")
    assert decls == ["tb"]


def test_verilog_module_declaration_doubly_nested_parameter_still_unsupported():
    # Pinned limitation: the one-level-nesting regex cannot span TWO levels of
    # nesting in the parameter list (a default computed from a
    # function-of-a-function call). This documents current behaviour, not a
    # requirement -- if this ever starts passing, update it rather than
    # deleting it (silently regaining/losing support should be noticed).
    src = "module tb #(parameter int W = $foo($bar(8)));\nendmodule"
    assert verilog_extract_module_declarations(src) == []


def test_verilog_module_declaration_param_list_no_catastrophic_backtracking():
    # The nested-paren-aware group is a `(?:alt1|alt2)*` repetition, the
    # classic shape for catastrophic backtracking (mirrors the VHDL
    # component_inst/direct_inst fix -- see
    # test_vhdl_large_comment_only_file_does_not_hang) IF the two alternatives
    # overlap. They don't here (`[^()]` explicitly excludes '(' and ')', so at
    # any position at most one alternative can even start) -- but prove it: a
    # ~1MB adversarial input, mixing a long non-paren run with one-level
    # nested groups and never properly closing the outer "#(", must still
    # parse in well under a second, not minutes/hours.
    src = "module m #(" + ("x" * 200 + "(" + "y" * 200 + ")") * 2500  # ~1MB, deliberately never closes "#("
    t0 = time.perf_counter()
    result = verilog_extract_module_declarations(src)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"verilog_extract_module_declarations took {dt:.1f}s (expected a fraction of a second)"
    assert result == []  # never closed -> correctly finds no declaration (not the point of this test)


def test_verilog_package_regex_requires_word_boundary():
    # "endpackage foo;" must not be misread as a package declaration "foo".
    assert verilog_extract_packages("endpackage foo;") == []


def test_verilog_package_regexes_are_case_sensitive():
    # Verilog is case-sensitive; the module regexes already are case-sensitive --
    # the package/import regexes must match that (they previously used re.IGNORECASE).
    assert verilog_extract_packages("PACKAGE Foo;") == []
    assert verilog_extract_package_imports("IMPORT mypkg::*;") == []
    # lower-case (the only legal spelling) still works
    assert verilog_extract_packages("package foo;") == ["foo"]


def test_verilog_truncated_instantiation_does_not_crash():
    # A file cut off mid-instantiation (e.g. truncated write) must not crash the
    # parser with `TypeError: string indices must be integers, not 'NoneType'`.
    assert verilog_extract_module_instantiations("module m; foo #(") == []


def test_verilog_truncated_file_end_to_end(tmp_path):
    f = _verilog(tmp_path, "module m; foo #(")
    assert ("work", "foo") not in _names(f.requires)


def test_verilog_include_first_match_wins_over_later_dir(tmp_path):
    # Compiler convention: first match wins (this file's dir, then include dirs
    # in listed order). A previous bug kept overwriting `found` so the LAST
    # matching include dir won instead.
    d1 = tmp_path / "dir1"
    d2 = tmp_path / "dir2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "foo.vh").write_text("// dir1 version\n")
    (d2 / "foo.vh").write_text("// dir2 version\n")
    main = tmp_path / "main.v"
    main.write_text('`include "foo.vh"\nmodule top; endmodule\n')

    sf = parse_verilog_file(main, None, [d1, d2], [d1 / "foo.vh", d2 / "foo.vh"])
    assert sf.include_locs == [resolve_abs_path(d1 / "foo.vh")]


def test_verilog_include_with_string_argument_still_resolves_alongside_f4(tmp_path):
    # verilog_extract_include_files must keep seeing the
    # ORIGINAL, un-blanked text -- its `include "file.vh"` target is itself a
    # string literal, so blanking it there (as the other extractors now do)
    # would erase the very text it needs to extract. Exercised alongside a
    # $display string that would phantom-declare a module if declarations
    # were (incorrectly) parsed from un-blanked text, so both sides of the F4
    # fix are proven together: the include still resolves, and no phantom
    # module is declared.
    inc = tmp_path / "foo.vh"
    inc.write_text("// empty include\n")
    main = tmp_path / "main.v"
    main.write_text(
        '`include "foo.vh"\n'
        'module top;\n  initial $display("entering module ghost; init done");\nendmodule\n'
    )
    sf = parse_verilog_file(main, None, [], [resolve_abs_path(inc)])
    assert sf.include_locs == [resolve_abs_path(inc)]
    assert ("work", "ghost") not in _names(sf.provides)
    assert ("work", "top") in _names(sf.provides)
