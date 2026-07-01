"""Build the sample package archives used by the README quick start

Run from the repository root:

    python examples/build_archives.py

This writes inert ``.tar.gz`` archives into ``examples/dist/`` that you can then
publish into a local registry with ``pypm publish``. The archives form a small
diamond: ``alpha`` and ``bravo`` both depend on ``shared``.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from pathlib import Path

# name -> version -> dependencies (a small diamond: alpha, bravo -> shared)
SAMPLE_PACKAGES: dict[str, dict[str, dict[str, str]]] = {
    "shared": {"1.5.0": {}},
    "alpha": {"1.2.4": {"shared": ">=1.0.0,<2.0.0"}},
    "bravo": {"2.1.0": {"shared": ">=1.0.0,<2.0.0"}},
}


def build_archives(out_dir: Path) -> list[Path]:
    """Write one inert archive per sample package version into ``out_dir``."""

    out_dir.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    for name, versions in SAMPLE_PACKAGES.items():
        for version, dependencies in versions.items():
            archive_path = out_dir / f"{name}-{version}.tar.gz"
            with tempfile.TemporaryDirectory() as staging:
                root = Path(staging) / f"{name}-{version}"
                (root / "src").mkdir(parents=True)
                manifest = {"name": name, "version": version, "dependencies": dependencies}
                (root / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                (root / "src" / f"{name}.txt").write_text(f"{name} {version}\n", encoding="utf-8")
                (root / "README.md").write_text(f"# {name} {version}\n", encoding="utf-8")
                with tarfile.open(archive_path, "w:gz") as archive:
                    archive.add(root, arcname=f"{name}-{version}")
            built.append(archive_path)
    return built


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "dist"
    for archive in build_archives(out_dir):
        print(archive)


if __name__ == "__main__":
    main()
