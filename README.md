# PyPM Lab

PyPM Lab is a custom educational package manager. It is CLI-first, uses a local registry, installs inert package archives only into a project-local `.pypm/` directory, and models dependency resolution as a graph and constraint problem.

It is not compatible with pip, PyPI, wheels, Poetry lockfiles, npm packages, virtual environments, global Python packages, user site-packages, or system executable locations.

## Quick Start

PyPM Lab requires Python 3.11.4 or newer (it extracts archives with the tarfile `data` safety filter, available from 3.11.4).

```powershell
python -m pip install -r requirements-dev.txt
python examples\build_archives.py        # writes sample archives into examples\dist\
pypm init
# Publish every package the project will resolve. Publish order is unconstrained
# (a package may be published before its dependencies), but all dependencies must
# exist in the registry before `resolve`/`install` runs.
pypm publish examples\dist\shared-1.5.0.tar.gz
pypm publish examples\dist\alpha-1.2.4.tar.gz
pypm add alpha ^1.2.0
pypm resolve --trace
pypm install
pypm tree
pypm why shared
pypm graph --format dot
pypm verify
pypm install --locked
```

On Linux or macOS, use forward slashes in paths (`examples/dist/`, `examples/dist/shared-1.5.0.tar.gz`, etc.).

```bash
python -m pip install -r requirements-dev.txt
python examples/build_archives.py
pypm init
pypm publish examples/dist/shared-1.5.0.tar.gz
pypm publish examples/dist/alpha-1.2.4.tar.gz
pypm add alpha ^1.2.0
pypm resolve --trace
pypm install
pypm verify
```

`python examples\build_archives.py` builds sample inert archives for a small
dependency diamond (`alpha` and `bravo` both depend on `shared`). The quick start
above uses only `shared` and `alpha`; `bravo-2.1.0.tar.gz` is also built if you
want to experiment with a second root dependency. After `pypm resolve`, run
`pypm install` — `resolve` updates the lockfile only and prints a note when
`.pypm/` is out of sync. `pypm install` is reproducible by default: it reuses an
existing `pypm-lock.json` when that lockfile still satisfies the manifest, and
only re-resolves when the lockfile is missing or stale. Use `pypm update` to
force re-resolution to the newest compatible graph.

An archive is just a `.tar.gz` whose top-level directory is `<name>-<version>/`
containing a `package.json` with matching `name`/`version`/`dependencies`; see
[`examples/build_archives.py`](examples/build_archives.py) for the exact layout.

## Project Files

`package.json` is the project manifest: it says what the project wants using version ranges.

`pypm-lock.json` is the lockfile: it says what the resolver selected using exact versions, integrity hashes, and dependency edges. Lockfile serialization is stable, so equivalent inputs produce deterministic output.

`registry/index.json` is the local registry index. Each package version points to an inert archive and a `sha256:` integrity value.

`.pypm/` is the project-local store:

```text
.pypm/
  store/
    alpha/1.2.4/
  cache/
    sha256/
  tmp/
  installed.json
```

## Version And Requirement Model

Versions use `major.minor.patch` semantic-version-style triples. Supported constraints are exact versions, comparators (`>=`, `>`, `<=`, `<`), comma ranges, caret (`^1.2.3`), tilde (`~1.2.3`), and wildcard (`*`).

Wildcard behavior:

- `*` means any non-negative semantic version (`>=0.0.0`).

Caret behavior:

- `^1.2.3` means `>=1.2.3,<2.0.0`
- `^0.2.3` means `>=0.2.3,<0.3.0`
- `^0.0.3` means `>=0.0.3,<0.0.4`

Tilde behavior:

- `~1.2.3` means `>=1.2.3,<1.3.0`

Requirement strings parse into structured objects:

```text
alpha@^1.2.0
bravo@>=2.0.0,<3.0.0
charlie@1.4.2
delta@~1.2.0
echo@*
```

The CLI also accepts split forms such as `pypm add alpha ^1.2.0` or `pypm add alpha "*"`.

## Resolver Design

The resolver is pure and separated from filesystem I/O. It queries a registry interface for package facts, accumulates all constraints that reach each package, and performs deterministic backtracking:

1. Choose an unresolved package deterministically, preferring the most constrained one — the package with the fewest compatible candidate versions, with ties broken by name. This most-constrained-variable heuristic fails fast and keeps selection deterministic.
2. Sort compatible candidate versions highest-first.
3. Try a candidate.
4. Add its dependency constraints.
5. Recurse.
6. Backtrack on conflict, recording why each candidate was rejected.

Cycles are detected during the search: an edge that would close a cycle is rejected like any other dead end, and if a package cannot be resolved for that reason the conflict explanation ends with an explicit `Dependency cycle detected: a -> b -> a` line.

This is a constraint-satisfaction problem over a dependency graph. Real package managers often use more sophisticated solvers such as PubGrub; PyPM Lab intentionally implements a small deterministic backtracking resolver so the graph and search behavior stay readable.

The resolved result is a dependency DAG. PyPM Lab exposes graph behavior through `tree`, `why`, `graph`, topological install order, cycle detection, and resolver trace mode. See [ADR 0001](docs/adr/0001-deterministic-backtracking-resolver.md) for the resolver trade-offs (including why PubGrub was not implemented).

## Registry And Archive Contract

Example `registry/index.json`:

```json
{
  "packages": {
    "alpha": {
      "versions": {
        "1.2.4": {
          "archive": "archives/alpha-1.2.4.tar.gz",
          "integrity": "sha256:...",
          "dependencies": {
            "shared": ">=1.0.0,<2.0.0"
          }
        }
      }
    }
  }
}
```

Each archive is inert data and must contain package metadata that agrees with the registry:

```text
alpha-1.2.4/
  package.json
  src/
    alpha.txt
  README.md
```

Archive `package.json` example:

```json
{
  "name": "alpha",
  "version": "1.2.4",
  "dependencies": {
    "shared": ">=1.0.0,<2.0.0"
  }
}
```

Registry validation catches malformed JSON, invalid names, invalid versions, bad constraints, missing archives, path traversal, unsupported integrity algorithms, missing dependencies, hash mismatches, and archive metadata disagreement before resolution begins. See [ADR 0002](docs/adr/0002-local-registry-and-inert-archives.md).

## Installation And Integrity

Install order is topological: dependencies install before packages that require them. Each archive is copied into `.pypm/cache/sha256/`, re-hashed, safely unpacked into a temporary directory, moved into `.pypm/store/<name>/<version>/`, and only then recorded in `.pypm/installed.json`.

`install --locked` reads `pypm-lock.json`, skips resolution, installs exact pinned versions, and verifies pinned hashes.

`verify` checks manifest-lockfile alignment, lockfile reachability from roots, lockfile entries, registry dependency metadata, registry archives, installed records, installed package directories, content hashes, and the lockfile's internal constraint consistency. It exits nonzero if integrity checks fail.

`install` reconciles the store to the resolved set: a package dropped by `remove` (or a re-resolve) is pruned from `.pypm/store/` and `installed.json`, so `verify` stays clean. `clean` additionally prunes cache archives no longer referenced by an installed package.

`resolve` writes the lockfile without installing. `install` and `update` persist the lockfile only after a successful install, so a failed install never leaves a new lockfile ahead of the store. See [ADR 0003](docs/adr/0003-lockfile-install-verify-store-model.md) for the full lockfile, store, and verify model.

## CLI

### Global options

```text
pypm [--project-dir <path>] [--registry <path>] <command> [...]
```

- `--project-dir <path>` — project directory containing `package.json`, `pypm-lock.json`, and `.pypm/` state. Default: current directory.
- `--registry <path>` — local registry directory. Relative paths are resolved under `--project-dir`; absolute paths are used as-is. Default: `registry`.

```text
pypm --version
pypm init [--name <project-name>]
pypm publish <archive>
pypm add <pkg> <constraint>
pypm add <requirement>
pypm remove <pkg>
pypm resolve [--trace]
pypm install [--locked]
pypm update
pypm list
pypm tree
pypm why <pkg> [--all]
pypm graph [--format adjacency|json|dot]
pypm outdated [--strict]
pypm verify
pypm clean [--dry-run]
```

`publish` adds an inert package archive to the local registry after validating its `package.json` metadata and recording its archive path, dependencies, and `sha256:` integrity in `registry/index.json`. It is local-only: no PyPI, pip, cloud index, accounts, or multi-user publishing.

`why` shows the shortest path by default; `why --all` shows every path. `outdated` lists installed packages with newer registry releases (noting the newest version still allowed by the manifest constraint) and reports lockfile packages that are missing from the registry; use `--strict` to exit `1` when any package is missing from the registry (not when newer compatible versions exist). `add` and `remove` print a stderr note when a lockfile already exists but no longer matches the manifest or installed store. `clean --dry-run` reports what would be pruned without deleting anything.

### Exit codes

- `0` — success (including `verify` passing, `why` finding the package, and informational commands such as `outdated` without `--strict`).
- `1` — a runtime error: unsatisfiable constraints, a dependency cycle, a hash mismatch, a missing package, a malformed manifest/lockfile/registry index, a failed atomic install, a failing `verify`, `outdated --strict` with missing registry packages, or `why` on a package that is not in the resolved graph.
- `2` — a usage error: no subcommand, an unknown command, or invalid arguments (reported by the argument parser).

## Testing Strategy

Install the development tools and run the checks with:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check src tests examples benchmarks
python -m mypy
python -m pytest --cov=pypm_lab --cov-report=term-missing --cov-fail-under=95
```

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check src tests examples benchmarks
python -m mypy
python -m pytest --cov=pypm_lab --cov-report=term-missing --cov-fail-under=95
```

PyPM Lab ships **282** tests across workflow, CLI, property-based, and module-level suites. CI enforces **95%** line coverage on `pypm_lab` (local runs currently reach **~98%**). Dev dependency **ranges** live in `pyproject.toml`; the pinned lockfile is `requirements-dev.txt`, generated from `requirements-dev.in` with [pip-tools](https://github.com/jazzband/pip-tools). After changing dev ranges, regenerate and commit:

```powershell
python -m pip install "pip-tools>=7.5,<8"
python -m piptools compile requirements-dev.in -o requirements-dev.txt --strip-extras
```

```bash
python -m pip install "pip-tools>=7.5,<8"
python -m piptools compile requirements-dev.in -o requirements-dev.txt --strip-extras
```

CI runs a lockfile drift check on Python 3.11.4. Coverage thresholds live in `[tool.coverage.report]`; lint and type settings in `[tool.ruff.*]` and `[tool.mypy]`.

The tests cover resolver backtracking, semver/constraints, graph algorithms, deterministic lockfiles, registry validation, install rollback, store/clean, tar safety, verify tamper detection, and CLI exit codes. Resolver tests use an in-memory registry; filesystem tests run in `pytest` temporary directories. Property-based tests (Hypothesis) check semver/constraint invariants and resolution invariance to manifest dependency order.

| Files | Focus |
|-------|--------|
| `tests/test_resolver.py`, `test_graph_lockfile.py`, `test_versions_requirements.py` | Resolver, graph, parsers |
| `tests/test_registry_validation.py`, `test_registry_install_verify.py` | Registry and install/verify integration |
| `tests/test_workflow.py`, `test_cli.py`, `test_robustness.py` | End-to-end CLI workflows |
| `tests/test_properties.py` | Hypothesis property tests |
| `tests/test_install_round2.py`, `test_round3.py` | Install hardening regressions |
| `tests/test_module_*.py` | Per-module exhaustive coverage |

CI runs on Ubuntu across Python **3.11.4**–**3.14** (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). See [CHANGELOG.md](CHANGELOG.md) for release notes and [`docs/adr/README.md`](docs/adr/README.md) for architecture decisions.

`benchmarks/bench_resolver.py` resolves generated package universes of increasing size to make the resolver's scaling visible:

```powershell
python benchmarks/bench_resolver.py
```

```bash
python benchmarks/bench_resolver.py
```

## Limitations And Non-Goals

PyPM Lab does not execute package contents, build wheels, manage environments, publish to a public index, authenticate users, manage ownership, moderate packages, or claim production security. The optional Django + HTMX registry browser is intentionally stretch-only and would call the same service layer rather than owning resolver logic.

The graph layer targets small fixture-sized package universes. Cycle detection and topological sort use iterative depth-first search so they are not bounded by Python's recursion limit, but the `tree` and `why` renderers walk the resolved DAG recursively and enumerate every path, so they assume the modest graph sizes this project is built to demonstrate.

Other deliberate boundaries:

- **Not concurrency-safe.** The CLI takes no locks on `.pypm/` or the registry index, so it assumes a single user runs one command at a time ([ADR 0004](docs/adr/0004-single-user-no-locks.md)).
- **Tree hashing scope.** `verify` hashes file paths and contents but not empty directories or file permissions, which is sufficient for inert text packages.
- **Extraction cap.** Archives are rejected if their declared member sizes exceed a fixed total limit (header-declared sizes, not bytes actually extracted), a basic guard against decompression bombs rather than a full sandboxing layer.
