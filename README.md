# PyPM Lab

PyPM Lab is a custom educational package manager. It is CLI-first, uses a local registry, installs inert package archives only into a project-local `.pypm/` directory, and models dependency resolution as a graph and constraint problem.

It is not compatible with pip, PyPI, wheels, Poetry lockfiles, npm packages, virtual environments, global Python packages, user site-packages, or system executable locations.

## Quick Start

```powershell
python -m pip install -e .
pypm init
# Publish every package the project will resolve. Publish order is unconstrained
# (a package may be published before its dependencies), but all dependencies must
# exist in the registry before `resolve`/`install` runs.
pypm publish path\to\shared-1.5.0.tar.gz
pypm publish path\to\alpha-1.2.4.tar.gz
pypm add alpha ^1.2.0
pypm resolve --trace
pypm install
pypm tree
pypm why shared
pypm graph --format dot
pypm verify
pypm install --locked
```

Here `alpha-1.2.4` declares a dependency on `shared`, so both archives are
published before resolving. `pypm install` is reproducible by default: it reuses
an existing `pypm-lock.json` when that lockfile still satisfies the manifest, and
only re-resolves when the lockfile is missing or stale. Use `pypm update` to force
re-resolution to the newest compatible graph.

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

Versions use `major.minor.patch` semantic-version-style triples. Supported constraints are exact versions, comparators (`>=`, `>`, `<=`, `<`), comma ranges, caret (`^1.2.3`), and tilde (`~1.2.3`).

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
```

The CLI also accepts split forms such as `pypm add alpha ^1.2.0`.

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

The resolved result is a dependency DAG. PyPM Lab exposes graph behavior through `tree`, `why`, `graph`, topological install order, cycle detection, and resolver trace mode.

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

Registry validation catches malformed JSON, invalid names, invalid versions, bad constraints, missing archives, path traversal, unsupported integrity algorithms, missing dependencies, hash mismatches, and archive metadata disagreement before resolution begins.

## Installation And Integrity

Install order is topological: dependencies install before packages that require them. Each archive is copied into `.pypm/cache/sha256/`, re-hashed, safely unpacked into a temporary directory, moved into `.pypm/store/<name>/<version>/`, and only then recorded in `.pypm/installed.json`.

`install --locked` reads `pypm-lock.json`, skips resolution, installs exact pinned versions, and verifies pinned hashes.

`verify` checks lockfile entries, registry archives, installed records, installed package directories, and content hashes. It exits nonzero if integrity checks fail.

## CLI

```text
pypm init
pypm add <pkg> <constraint>
pypm add <requirement>
pypm remove <pkg>
pypm resolve [--trace]
pypm install [--locked]
pypm update
pypm list
pypm tree
pypm why <pkg>
pypm graph [--format adjacency|json|dot]
pypm verify
pypm publish <archive>
```

## Testing Strategy

Install the development tools and run the checks with:

```powershell
python -m pip install -e .[dev]
python -m pytest
python -m mypy
```

The tests focus on the pure resolver, parser, semver/constraint layer, graph algorithms, deterministic lockfile serialization, registry validation, integrity failure, locked installs, and verify tamper detection. Resolver tests use an in-memory registry so graph and constraint behavior can be tested without filesystem installation. Installer, store, publish, and validation tests run entirely inside `pytest` temporary directories, so they never touch real system packages. Type checking is configured in `pyproject.toml` under `[tool.mypy]`.

## Limitations And Non-Goals

PyPM Lab does not execute package contents, build wheels, manage environments, publish to a public index, authenticate users, manage ownership, moderate packages, or claim production security. The optional Django + HTMX registry browser is intentionally stretch-only and would call the same service layer rather than owning resolver logic.

The graph layer targets small fixture-sized package universes. Cycle detection and topological sort use iterative depth-first search so they are not bounded by Python's recursion limit, but the `tree` and `why` renderers walk the resolved DAG recursively and enumerate every path, so they assume the modest graph sizes this project is built to demonstrate.
