"""Generic, dependency-light helpers (path handling, config-key parsing, IO).

Note: ``str_to_name`` is intentionally *not* here -- it constructs a ``Name`` and
therefore lives with the core model to avoid an import cycle.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

from .constants import TOML_KEY_VER_SEP
from .errors import ConfigError
from .logging_util import log


def path_abs_from_dir(dir: Path, loc: Path):
    orig = str(loc)
    try:
        loc_str = orig.format(**os.environ)
    except (KeyError, IndexError) as e:
        # str.format raises immediately on the first unresolved {name} -- it
        # never leaves it in place for the check below to catch.
        name = e.args[0] if e.args else str(e)
        raise RuntimeError(f"path '{orig}' references environment variable(s) not set: {name}") from e
    if re.search(r"\{[^}]+\}", loc_str):
        log.error(
            "Note: curly brackets in a path are interpreted as {ENV_VAR_NAME} substitutions; "
            "any other use of '{' or '}' in a path is not supported"
        )
        raise RuntimeError(f"Path {loc_str} still contains env variables which we cannot find in shell's env")
    loc = Path(loc_str)
    # dir = Path(os.path.expandvars(str(dir)))
    if not loc.is_absolute():
        loc = dir / loc
        loc = loc.resolve()
    return loc


def resolve_abs_path(dir: Path):
    return dir.resolve()


def key_split_opt_ver(k: str) -> Tuple[str, Optional[str]]:
    split_k = k.split(TOML_KEY_VER_SEP)
    lsk = len(split_k)
    if not (lsk == 1 or lsk == 2):
        raise ConfigError(f"key {k}, can only have upto 1 {TOML_KEY_VER_SEP}")
    ver = None
    if lsk == 2:
        ver = split_k[1]
    return split_k[0], ver


def make_list(v) -> List:
    if isinstance(v, list):
        return v
    else:
        return [v]


def make_set(v) -> Set:
    if isinstance(v, set):
        return v
    elif isinstance(v, str):
        s = set()
        s.add(v)
        return s
    else:
        return set(v)


def add_unique(seq: List, item) -> None:
    """Append ``item`` to ``seq`` unless it is already present."""
    if item not in seq:
        seq.append(item)


def read_text_file_contents(loc: Path):
    """Read a text file, tolerating non-UTF-8 encodings.

    Tries UTF-8 first (the overwhelmingly common case). On failure, falls back
    to ISO-8859-1, which maps every byte value 0-255 to a character and so can
    never itself raise UnicodeDecodeError -- it is a *total* fallback, not a
    correct decoding of e.g. a real windows-1252/gb2312/utf-16 file (those
    bytes come through as the wrong characters), but it will never crash the
    parser on a file that isn't UTF-8.
    """
    try:
        with open(loc, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        log.debug(f"{loc} is not valid UTF-8; falling back to ISO-8859-1 (total fallback, may mis-decode)")
        with open(loc, encoding="iso-8859-1") as f:
            return f.read()
