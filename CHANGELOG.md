# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-07-11

### Major refactor — 2026-06-15 to 2026-06-17

#### Changed
- `*_files` and `*_files_glob` unified: every entry in either key is now a glob pattern (a `!`-prefixed entry excludes, applied serially per lib/@tag); previously plain `*_files` entries were literal, exact paths with no glob or exclude support.
- Sub-configs (`sub`) now populate one flat, global index -- `ignore_libs` / `ignore_packages` / `ignore_entities` / `ignore_components` and all discovered files apply project-wide; upstream scoped each config's settings to its own `LookupSingular`/`LookupMulti` subtree.
- An unresolvable instantiation now logs a warning and continues, instead of raising `KeyError` and aborting the run.
- A bare config name now defaults to `.yaml` (was `.toml`); YAML is now actually loadable end-to-end -- upstream's YAML loader existed but path resolution only accepted an explicit `.toml`/`.json` suffix, rejecting `.yaml` outright.
- Non-VHDL source files (Verilog, other, `.bd`, `.xci`) now report library `work` in compile-order/file-list/JSON output; previously their library was `None`, printed as the literal text "None" in text output and omitted from JSON's `library` key.
- The `@tag` on a source file now replaces the file type in the compile-order/file-list type column (e.g. `@VHDL2008` prints as `VHDL2008`); previously the tag was appended to the base type (`VHDL@VHDL2008`).
- Coefficient/direct-dependency files reached via an XCI (e.g. `.coe`/`.mif`) are now folded into the main compile-order walk as `"type": "DIRECT"` entries; upstream emitted them via a separate coefficient-scan pass as `"type": "EXTERNAL"` entries with a `file_ext` field.
- The monolithic single 3,350-line `hdldepends.py` module is split into ~15 focused modules (`config`, `config_models`, `model`, `resolver`, `output`, `discovery`, `parsers/`, `vendors/xilinx/`, `cli`, ...); `hdldepends.hdldepends` remains as a re-exporting compat facade so the `hdldepends.hdldepends:hdldepends` console-script entry point still works.

#### Added
- Unified `-o`/`--output KIND[:SEL=VAL] FILE` flag (repeatable), replacing ten separate per-output-kind flags (see Removed).
- `--version`.
- Unknown config keys are now rejected with a "did you mean" suggestion; upstream also rejected unknown keys, but as an uncaught `KeyError` with no suggestion.
- `PyYAML` runtime dependency; `pydantic>=2` added for config validation (removed again in the hardening pass below, in favor of a dependency-free plain-Python gate with the same behavior).
- New `tests/` pytest-based automated test suite (upstream has only ad hoc shell scripts under `test/vhdl/`).

#### Removed
- Pickle caching entirely, including its two flags: `-c`/`--clear-pickle`, `--no-pickle`.
- Ten per-output-kind flags, consolidated into `-o`/`--output`: `--compile-order`, `--compile-order-path-only` (now `-o compile-order-paths`), `--compile-order-type`, `--compile-order-vhdl-lib`, `--compile-order-json`, `--file-list`, `--file-list-type`, `--file-list-vhdl-lib`, `--ext-file-list`, `--ext-file-list-tag`.
- `--top-file-type`, and with it the ability to use an unregistered file as top by naming its type; `--top-file` (kept) still requires the file already be part of the project, as it did upstream.

#### Fixed
- A circular `sub` config chain (A subs B, B subs A) is now detected and rejected with a clear error; upstream only caught a config directly listing itself, so an indirect cycle would recurse unchecked.

### Quality hardening — 2026-07-11

#### Fixed
- Verilog/VHDL parser correctness: portless module declarations, missing word boundaries (phantom declarations from instance names), string-literal phantom declarations, nested-parenthesis parameter lists, protected-code stripping (including orphan `end_protected` markers), an EOF/truncated-file crash, and include-directory first-match search order.
- A catastrophic-backtracking hang in the VHDL component/direct-instantiation regexes on pathological input.
- A `RecursionError` on deep dependency chains, by rewriting `compile_order`'s post-order walk as an iterative trampoline.
- Resolver index dedup (re-adding a file location is now replace-with-cleanup, so the by-location and by-name indexes can never disagree) and a direct-dependency walk that could double-emit an already-indexed file.
- Xilinx `.xci`/`.bd` tool-version selection now compares versions numerically instead of lexicographically (e.g. `2019.10` correctly sorts after `2019.2`).
- Various Xilinx `.xci`/`.bd` malformed-file crashes (missing required parameters, non-mapping JSON shapes, multi-dot `.bd` names, broken coefficient-file parameters) now raise/log clean, file-naming errors instead of bare tracebacks.
- Config/CLI crash-class errors -- bad TOML/JSON/YAML syntax, malformed `init_files` shapes, a failing `pre_cmds` command, directory-matching globs, and unwritable outputs -- now all exit cleanly (exit 2) instead of leaking a raw traceback.
- The sub-config top-key check no longer depends on the order config files are passed on argv.
- An `@tag` on a config key that doesn't accept one (e.g. `top_entity@rtl`) is now rejected instead of silently ignored.

#### Added
- Config-driven top selection restored: `top_entity` / `top_vhdl_file` / `top_verilog_file` / `top_x_bd_file`.
- `python -m hdldepends` package entry point.
- CI workflow (ruff + mypy + pytest on push/PR across Python 3.8/3.10/3.12/3.13).
- ruff lint configuration.
- A warning when a name resolves ambiguously to multiple candidate files.
- This changelog.

#### Changed
- `--version` output now reports both the package version and the config-schema version.
- Absolute paths are now fully resolved (a symlinked project root now emits physical, not symlinked, paths).
- The same file location added twice (e.g. listed under two libraries, or via both `init_files` and a source key) now resolves to the last one added, with the earlier index entry cleaned up instead of left stale.
- The pydantic dependency is removed; config validation is now dependency-free plain Python.
- Config-schema version (`HDL_DEPENDS_VERSION_NUM`, gates a config's `min_ver`) bumped 1.03 -> 1.04, matching upstream.

#### Removed
- Unused compat-facade names: `FileObjType`, `string_to_FileObjType`, `contains_any`, `get_file_modification_time`, `keys_rm_opt_ver`, `issue_key`.
- `set_log_level_from_verbose` (renamed to `set_log_level`).
