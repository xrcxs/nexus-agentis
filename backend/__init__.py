"""NEXUS//AGENTIS backend package."""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent


class _DirectStatFinder(importlib.abc.MetaPathFinder):
    """Fallback finder for 9p virtual filesystems where readdir/listdir truncates directory entries."""

    def find_spec(self, fullname: str, path: object = None, target: object = None):  # type: ignore[override]
        if not fullname.startswith("backend."):
            return None
        rel = fullname.replace(".", os.sep)
        pkg_init = _PKG_ROOT / rel / "__init__.py"
        if pkg_init.is_file():
            return importlib.util.spec_from_file_location(
                fullname,
                str(pkg_init),
                submodule_search_locations=[str(pkg_init.parent)],
            )
        mod_file = _PKG_ROOT / f"{rel}.py"
        if mod_file.is_file():
            return importlib.util.spec_from_file_location(fullname, str(mod_file))
        return None


if not any(isinstance(f, _DirectStatFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _DirectStatFinder())
