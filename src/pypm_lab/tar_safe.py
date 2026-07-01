"""Safe tar archive inspection and extraction."""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from .errors import InstallError, RegistryValidationError
from .jsonio import loads_no_duplicate_keys

# Generous cap on total declared archive size; protects against decompression
# bombs (declared header sizes, not bytes actually extracted on disk) while
# leaving room for the inert text packages this tool is built for.
MAX_TOTAL_EXTRACT_BYTES = 256 * 1024 * 1024


def _member_validation_root() -> Path:
    """Return a dedicated root used only for archive member path checks."""

    return Path(tempfile.gettempdir()).resolve()


def validate_members(
    archive: tarfile.TarFile,
    destination: Path,
    *,
    max_total_bytes: int | None = None,
) -> None:
    """Reject members that escape ``destination`` or exceed the size cap."""

    limit = MAX_TOTAL_EXTRACT_BYTES if max_total_bytes is None else max_total_bytes
    destination_root = destination.resolve()
    total_size = 0
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        try:
            target.relative_to(destination_root)
        except ValueError as exc:
            raise InstallError(f"archive member escapes install root: {member.name}") from exc
        total_size += max(member.size, 0)
        if total_size > limit:
            raise InstallError(
                f"archive exceeds the extraction size limit of {limit} bytes"
            )


def safe_extractall(
    archive_path: Path | str,
    destination: Path,
    *,
    max_total_bytes: int | None = None,
) -> None:
    """Extract ``archive_path`` into ``destination`` with path and size guards."""

    try:
        with tarfile.open(archive_path, "r:*") as archive:
            destination.mkdir(parents=True, exist_ok=True)
            validate_members(archive, destination, max_total_bytes=max_total_bytes)
            archive.extractall(destination, filter="data")
    except InstallError:
        raise
    except tarfile.TarError as exc:
        raise InstallError(f"cannot unpack archive {archive_path}: {exc}") from exc


def read_archive_manifest(path: Path | str) -> dict[str, object]:
    """Read the shallowest ``package.json`` from an archive using safe tar handling."""

    archive_path = Path(path)
    validation_root = _member_validation_root()
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            validate_members(archive, validation_root, max_total_bytes=MAX_TOTAL_EXTRACT_BYTES)
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and PurePosixPath(member.name).name == "package.json"
            ]
            if not members:
                raise RegistryValidationError([f"{archive_path}: missing package.json"])
            member = min(
                members,
                key=lambda item: (len(PurePosixPath(item.name).parts), item.name),
            )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RegistryValidationError([f"{archive_path}: cannot read {member.name}"])
            try:
                data = loads_no_duplicate_keys(extracted.read().decode("utf-8"))
            except ValueError as exc:
                raise RegistryValidationError(
                    [f"{archive_path}: malformed archive package.json: {exc}"]
                ) from exc
    except RegistryValidationError:
        raise
    except InstallError as exc:
        raise RegistryValidationError([f"{archive_path}: {exc}"]) from exc
    except (OSError, tarfile.TarError) as exc:
        raise RegistryValidationError([f"{archive_path}: cannot read archive: {exc}"]) from exc
    if not isinstance(data, dict):
        raise RegistryValidationError([f"{archive_path}: archive package.json must be an object"])
    return data
