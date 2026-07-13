"""File discovery: turning glob patterns into concrete file paths."""

import glob
from pathlib import Path
from typing import List

from .util import resolve_abs_path


def process_glob_patterns(patterns: List[str], base_path: Path = Path(".")) -> List[Path]:
    """Apply glob ``patterns`` sequentially against ``base_path`` and return the
    sorted absolute file paths that survive.

    Each pattern modifies the running set: a plain pattern adds its matches, a
    ``!``-prefixed pattern removes any matches added by earlier patterns.
    """
    base_path = resolve_abs_path(base_path)
    current_files: set = set()

    for pattern in patterns:
        if pattern.startswith("!"):
            exclude_pattern = pattern[1:]
            excluded_files = glob.glob(str(base_path / exclude_pattern), recursive=True)
            excluded_paths = {resolve_abs_path(Path(f)) for f in excluded_files}
            current_files = current_files - excluded_paths
        else:
            # A pattern like 'src/**' matches directories as well as files;
            # only files are kept here (a directory reaching the parsers
            # raises a raw IsADirectoryError). Exclusion patterns are NOT
            # filtered this way -- harmless, since current_files never
            # contains directories to subtract from.
            matched_files = glob.glob(str(base_path / pattern), recursive=True)
            current_files.update(resolve_abs_path(Path(f)) for f in matched_files if Path(f).is_file())

    return sorted(current_files)
