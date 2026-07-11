"""Adversarial resolver/ordering probes: cycles, diamonds, self-deps, missing
deps, case mismatch, deep chains, and cross-sub (flattened) resolution."""

from pathlib import Path

from hdldepends.config import build_resolver
from hdldepends.model import Name


def _ent(name: str, *deps: str) -> str:
    insts = "\n".join(f"  i_{d} : entity work.{d} port map (x => x);" for d in deps)
    return (
        f"library ieee;\nentity {name} is end entity;\n"
        f"architecture a of {name} is begin\n{insts}\nend architecture;\n"
    )


def _build(tmp_path, files: dict, monkeypatch):
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    listing = ", ".join(f"'./{n}'" for n in files)
    (tmp_path / "hdldeps.toml").write_text(f"ignore_libs=['ieee','std']\nvhdl_files={{work=[{listing}]}}\n")
    monkeypatch.chdir(tmp_path)
    return build_resolver("hdldeps.toml", work_dir=Path("."))


def _order(resolver, top: str):
    return [f.loc.stem for f in resolver.compile_order(resolver.find_top(Name("work", top)))]


def test_circular_dependency_terminates(tmp_path, monkeypatch):
    r = _build(tmp_path, {"a.vhd": _ent("a", "b"), "b.vhd": _ent("b", "a")}, monkeypatch)
    stems = _order(r, "a")
    assert set(stems) >= {"a", "b"}
    assert stems[-1] == "a"


def test_self_dependency_terminates(tmp_path, monkeypatch):
    r = _build(tmp_path, {"a.vhd": _ent("a", "a")}, monkeypatch)
    assert _order(r, "a") == ["a"]


def test_diamond_leaf_once_and_before_dependents(tmp_path, monkeypatch):
    files = {
        "top.vhd": _ent("top", "l", "r"),
        "l.vhd": _ent("l", "leaf"),
        "r.vhd": _ent("r", "leaf"),
        "leaf.vhd": _ent("leaf"),
    }
    r = _build(tmp_path, files, monkeypatch)
    stems = _order(r, "top")
    assert stems.count("leaf") == 1
    assert stems.index("leaf") < stems.index("l")
    assert stems.index("leaf") < stems.index("r")
    assert stems[-1] == "top"


def test_missing_dependency_is_skipped_not_fatal(tmp_path, monkeypatch):
    # An unresolved instantiation is warned about and skipped (not fatal).
    r = _build(tmp_path, {"a.vhd": _ent("a", "ghost")}, monkeypatch)
    stems = _order(r, "a")
    assert stems == ["a"]


def test_case_insensitive_dependency_resolves(tmp_path, monkeypatch):
    r = _build(tmp_path, {"a.vhd": _ent("a", "SUB"), "sub.vhd": _ent("sub")}, monkeypatch)
    assert _order(r, "a") == ["sub", "a"]


def test_deep_chain_orders_correctly(tmp_path, monkeypatch):
    n = 40
    files = {f"n{i}.vhd": _ent(f"n{i}", *([f"n{i+1}"] if i < n else [])) for i in range(n + 1)}
    r = _build(tmp_path, files, monkeypatch)
    stems = _order(r, "n0")
    assert stems[0] == f"n{n}" and stems[-1] == "n0"
    assert len(stems) == n + 1


def test_very_deep_chain_does_not_recursion_error(tmp_path, monkeypatch):
    # Regression: compile_order's walk used to be direct Python recursion, so
    # a dependency chain deeper than ~1000 files (well within reach of a real
    # project generated from a template or a long include chain) raised a
    # bare RecursionError instead of producing a compile order. n=2000 is
    # comfortably past the old ~998-deep crash threshold (measured with
    # sys.getrecursionlimit()'s default of 1000) and still completes in a
    # fraction of a second end-to-end (parsing all 2001 files + resolving).
    n = 2000
    files = {f"n{i}.vhd": _ent(f"n{i}", *([f"n{i + 1}"] if i < n else [])) for i in range(n + 1)}
    r = _build(tmp_path, files, monkeypatch)
    stems = _order(r, "n0")
    assert stems[0] == f"n{n}" and stems[-1] == "n0"
    assert len(stems) == n + 1


def test_cross_sub_resolution_flattened(tmp_path, monkeypatch):
    # top (main) depends on ea (sub a) and eb (sub b); all merge into one index.
    (tmp_path / "a.vhd").write_text(_ent("ea"))
    (tmp_path / "b.vhd").write_text(_ent("eb"))
    (tmp_path / "top.vhd").write_text(_ent("top", "ea", "eb"))
    (tmp_path / "a.toml").write_text("ignore_libs=['ieee','std']\nvhdl_files={work=['./a.vhd']}\n")
    (tmp_path / "b.toml").write_text("ignore_libs=['ieee','std']\nvhdl_files={work=['./b.vhd']}\n")
    (tmp_path / "main.toml").write_text(
        "ignore_libs=['ieee','std']\nsub=['a.toml','b.toml']\nvhdl_files={work=['./top.vhd']}\n"
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("main.toml", work_dir=Path("."))
    stems = {f.loc.stem for f in r.compile_order(r.find_top(Name("work", "top")))}
    assert {"top", "a", "b"} <= stems
