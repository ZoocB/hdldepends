"""Regression tests pinning multi-``sub`` config gathering.

Historically, a top-level config with ``sub: [sub1.yaml, sub2.yaml]`` silently
skipped the FIRST sub config, so its source file was missing from every
output. The ``gather()`` rewrite in :mod:`hdldepends.config` fixed that; these
tests pin *file-contribution completeness* through ``sub`` edges (every listed
sub -- first, middle, last, nested, diamond-shared, cross-format -- must land
its files in the resolver) so the bug cannot come back unnoticed.

Complementary existing coverage (NOT duplicated here): circular-sub and
top-key-in-sub errors plus the bare diamond-is-allowed check live in
tests/test_adversarial_config.py; init-file dedup across subs in
tests/test_config.py / features tests.
"""

import os
import subprocess
import sys
from pathlib import Path

import hdldepends
from hdldepends.config import build_resolver

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _entity(name: str) -> str:
    return (
        "library ieee;\nuse ieee.std_logic_1164.all;\n\n"
        f"entity {name} is\n  port (clk : in std_logic);\nend entity;\n\n"
        f"architecture rtl of {name} is\nbegin\nend architecture;\n"
    )


def _instantiating_entity(name: str, *insts: str) -> str:
    body = "".join(f"  u_{e} : entity work.{e} port map (clk => clk);\n" for e in insts)
    return (
        "library ieee;\nuse ieee.std_logic_1164.all;\n\n"
        f"entity {name} is\n  port (clk : in std_logic);\nend entity;\n\n"
        f"architecture rtl of {name} is\nbegin\n{body}end architecture;\n"
    )


def _user_scenario(tmp_path: Path) -> None:
    """The reported project shape: top.yaml subs two sibling configs, each
    contributing one VHDL file, and contributes one itself (the top entity,
    which instantiates both sub entities)."""
    (tmp_path / "sub1.vhd").write_text(_entity("sub1_ent"))
    (tmp_path / "sub2.vhd").write_text(_entity("sub2_ent"))
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", "sub1_ent", "sub2_ent"))
    (tmp_path / "sub1.yaml").write_text("vhdl_files:\n  work:\n    - ./sub1.vhd\n")
    (tmp_path / "sub2.yaml").write_text("vhdl_files:\n  work:\n    - ./sub2.vhd\n")
    (tmp_path / "top.yaml").write_text(
        "sub:\n  - sub1.yaml\n  - sub2.yaml\n"
        "vhdl_files:\n  work:\n    - ./top.vhd\n"
        "top_entity: top_ent\n"
    )


# --- 1. the user's exact scenario --------------------------------------------

def test_first_sub_config_is_not_silently_skipped(tmp_path, monkeypatch):
    _user_scenario(tmp_path)
    monkeypatch.chdir(tmp_path)

    r = build_resolver("top.yaml", work_dir=Path("."))
    stems = {p.stem for p in r.by_loc}
    assert "sub1" in stems, "FIRST sub config's file missing -- the historical bug"
    assert {"sub1", "sub2", "top"} <= stems

    result = hdldepends.analyze("top.yaml")
    paths = [f["path"] for f in result.compile_order]
    assert str(tmp_path / "sub1.vhd") in paths, "FIRST sub's file missing from compile order"
    assert str(tmp_path / "sub2.vhd") in paths
    # top last (is_top), both sub files ordered before it
    assert paths[-1] == str(tmp_path / "top.vhd")
    assert result.compile_order[-1]["is_top"] is True


# --- 2. completeness without a top walk (file-list surface) ------------------

def test_all_sub_files_gathered_even_without_a_top(tmp_path, monkeypatch):
    _user_scenario(tmp_path)
    # Rewrite the top config without any top key: gathering completeness must
    # not depend on anything instantiating (or walking to) the files.
    (tmp_path / "top.yaml").write_text(
        "sub:\n  - sub1.yaml\n  - sub2.yaml\nvhdl_files:\n  work:\n    - ./top.vhd\n"
    )
    monkeypatch.chdir(tmp_path)

    r = build_resolver("top.yaml", work_dir=Path("."))
    expected = {tmp_path / n for n in ("sub1.vhd", "sub2.vhd", "top.vhd")}
    assert expected <= set(r.by_loc)
    assert expected <= {sf.loc for sf in r.files}


# --- 3. sub configs in different subdirectories -------------------------------

def test_sub_config_paths_are_relative_to_each_configs_own_dir(tmp_path, monkeypatch):
    # `sub` entries resolve relative to the referencing config's directory,
    # and source paths inside each sub config resolve relative to THAT sub
    # config's own directory (gather uses cwd = loc.parent).
    a_dir = tmp_path / "ip" / "a"
    b_dir = tmp_path / "ip" / "b"
    a_dir.mkdir(parents=True)
    b_dir.mkdir(parents=True)
    (a_dir / "a_ent.vhd").write_text(_entity("a_ent"))
    (b_dir / "b_ent.vhd").write_text(_entity("b_ent"))
    (a_dir / "a.yaml").write_text("vhdl_files:\n  work:\n    - ./a_ent.vhd\n")
    (b_dir / "b.yaml").write_text("vhdl_files:\n  work:\n    - ./b_ent.vhd\n")
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", "a_ent", "b_ent"))
    (tmp_path / "top.yaml").write_text(
        "sub:\n  - ip/a/a.yaml\n  - ip/b/b.yaml\n"
        "vhdl_files:\n  work:\n    - ./top.vhd\n"
        "top_entity: top_ent\n"
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("top.yaml")
    paths = [f["path"] for f in result.compile_order]
    assert str(a_dir / "a_ent.vhd") in paths
    assert str(b_dir / "b_ent.vhd") in paths
    assert paths[-1] == str(tmp_path / "top.vhd")


# --- 4. nested subs -----------------------------------------------------------

def test_nested_subs_all_contribute_and_order_is_leaf_first(tmp_path, monkeypatch):
    (tmp_path / "leaf.vhd").write_text(_entity("leaf_ent"))
    (tmp_path / "mid.vhd").write_text(_instantiating_entity("mid_ent", "leaf_ent"))
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", "mid_ent"))
    (tmp_path / "leaf.yaml").write_text("vhdl_files:\n  work:\n    - ./leaf.vhd\n")
    (tmp_path / "mid.yaml").write_text("sub: leaf.yaml\nvhdl_files:\n  work:\n    - ./mid.vhd\n")
    (tmp_path / "top.yaml").write_text(
        "sub: mid.yaml\nvhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top_ent\n"
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("top.yaml")
    paths = [f["path"] for f in result.compile_order]
    assert paths == [str(tmp_path / n) for n in ("leaf.vhd", "mid.vhd", "top.vhd")]


# --- 5. diamond with file contribution ----------------------------------------

def test_diamond_shared_sub_contributes_its_file_exactly_once(tmp_path, monkeypatch):
    # Both l and r sub the same shared.yaml; its file must be gathered exactly
    # ONCE (the `done` set dedup), not dropped and not duplicated.
    (tmp_path / "shared.vhd").write_text(_entity("shared_ent"))
    (tmp_path / "l.vhd").write_text(_instantiating_entity("l_ent", "shared_ent"))
    (tmp_path / "r.vhd").write_text(_instantiating_entity("r_ent", "shared_ent"))
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", "l_ent", "r_ent"))
    (tmp_path / "shared.yaml").write_text("vhdl_files:\n  work:\n    - ./shared.vhd\n")
    (tmp_path / "l.yaml").write_text("sub: shared.yaml\nvhdl_files:\n  work:\n    - ./l.vhd\n")
    (tmp_path / "r.yaml").write_text("sub: shared.yaml\nvhdl_files:\n  work:\n    - ./r.vhd\n")
    (tmp_path / "top.yaml").write_text(
        "sub:\n  - l.yaml\n  - r.yaml\nvhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top_ent\n"
    )
    monkeypatch.chdir(tmp_path)

    r = build_resolver("top.yaml", work_dir=Path("."))
    shared_loc = tmp_path / "shared.vhd"
    assert [sf.loc for sf in r.files].count(shared_loc) == 1

    result = hdldepends.analyze("top.yaml")
    paths = [f["path"] for f in result.compile_order]
    assert paths.count(str(shared_loc)) == 1
    assert {str(tmp_path / n) for n in ("shared.vhd", "l.vhd", "r.vhd", "top.vhd")} == set(paths)
    assert paths[-1] == str(tmp_path / "top.vhd")


# --- 6. three or more subs ------------------------------------------------------

def test_every_sub_of_many_contributes(tmp_path, monkeypatch):
    # First / middle / last positions in the sub list must all survive; a
    # gather bug that drops any position (not just the first) is caught here.
    names = ["s1", "s2", "s3", "s4"]
    for n in names:
        (tmp_path / f"{n}.vhd").write_text(_entity(f"{n}_ent"))
        (tmp_path / f"{n}.yaml").write_text(f"vhdl_files:\n  work:\n    - ./{n}.vhd\n")
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", *(f"{n}_ent" for n in names)))
    sub_lines = "".join(f"  - {n}.yaml\n" for n in names)
    (tmp_path / "top.yaml").write_text(
        f"sub:\n{sub_lines}vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top_ent\n"
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("top.yaml")
    paths = set(f["path"] for f in result.compile_order)
    for n in names:
        assert str(tmp_path / f"{n}.vhd") in paths, f"sub {n}.yaml's file was dropped"


# --- 7. mixed config formats ----------------------------------------------------

def test_sub_edges_are_config_format_agnostic(tmp_path, monkeypatch):
    # A YAML top may sub a TOML and a JSON config; load_config dispatches on
    # suffix per file, so files from every format must be gathered.
    (tmp_path / "t.vhd").write_text(_entity("t_ent"))
    (tmp_path / "j.vhd").write_text(_entity("j_ent"))
    (tmp_path / "top.vhd").write_text(_instantiating_entity("top_ent", "t_ent", "j_ent"))
    (tmp_path / "t.toml").write_text("vhdl_files = { work = ['./t.vhd'] }\n")
    (tmp_path / "j.json").write_text('{"vhdl_files": {"work": ["./j.vhd"]}}\n')
    (tmp_path / "top.yaml").write_text(
        "sub:\n  - t.toml\n  - j.json\nvhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top_ent\n"
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("top.yaml")
    paths = [f["path"] for f in result.compile_order]
    assert str(tmp_path / "t.vhd") in paths
    assert str(tmp_path / "j.vhd") in paths
    assert paths[-1] == str(tmp_path / "top.vhd")


# --- 8. end-to-end through the real CLI ------------------------------------------

def test_cli_file_list_contains_files_from_every_sub(tmp_path):
    _user_scenario(tmp_path)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "hdldepends.hdldepends", "top.yaml", "-o", "file-list", "out.txt"]
    proc = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    listing = (tmp_path / "out.txt").read_text()
    for n in ("sub1.vhd", "sub2.vhd", "top.vhd"):
        assert str(tmp_path / n) in listing, f"{n} missing from CLI file-list output"
