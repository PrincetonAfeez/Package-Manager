"""Project metadata and documentation link checks."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_URL = "https://github.com/PrincetonAfeez/Package-Manager"
PLACEHOLDER_HOST = "github.com/example/"

ROOT = Path(__file__).resolve().parents[1]

METADATA_FILES = (
    ROOT / "pyproject.toml",
    ROOT / "CHANGELOG.md",
    ROOT / "README.md",
    ROOT / "docs" / "adr" / "README.md",
)


def test_metadata_files_do_not_use_placeholder_repository_urls():
    offenders: list[str] = []
    for path in METADATA_FILES:
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_HOST in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_pyproject_declares_real_repository_url():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'Repository = "{REPOSITORY_URL}"' in text


def test_changelog_release_links_point_at_real_repository():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"{REPOSITORY_URL}/compare/v0.1.0...HEAD" in text
    assert f"{REPOSITORY_URL}/releases/tag/v0.1.0" in text
