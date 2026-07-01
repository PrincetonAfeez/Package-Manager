"""Atomic filesystem writes for authoritative project files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically via a temporary file and ``os.replace``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path | str, data: Any) -> None:
    """Atomically write a JSON object with stable key ordering."""

    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
