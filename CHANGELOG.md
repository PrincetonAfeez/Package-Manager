# Changelog

All notable changes to PyPM Lab are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `pypm init --name` to set the project name when the directory name does not normalize to a valid package name.
- Stderr sync notes after `pypm add` and `pypm remove` when a lockfile exists but no longer matches the manifest or `.pypm/`.
- Bash quick-start commands in the README for Linux and macOS.
- `requirements.txt` and `requirements-dev.txt` for install paths that do not require reading `pyproject.toml`.
- `requirements-dev.in` plus pip-tools lockfile workflow: pinned `requirements-dev.txt` with CI drift check.
- Round 3 polish: CLI exception routing, publish rollback, tar safety edge cases, verify consistency checks, installer directory-replace recovery.
- Module-level exhaustive suites (`tests/test_module_*.py`) covering graph, lockfile, manifest, store, constraints, CLI, installer, verify, registry validation, resolver, jsonio/models, and final coverage gaps.
- CI coverage XML artifact upload on Python 3.11.4.
- Architecture Decision Records under `docs/adr/` (README index plus ADRs 0001–0004).

### Changed

- Test suite expanded to **282** tests with **~98%** line coverage on `pypm_lab` (CI gate **95%**).
- Dev dependency ranges stay in `pyproject.toml`; exact pins and transitive deps are locked in `requirements-dev.txt` (pip-tools).
- CI installs from the pinned lockfile and uploads `coverage.xml` from the primary matrix job.
- Coverage settings consolidated under `[tool.coverage.*]` in `pyproject.toml`.

### Documentation

- README testing section documents the full test layout, dev install paths, and lockfile regeneration.
- [ADR 0003 — Manifest-edit sync notes](docs/adr/0003-lockfile-install-verify-store-model.md#manifest-edit-sync-notes) records stderr warnings after `add`/`remove` when the lockfile or `.pypm/` is stale.
- `.gitignore` ignores `.claude/` IDE artifacts and local scope planning documents.

## [0.1.0] - project baseline

Educational CLI-first package manager: local registry, deterministic resolver, lockfile/install/verify workflow, inert archives, and `.pypm/` project store. Initial integration tests, property tests, and CI on Python 3.11.4 through 3.14.

[Unreleased]: https://github.com/PrincetonAfeez/Package-Manager/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PrincetonAfeez/Package-Manager/releases/tag/v0.1.0
