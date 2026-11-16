"""Mark naming and inventory used by the source-only operator."""

import os
import re
import stat

MARK_FOLDER = re.compile(r"mark-[0-9]{1,20}-[0-9]{2}\Z")
MAP_HASH = re.compile(r"[0-9a-f]{32}\Z")
FOCUSED, MINIMIZED, PLAY, LOADING = 1, 2, 4, 16  # OsuPerformanceHistory::Context


def capture_entries(root, limit):
    """The app publishes into a small flat directory of exclusively created Mark folders."""
    try:
        attributes = root.lstat()
        if not stat.S_ISDIR(attributes.st_mode) or is_reparse(attributes):
            raise ValueError("Diagnostic capture folder is a reparse point")
        with os.scandir(root) as entries:
            return [entry for _, entry in zip(range(limit + 1), entries)]
    except FileNotFoundError:
        return []


def is_reparse(attributes):
    return getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
