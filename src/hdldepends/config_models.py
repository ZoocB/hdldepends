"""Plain-Python validation gate for hdldepends configuration files.

Validates a loaded config mapping (parsed from TOML / JSON / YAML) and raises
clear errors for the common mistakes: unknown keys (with a "did you mean"
hint), malformed ``@tag`` suffixes, and a non-numeric ``min_ver``.

This is intentionally **permissive about values**: the source-file keys
accept a wide range of shapes (str / list / per-library dict) that the existing
loader already understands, so validation never rejects a config that the tool
previously accepted. It is used as a *gate* -- downstream code keeps consuming
the raw dict, so behaviour is unchanged for every valid config.
"""

import difflib

from .constants import TOML_KEY_VER_SEP
from .errors import ConfigError  # noqa: F401  (re-exported: tests import it from here)

#: Keys that may carry an optional ``@tag`` suffix (source files, top files,
#: init/skip lists). Consumed by :func:`hdldepends.config.build_resolver`'s
#: ``gather``/``_files_for`` machinery, which resolves each to a (lib, loc, ver)
#: triple.
SOURCE_KEYS = {
    "init_files",
    "vhdl_files",
    "vhdl_files_file",
    "vhdl_files_glob",
    "vhdl_package_skip_order",
    "verilog_files",
    "verilog_files_file",
    "verilog_files_glob",
    "verilog_include_dir",
    "verilog_include_files",
    "verilog_include_files_file",
    "verilog_include_files_glob",
    "other_files",
    "other_files_file",
    "other_files_glob",
    "x_bd_files",
    "x_bd_files_file",
    "x_bd_files_glob",
    "x_xci_files",
    "x_xci_files_file",
    "x_xci_files_glob",
    "ext_files",
    "ext_files_file",
    "ext_files_glob",
    "top_vhdl_file",
    "top_verilog_file",
    "top_x_bd_file",
}

#: Keys that do not take an ``@tag`` suffix. Also consumed directly by
#: ``gather`` in :mod:`hdldepends.config` (e.g. ``ignore_libs``, ``top_entity``).
OTHER_KEYS = {
    "min_ver",
    "pre_cmds",
    "ignore_libs",
    "ignore_packages",
    "ignore_entities",
    "ignore_components",
    "sub",
    "top_entity",
    "x_tool_version",
    "x_device",
}

ALL_BASE_KEYS = SOURCE_KEYS | OTHER_KEYS


def _check_keys(raw: dict) -> None:
    for key in raw:
        if not isinstance(key, str):
            raise ConfigError(f"config keys must be strings, got {key!r}")

        parts = key.split(TOML_KEY_VER_SEP)
        if len(parts) > 2:
            raise ConfigError(
                f"config key '{key}' has more than one '{TOML_KEY_VER_SEP}' tag separator"
            )
        base = parts[0]
        tag = parts[1] if len(parts) == 2 else None

        if base not in ALL_BASE_KEYS:
            suggestion = difflib.get_close_matches(base, sorted(ALL_BASE_KEYS), n=1)
            hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
            raise ConfigError(f"unknown config key '{key}'{hint}")

        if tag is not None and len(tag) == 0:
            raise ConfigError(f"config key '{key}' has an empty '{TOML_KEY_VER_SEP}' tag")

        if tag is not None and base in OTHER_KEYS:
            # An @tag on a key that isn't in SOURCE_KEYS (e.g. `top_entity@rtl`)
            # previously passed validation and was then silently ignored --
            # `key_split_opt_ver`/`_for_each_file_spec` only ever look for the
            # bare key, so the tagged variant never matched and the setting it
            # was meant to make (e.g. top_entity) was never applied, with no
            # diagnostic at all.
            raise ConfigError(f"key '{key}': '{base}' does not take an '@' tag")

    mv = raw.get("min_ver")
    if mv is not None and (isinstance(mv, bool) or not isinstance(mv, (int, float))):
        raise ConfigError(f"min_ver must be a number, got {mv!r}")


def validate_config(raw: dict, source) -> None:
    """Validate a loaded config mapping, raising :class:`ConfigError` (with the
    source file in the message) on failure."""
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid hdldepends config {source}: top level must be a mapping/table, got {type(raw).__name__}")
    try:
        _check_keys(raw)
    except ConfigError as e:
        raise ConfigError(f"Invalid hdldepends config {source}: {e}") from None
