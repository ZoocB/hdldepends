"""File discovery: turning glob patterns into concrete file paths."""

import glob
from pathlib import Path
from typing import List

from .util import resolve_abs_path


def process_glob_patterns(patterns: List[str], base_path: Path = Path(".")) -> List[Path]:
    """
    Process a list of glob patterns sequentially, including exclusion patterns (starting with '!'),
    to generate a filtered list of file paths. Each pattern modifies the current file list.

    Args:
        patterns (List[str]): list of glob patterns. Patterns starting with '!' are exclusions.
        base_path (str): Base directory to start glob searches from. Defaults to current directory.

    Returns:
        List[str]: list of absolute file paths that match the inclusion patterns but not the exclusion patterns.

    Example:
        patterns = [
            "*.py",          # Include all Python files
            "test/*.py",     # Include additional Python files in test directory
            "!**/temp*"      # Exclude any files with temp in the name from current list
        ]
        files = process_glob_patterns(patterns)
    """
    base_path = resolve_abs_path(base_path)  # Get absolute path of base directory
    current_files: set = set()

    # Process patterns sequentially
    for pattern in patterns:
        if pattern.startswith("!"):
            # Handle exclusion pattern - remove matching files from current set
            exclude_pattern = pattern[1:]  # Remove the '!' character

            # Get files that match the exclusion pattern
            excluded_files = glob.glob(str(base_path / exclude_pattern), recursive=True)
            excluded_paths = {resolve_abs_path(Path(f)) for f in excluded_files}

            # Remove excluded files from current set
            current_files = current_files - excluded_paths
        else:
            # Handle inclusion pattern - add new matching files. A pattern
            # like 'src/**' matches directories as well as files; only files
            # are kept here (a directory reaching the parsers raises a raw
            # IsADirectoryError) -- exclusion patterns are NOT filtered this
            # way, so a directory-matching `!` pattern still subtracts
            # whatever it matches (harmless: current_files never contains
            # directories to begin with, since only files are ever added).
            matched_files = glob.glob(str(base_path / pattern), recursive=True)
            current_files.update(resolve_abs_path(Path(f)) for f in matched_files if Path(f).is_file())

    # Return sorted list of absolute paths
    return sorted(current_files)
