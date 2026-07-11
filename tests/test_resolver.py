"""Unit tests for the Resolver (flat index + compile-order walk)."""

from pathlib import Path

from hdldepends.config import build_resolver
from hdldepends.model import FileType, Name, SourceFile
from hdldepends.resolver import Resolver
from hdldepends.util import resolve_abs_path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_resolver_simple_chain():
    r = Resolver()
    leaf = SourceFile(Path("/x/leaf.vhd"), FileType.VHDL, provides=[Name("work", "leaf")])
    top = SourceFile(Path("/x/top.vhd"), FileType.VHDL, provides=[Name("work", "top")], requires=[Name("work", "leaf")])
    r.add(leaf)
    r.add(top)
    assert [s.loc.stem for s in r.compile_order(top)] == ["leaf", "top"]


def test_compile_order_deep_chain_no_recursion_error():
    # compile_order's walk is driven by an explicit-stack trampoline (not
    # Python recursion / chained `yield from`, both of which still consume
    # the interpreter's recursion budget one frame per depth level), so this
    # must not raise RecursionError even for a chain far deeper than
    # sys.getrecursionlimit() (default 1000). Built directly (no file I/O) to
    # isolate the resolver's own behaviour from parsing cost.
    n = 5000
    r = Resolver()
    files = []
    for i in range(n):
        sf = SourceFile(Path(f"/x/n{i}.vhd"), FileType.VHDL, provides=[Name("work", f"n{i}")])
        if i > 0:
            sf.requires.append(Name("work", f"n{i - 1}"))
        files.append(sf)
        r.add(sf)
    order = r.compile_order(files[-1])  # n{n-1} depends on n{n-2} depends on ... depends on n0
    assert [f.loc.stem for f in order] == [f"n{i}" for i in range(n)]


def test_resolver_ignored_library_not_a_dependency():
    r = Resolver()
    r.ignore_libs.add("ieee")
    top = SourceFile(
        Path("/x/top.vhd"), FileType.VHDL, provides=[Name("work", "top")], requires=[Name("ieee", "std_logic_1164")]
    )
    r.add(top)
    assert [s.loc.stem for s in r.compile_order(top)] == ["top"]


def _order_stems(monkeypatch, fixture, top_entity):
    monkeypatch.chdir(FIXTURES / fixture)
    r = build_resolver("hdldeps.toml", work_dir=Path("."))
    top = r.find_top(Name("work", top_entity))
    return [f.loc.stem for f in r.compile_order(top)]


def test_compile_order_vhdl_dep_before_dependent(monkeypatch):
    assert _order_stems(monkeypatch, "vhdl_basic", "del21") == ["del211", "del21"]


def test_compile_order_bd_nested_before_top(monkeypatch):
    stems = _order_stems(monkeypatch, "bd_compile", "design_1")
    assert stems[-1] == "design_1"
    assert "bd_hdl" in stems and "design_2" in stems
    assert stems.index("design_2") < stems.index("design_1")


# --- direct deps must be deduplicated in the compile order ------------------

def test_compile_order_dedups_shared_direct_dep():
    # A direct dep (e.g. a coefficient file) shared by two parents must appear
    # exactly once in the compile order, not once per parent.
    r = Resolver()
    shared = Path("/x/shared.coe")
    a = SourceFile(Path("/x/a.xci"), FileType.X_XCI, provides=[Name("work", "a")])
    a.direct_deps.append(shared)
    b = SourceFile(Path("/x/b.xci"), FileType.X_XCI, provides=[Name("work", "b")])
    b.direct_deps.append(shared)
    top = SourceFile(
        Path("/x/top.vhd"), FileType.VHDL, provides=[Name("work", "top")],
        requires=[Name("work", "a"), Name("work", "b")],
    )
    r.add(a)
    r.add(b)
    r.add(top)

    order = r.compile_order(top)
    locs = [sf.loc for sf in order]
    assert locs.count(resolve_abs_path(shared)) == 1
    assert {sf.loc.stem for sf in order} == {"shared", "a", "b", "top"}


def test_compile_order_direct_dep_pointing_at_project_file_not_duplicated():
    # A direct dep that resolves to the SAME location as a file already placed
    # in the order via its own requires-walk must not be re-emitted.
    r = Resolver()
    leaf = SourceFile(Path("/x/leaf.vhd"), FileType.VHDL, provides=[Name("work", "leaf")])
    mid = SourceFile(
        Path("/x/mid.vhd"), FileType.VHDL, provides=[Name("work", "mid")],
        requires=[Name("work", "leaf")],
    )
    # `mid` also (redundantly/oddly) lists leaf.vhd as a direct dep.
    mid.direct_deps.append(Path("/x/leaf.vhd"))
    r.add(leaf)
    r.add(mid)

    order = r.compile_order(mid)
    assert [sf.loc.stem for sf in order].count("leaf") == 1


# --- a direct dep that is ALSO an indexed project file must get -------------
# a full post-order walk (its own requires emitted first), not a dependency-
# blind append that can also duplicate it when reached normally afterwards.

def test_compile_order_direct_dep_that_is_a_project_file_walked_not_blind_appended():
    # a.direct_deps=[leaf.loc] and leaf is itself an indexed file: previously
    # leaf was blindly appended when a was walked, then appended AGAIN when
    # b's normal `requires` walk reached it, so leaf appeared twice.
    r = Resolver()
    leaf = SourceFile(Path("/x/leaf.vhd"), FileType.VHDL, provides=[Name("work", "leaf")])
    a = SourceFile(Path("/x/a.vhd"), FileType.VHDL, provides=[Name("work", "a")])
    a.direct_deps.append(Path("/x/leaf.vhd"))
    b = SourceFile(
        Path("/x/b.vhd"), FileType.VHDL, provides=[Name("work", "b")], requires=[Name("work", "leaf")],
    )
    top = SourceFile(
        Path("/x/top.vhd"), FileType.VHDL, provides=[Name("work", "top")],
        requires=[Name("work", "a"), Name("work", "b")],
    )
    r.add(leaf)
    r.add(a)
    r.add(b)
    r.add(top)

    order = r.compile_order(top)
    stems = [sf.loc.stem for sf in order]
    assert stems.count("leaf") == 1
    assert stems.index("leaf") < stems.index("a")  # placed before its user, not blind-appended after


def test_compile_order_direct_dep_project_file_keeps_its_own_deps_ordered_first():
    # Deeper repro: a.direct_deps=[x.loc], x itself requires y, and b also
    # requires x. Previously this yielded ['x', 'a', 'y', 'x', 'b', 'top'] --
    # x emitted dependency-blind (BEFORE its own requirement y) via a's direct
    # dep, then duplicated when b's normal requires-walk reached it properly.
    r = Resolver()
    y = SourceFile(Path("/x/y.vhd"), FileType.VHDL, provides=[Name("work", "y")])
    x = SourceFile(Path("/x/x.vhd"), FileType.VHDL, provides=[Name("work", "x")], requires=[Name("work", "y")])
    a = SourceFile(Path("/x/a.vhd"), FileType.VHDL, provides=[Name("work", "a")])
    a.direct_deps.append(Path("/x/x.vhd"))
    b = SourceFile(Path("/x/b.vhd"), FileType.VHDL, provides=[Name("work", "b")], requires=[Name("work", "x")])
    top = SourceFile(
        Path("/x/top.vhd"), FileType.VHDL, provides=[Name("work", "top")],
        requires=[Name("work", "a"), Name("work", "b")],
    )
    r.add(y)
    r.add(x)
    r.add(a)
    r.add(b)
    r.add(top)

    order = r.compile_order(top)
    stems = [sf.loc.stem for sf in order]
    assert stems == ["y", "x", "a", "b", "top"]
    assert stems.count("x") == 1


# --- ambiguous (non-Xilinx-selectable) candidates warn once per Name --------

def test_resolve_ambiguous_candidates_warns_once_per_name(capsys):
    r = Resolver()
    a = SourceFile(Path("/x/a1.vhd"), FileType.VHDL, provides=[Name("work", "dup")])
    b = SourceFile(Path("/x/a2.vhd"), FileType.VHDL, provides=[Name("work", "dup")])
    r.add(a)
    r.add(b)

    first = r.resolve(Name("work", "dup"))
    second = r.resolve(Name("work", "dup"))
    assert first is a and second is a  # first candidate wins, consistently

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert err.count("dup") == 1  # warned exactly once, not once per lookup call


def test_resolve_unambiguous_name_never_warns(capsys):
    r = Resolver()
    a = SourceFile(Path("/x/a.vhd"), FileType.VHDL, provides=[Name("work", "solo")])
    r.add(a)
    assert r.resolve(Name("work", "solo")) is a
    assert capsys.readouterr().err == ""


# --- Resolver.add must not double-index a diamond re-add, and must not ------
# leave a stale object in by_name when a loc is replaced: add() is an
# unconditional replace-with-cleanup -- last write always wins in both by_loc
# and by_name (so a later-parsed real file supersedes an unparsed init_files
# stub with the same loc), and the previous object's provides entries are
# removed from by_name so no stale, no-longer-in-by_loc object lingers.

def test_add_same_file_twice_indexed_once_in_by_name():
    # Same file listed by two sub-configs (the diamond case): by_name must
    # not accumulate a second SourceFile object for the same loc.
    r = Resolver()
    sf1 = SourceFile(Path("/x/a.vhd"), FileType.VHDL, lib="work", provides=[Name("work", "a")])
    sf2 = SourceFile(Path("/x/a.vhd"), FileType.VHDL, lib="work", provides=[Name("work", "a")])
    r.add(sf1)
    r.add(sf2)
    assert r.by_name[Name("work", "a")] == [sf2]
    assert r.by_loc[sf1.loc] is sf2  # last write wins, even for identical content


def test_add_same_loc_different_lib_replaces_and_drops_stale_by_name_entry():
    # Different lib/content for the same loc: by_loc can only ever hold ONE
    # object per loc, so the second add's lib wins there -- and, since by_name
    # must never point at an object by_loc no longer agrees is current, the
    # first add's by_name entry is cleaned up rather than left dangling.
    r = Resolver()
    sf1 = SourceFile(Path("/x/a.vhd"), FileType.VHDL, lib="lib_a", provides=[Name("lib_a", "a")])
    sf2 = SourceFile(Path("/x/a.vhd"), FileType.VHDL, lib="lib_b", provides=[Name("lib_b", "a")])
    r.add(sf1)
    r.add(sf2)
    assert Name("lib_a", "a") not in r.by_name  # stale entry removed, not left dangling
    assert r.by_name[Name("lib_b", "a")] == [sf2]
    assert r.by_loc[sf1.loc] is sf2  # last write wins
