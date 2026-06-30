"""SHA-256 integrity helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .errors import IntegrityError

_INTEGRITY_RE = re.compile(r"^sha256:([a-fA-F0-9]{64})$")


def sha256_file(path: Path | str) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def integrity_for_file(path: Path | str) -> str:
    return f"sha256:{sha256_file(path)}"


def parse_integrity(integrity: str) -> str:
    match = _INTEGRITY_RE.match(integrity)
    if not match:
        raise IntegrityError(
            f"invalid integrity {integrity!r}; expected sha256:<64 lowercase hex chars>"
        )
    return match.group(1).lower()


def verify_integrity(path: Path | str, integrity: str) -> None:
    expected = parse_integrity(integrity)
    actual = sha256_file(path)
    if actual != expected:
        raise IntegrityError(
            f"hash mismatch for {Path(path)}: expected sha256:{expected}, got sha256:{actual}"
        )


def hash_directory(path: Path | str) -> str:
    root = Path(path)
    if not root.exists():
        raise IntegrityError(f"cannot hash missing directory {root}")
    # Order by the POSIX relative path string so the digest is independent of the
    # host filesystem's ordering and case sensitivity (Windows vs POSIX). Sorting
    # Path objects would order case-insensitively on Windows, making tree hashes
    # diverge across platforms for archives with mixed-case file names.
    entries = sorted(
        ((item.relative_to(root).as_posix(), item) for item in root.rglob("*") if item.is_file()),
        key=lambda entry: entry[0],
    )
    hasher = hashlib.sha256()
    for relative, file_path in entries:
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        hasher.update(b"\0")
    return f"sha256:{hasher.hexdigest()}"
