# Adversarial test findings (Stage 5.5)

~40 adversarial tests were added to deliberately break the system's assumptions
across the parsers, dependency graph, config loader, CLI, and Xilinx vendor
layer. Files: `test_adversarial_parsers.py`, `test_adversarial_graph.py`,
`test_adversarial_config.py`, `test_adversarial_cli.py`,
`test_adversarial_vendor.py`.

## Bugs found — all fixed

Each bug has a regression test (now passing) that pins the fix.

1. **`-o <bad-kind>` produced a traceback instead of a clean error.** The output
   KIND was validated only after argument parsing, so a typo raised
   `argparse.ArgumentTypeError` as an uncaught exception (exit 1 + traceback).
   **Fixed** in `cli.py`: `-o` specs are validated up front and routed through
   `parser.error` (clean usage message, exit 2).

2. **VHDL entity at file offset 0 was not detected.**
   The entity/component regexes used `\Wentity` (required a non-word char
   *before* `entity`), missing an entity that is the first token of a file.
   **Fixed** in `parsers/vhdl.py`: use `\b` (zero-width boundary) like
   `package_decl` already did.

3. **VHDL `end;` (no whitespace before `;`) was not detected.**
   The entity/component regexes required `end\s+...`. **Fixed**: `end(?:\s+(?:entity|<name>)|\s*;)`
   so `end;` and `end ;` both match. This un-breaks `test/vhdl/led_controller_tb.vhd`
   and the maintainer's `test_led_controller_tb.sh` (now covered by the
   `led_controller` golden).

4. **Transitive circular sub-configs were not detected.**
   `create_lookup_from_toml` guarded only *immediate* self-reference, so a cycle
   `a.toml -> b.toml -> a.toml` recursed until `RecursionError`. **Fixed**: an
   ancestor-path `frozenset` is threaded through the recursion and a clear
   "circular sub config detected" error is raised on revisit. A diamond
   (one config included by two parents) is still allowed (regression-tested).

## Known latent bugs preserved (documented, behaviour intentionally unchanged)

- **`_get_loc_from_common` always returns `None`.** In the original `LookupMulti`
  the `return None` sat outside the loop, so a file already present in a
  sub-lookup was never reused — files are always (re)parsed. Preserved verbatim
  during the LookupMulti→LookupSingular merge to avoid changing behaviour. Worth
  fixing (return the found object) in a future, separately-tested change.

## Assumptions that held up (passing probes)

- **VHDL parser:** case-insensitive; ignores `entity` text inside line/block
  comments and string literals; multiple entities per file; `use lib.pkg.all`
  package deps; direct `entity work.x` instantiation; tabs / irregular
  whitespace.
- **Verilog parser:** module detection; ignores modules in comments and strings;
  parameterized instantiation `sub #(.W(8)) u (...)`; `import pkg::*`; does not
  treat keywords (`if`, `always`) as instantiations.
- **Dependency graph / ordering:** circular and self dependencies terminate;
  diamonds emit the shared leaf once and before its dependents; missing entity
  raises `KeyError`; case-insensitive dependency resolution; deep (40-level)
  chains order correctly.
- **Config loader:** empty config is fine; `min_ver` too high raises; globs
  matching nothing are fine; immediate self-referencing `sub` raises; schema is
  lenient on value shapes but rejects a non-numeric `min_ver`.
- **CLI:** output-spec parsing validates kind/selector; compile-order without a
  top fails cleanly; unknown top entity fails; duplicate `-o` to one file is
  last-wins; multiple config files are all loaded (the previously-broken
  multi-config path, fixed in Phase 5).
- **Xilinx vendor parsers:** empty/garbage `.xci`, malformed `.bd` JSON, and
  files missing required keys all raise loudly rather than returning a bogus
  object.
