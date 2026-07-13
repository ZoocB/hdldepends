"""Pinned functional tests tracing this fork's behaviour back to the
upstream commit range ``ac3d402..079ab03`` -- ten commits that landed only in
the old monolith ``src/hdldepends/hdldepends.py`` on upstream ``main`` after
this fork's flat-index rewrite diverged. Each test names the upstream SHA(s)
it pins in a comment. Where an existing test already covers a behaviour
exactly, this file re-asserts it cheaply (a minimal, self-contained repro)
rather than duplicating the whole thing, and says so in a comment.

SHA -> behaviour map (also see each test's own comment):
  cd45117  schema version 1.03 -> 1.04; `package_use` regex: trailing
           `.all`/selector made optional (bare `use lib.pkg;` now matches too)
  1d3d152  `component_inst` regex: made the `component` keyword *required*
           (a regression -- broke the plain `u1 : bar port map(...)` form)
  079ab03  ...then fixed 1d3d152's regression by making the keyword optional
           again (both `component foo` and bare `foo` now match)
  9681804  `use lib.name;` where `name` is an entity, not a package: upstream
           falls back to `get_entity` and tolerates it (no crash) but does NOT
           wire up a dependency; see (c) below for this fork's superset
           behaviour
  490e1fb  direct deps (e.g. XCI coefficient files) no longer added twice when
           two XCI files share one
  fababfd / 1e70df8  XCI library inheritance from the instantiating VHDL file
  3ad7717  XCI version selection prefers upgrading (highest <= target) over
           downgrading (else lowest above)

Deliberately untested here (no behaviour to pin in this fork):
  0ba4cf4  fixed an args.file_file_type typo in the --top-file-type handler;
           this fork removed --top-file-type entirely (see CHANGELOG 0.2.0)
  079ab03 (2nd half) / fababfd (mtime tracking)  `equivalent()` gaining
           vhdl_component_deps and FileObj mtime/`exists` bookkeeping are only
           reachable from the pickle-cache staleness path; this fork removed
           pickle caching entirely
  af29e03  index-level X-file filtering -- superseded upstream within this
           very range (1e70df8 restored warn-only)
"""

from pathlib import Path

from hdldepends.config import build_resolver
from hdldepends.model import FileType, Name, SourceFile
from hdldepends.parsers.vhdl import parse_vhdl_file
from hdldepends.resolver import Resolver, _closest_x_version
from hdldepends.util import resolve_abs_path


def _names(name_list):
    return {(n.lib, n.name) for n in name_list}


# --- [cd45117] schema version bump 1.03 -> 1.04 ------------------------------
# HDL_DEPENDS_VERSION_NUM now matches upstream's 1.04 (constants.py); a config
# declaring `min_ver: 1.04` must load instead of being wrongly rejected by a
# tool that already has every 1.04-era feature.

def test_pin_cd45117_schema_version_1_04_config_loads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hdldeps.toml").write_text("min_ver = 1.04\n")
    assert build_resolver("hdldeps.toml", work_dir=Path(".")) is not None


# --- (a) [cd45117] `use lib.pkg;` and `use lib.pkg.all;` both -> Name(lib,pkg) -
# The bare-use form + explicit-`component`-keyword combo is already pinned by
# tests/test_parsers.py::test_parse_vhdl_explicit_component_keyword_and_bare_use;
# this test is the thin, SHA-labelled complement that also covers the `.all`
# form, so both regex-relevant variants of the upstream fix are pinned here.

def test_pin_cd45117_package_use_bare_and_dot_all_both_resolve(tmp_path):
    f = tmp_path / "t.vhd"
    f.write_text(
        "library work;\n"
        "use work.pkg_bare;\n"        # no trailing selector at all
        "use work.pkg_all.all;\n"     # trailing `.all`
        "entity t is end entity;\n"
    )
    reqs = _names(parse_vhdl_file(f, lib="work").requires)
    assert ("work", "pkg_bare") in reqs
    assert ("work", "pkg_all") in reqs


# --- (b) [1d3d152 + 079ab03] component instantiation with/without `component` -
# 1d3d152 made the component_inst regex require the literal `component`
# keyword (a regression: it broke the plain `u1 : bar port map(...)` form);
# 079ab03 fixed it by making the keyword optional again. Also pinned
# end-to-end by
# tests/test_parsers.py::test_parse_vhdl_explicit_component_keyword_and_bare_use.

def test_pin_1d3d152_079ab03_component_inst_with_and_without_keyword(tmp_path):
    f = tmp_path / "t.vhd"
    f.write_text(
        "entity t is end entity;\n"
        "architecture a of t is begin\n"
        "  u0 : component foo port map (x => x);\n"   # explicit keyword (1d3d152)
        "  u1 : bar port map (y => y);\n"              # bare form (079ab03 fix)
        "end architecture;\n"
    )
    reqs = _names(parse_vhdl_file(f, lib="work").requires)
    assert ("work", "foo") in reqs
    assert ("work", "bar") in reqs


# --- (c) [9681804] `use work.some_entity;` names an entity, not a package -----
# Upstream: `get_vhdl_package` raises KeyError for a name that isn't a
# registered package; 9681804 catches that and retries `get_entity`. On
# success it only info-logs "expected package but found entity instead" and
# `continue`s the loop -- the entity is deliberately NOT appended to
# file_deps, so upstream tolerates the construct (no crash) but the
# dependency has NO effect on the compile order.
#
# Ours: there is no separate package-name vs. entity-name index -- `use`
# clauses always add a plain Name to `requires`, and Resolver.resolve() looks
# it up in the one flat by_name index regardless of whether the provider
# matched as an entity_decl or a package_decl. So the entity's file IS
# resolved and IS included in the compile order. This is a deliberate
# difference (a superset of upstream's behaviour, not a bug): a `use` naming
# an entity actually wires up a real dependency edge here, where upstream
# silently drops it.

def test_pin_9681804_use_naming_an_entity_not_a_package_no_crash_and_is_ordered(tmp_path):
    entity_file = tmp_path / "leaf.vhd"
    entity_file.write_text("entity some_entity is\nend entity;\n")
    top_file = tmp_path / "top.vhd"
    top_file.write_text(
        "library work;\n"
        "use work.some_entity;\n"  # not a package -- `some_entity` is an entity
        "entity top is\nend entity;\n"
    )
    r = Resolver()
    leaf_sf = parse_vhdl_file(entity_file, lib="work")
    top_sf = parse_vhdl_file(top_file, lib="work")
    r.add(leaf_sf)
    r.add(top_sf)

    order = r.compile_order(top_sf)  # must not raise/crash

    stems = [sf.loc.stem for sf in order]
    assert "leaf" in stems  # deliberate superset behaviour, see comment above
    assert stems.index("leaf") < stems.index("top")


# --- (d) [490e1fb] two XCI files sharing the same coefficient file -> the -----
# coef appears exactly once in the compile order. Covered exactly by
# tests/test_resolver.py::test_compile_order_dedups_shared_direct_dep;
# re-asserted here cheaply for SHA traceability.

def test_pin_490e1fb_shared_coefficient_file_appears_once():
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
    assert [sf.loc for sf in order].count(resolve_abs_path(shared)) == 1


# --- (e) [fababfd / 1e70df8] XCI library inheritance --------------------------
# The instantiating VHDL file's library is adopted by the XCI (first
# non-default parent wins; a later, differently-libraried parent only warns).
# Covered exactly by
# tests/test_vendor_xilinx.py::test_xci_inherits_library_from_vhdl_parent and
# ::test_xci_library_inheritance_first_parent_wins; re-asserted cheaply here.

def test_pin_fababfd_1e70df8_xci_inherits_lib_from_first_parent_only(tmp_path, capsys):
    xci = SourceFile(Path("/x/ip.xci"), FileType.X_XCI, provides=[Name("work", "ip")])
    r = Resolver()
    r.add(xci)
    for lib in ("lib_a", "lib_b"):
        top = SourceFile(tmp_path / f"{lib}_top.vhd", FileType.VHDL, lib=lib)
        top.provides.append(Name(lib, f"{lib}_top"))
        top.requires.append(Name(lib, "ip"))
        r.add(top)
        r.compile_order(r.find_top(Name(lib, f"{lib}_top")))
    assert xci.lib == "lib_a"  # first parent walked wins...
    err = capsys.readouterr().err
    assert "already inherited library 'lib_a'" in err  # ...and the later parent only warns
    assert "ignoring 'lib_b'" in err


# --- (f) [3ad7717] XCI version selection: upgrade over downgrade --------------
# Prefers the highest version <= target (an upgrade candidate); if none is <=
# target, falls back to the lowest version above it. Covered exactly by
# tests/test_vendor_xilinx.py::test_select_x_priority_exact_then_version_then_device
# and ::test_closest_x_version_prefers_lower_upgradeable; re-asserted cheaply
# here.

def test_pin_3ad7717_version_selection_prefers_upgrade_over_downgrade():
    a = SourceFile(Path("/x/a.xci"), FileType.X_XCI, x_tool_version="2022.2", x_device="dev")
    b = SourceFile(Path("/x/b.xci"), FileType.X_XCI, x_tool_version="2024.2", x_device="dev")
    assert _closest_x_version([a, b], "2023.1") is a  # highest <= target: upgrade, not downgrade
    assert _closest_x_version([a, b], "2019.1") is a  # both above target -> lowest above
    assert _closest_x_version([a, b], "2024.2") is b  # exact match counts as "<= target"
