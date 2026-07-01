# Architecture Decision Record
## App — Package Manager
**Package Management Systems Group | Document 1 of 5**
**Status: Accepted**

---

## Context

The Package Management Systems group requires a portfolio-ready package manager that demonstrates dependency resolution, lockfiles, local registries, archive validation, integrity checks, project-local installation, graph operations, and a clear command-line workflow.

The project is named **PyPM Lab**. It is intentionally a custom educational package manager, not a replacement for `pip`, PyPI, wheels, Poetry, npm, virtual environments, system package managers, or global Python installation tools. The product is the `pypm` CLI. It uses a local registry, resolves package metadata as a graph/constraint problem, writes deterministic lockfiles, and installs inert tar archives only into a project-local `.pypm/` directory.

The selected architecture separates pure dependency logic from filesystem effects. Version/constraint parsing, requirement parsing, graph algorithms, and resolution are pure. The local registry validates package facts and archive metadata. The installer turns a resolved graph into a project-local store with cache, temporary extraction, rollback, pruning, and installed records. Verification checks the manifest, lockfile, registry, archive hashes, installed records, and installed content hashes.

---

## Decisions

### Decision 1 — Build a local educational package manager

**Chosen:** Build `pypm`, a CLI-first local package manager for inert archives.

**Rejected:** Compatibility with `pip`, PyPI, wheels, virtual environments, user site-packages, or system executables.

**Reason:** The goal is to demonstrate package-manager internals without inheriting the complexity of Python packaging standards. A scoped local model makes resolver, lockfile, registry, and install behavior inspectable.

---

### Decision 2 — Keep package installation project-local

**Chosen:** Install only under `.pypm/` in the project directory.

**Rejected:** Installing into global Python, user site-packages, virtual environments, or PATH locations.

**Reason:** Project-local install avoids privilege, environment, import-path, and executable-shim concerns. It keeps the installation side effects bounded and reversible.

---

### Decision 3 — Treat packages as inert archives

**Chosen:** Package archives are `.tar.gz` files containing metadata and data files.

**Rejected:** Executing package build steps, setup scripts, wheel hooks, or arbitrary code.

**Reason:** Executing package code would turn this into a security-sensitive installer. Inert archives allow integrity and extraction safety to be the primary install concerns.

---

### Decision 4 — Require Python 3.11.4+

**Chosen:** Require Python 3.11.4 or newer because safe extraction uses the `tarfile` data filter.

**Rejected:** Supporting older Python versions with hand-rolled extraction semantics.

**Reason:** The project benefits from Python’s safer built-in tar extraction support while still validating archive paths and declared sizes.

---

### Decision 5 — Use strict `major.minor.patch` versions

**Chosen:** Implement a strict semantic-version-style triple: `major.minor.patch`.

**Rejected:** Full PEP 440, pre-releases, local versions, epochs, build metadata, or arbitrary tags.

**Reason:** A strict triple is enough to teach version ordering, ranges, caret, tilde, and deterministic resolution without recreating all packaging edge cases.

---

### Decision 6 — Support a focused constraint grammar

**Chosen:** Support exact versions, comparators, comma ranges, caret, tilde, and wildcard constraints.

**Rejected:** Every ecosystem-specific constraint form.

**Reason:** These constraints cover the core solver problem and make conflict explanations understandable.

---

### Decision 7 — Keep resolver pure

**Chosen:** Resolver depends only on a `RegistryReader` protocol and returns a resolved graph plus optional trace.

**Rejected:** Resolver reading files, writing lockfiles, or installing packages directly.

**Reason:** Pure resolution is easier to test, fuzz, benchmark, and reason about. Filesystem mutation belongs to registry/installer/CLI layers.

---

### Decision 8 — Use deterministic backtracking

**Chosen:** Resolve by accumulating constraints, choosing the most-constrained unresolved package, trying candidates highest-first, detecting cycles, and backtracking on conflicts.

**Rejected:** PubGrub, SAT solver, or greedy latest-only resolution.

**Reason:** Deterministic backtracking is readable and appropriate for fixture-sized package universes. It exposes graph-search behavior without hiding it behind a solver library.

---

### Decision 9 — Prefer highest compatible candidate versions

**Chosen:** Candidate versions are sorted highest-first.

**Rejected:** Lowest-compatible or registry-order selection.

**Reason:** This matches common package-manager expectations while remaining deterministic.

---

### Decision 10 — Model dependency cycles as resolver conflicts

**Chosen:** An edge that closes a cycle is rejected and reported as a dependency-cycle conflict.

**Rejected:** Allowing cycles and relying on install ordering to fail later.

**Reason:** The resolved result is intended to be a DAG. Cycle detection belongs in resolution, before lockfile/install.

---

### Decision 11 — Make the lockfile deterministic and complete

**Chosen:** `pypm-lock.json` stores exact versions, integrity values, dependency edges, and roots with stable key ordering.

**Rejected:** Lockfile containing only root pins.

**Reason:** A complete deterministic lockfile allows install, tree, why, graph, and verify to run consistently without re-solving.

---

### Decision 12 — Make plain install reproducible by default

**Chosen:** `pypm install` uses the existing lockfile when it still satisfies the manifest. `pypm update` forces re-resolution.

**Rejected:** Re-resolving every install.

**Reason:** Users expect install to reproduce the locked graph. Update is the explicit operation that moves versions forward.

---

### Decision 13 — Write lockfile after successful install for install/update

**Chosen:** `install` and `update` persist the lockfile only after the install succeeds.

**Rejected:** Writing a new lockfile before installation.

**Reason:** A failed install should not leave the lockfile ahead of the store. `resolve` is the explicit command that writes a lockfile without installing.

---

### Decision 14 — Validate registry metadata before resolution

**Chosen:** Local registry loading validates package names, versions, constraints, archive paths, integrity format, missing dependencies, archive existence, hash agreement, and archive metadata agreement.

**Rejected:** Letting resolution/install discover malformed registry facts later.

**Reason:** Registry validation catches bad inputs at the source and gives clearer error messages.

---

### Decision 15 — Publish incrementally but validate the new entry

**Chosen:** `publish` validates the archive, copies it into registry archives, computes integrity, adds an index entry, validates the new entry, and writes the index atomically.

**Rejected:** Revalidating the entire registry on every publish.

**Reason:** Publish should be O(1) in registry size while still preventing broken new entries.

---

### Decision 16 — Use SHA-256 integrity strings

**Chosen:** Integrity format is `sha256:<64 hex characters>`.

**Rejected:** Multiple algorithms or unsigned hashes.

**Reason:** One strong algorithm keeps the model simple. Integrity is for tamper detection, not authentication.

---

### Decision 17 — Safely extract archives into temporary directories

**Chosen:** Validate tar members, reject escaping paths, enforce a declared-size cap, extract with `filter="data"`, then atomically place the package directory.

**Rejected:** Extracting archives directly into final store paths.

**Reason:** Direct extraction can leave partial installs. Temporary extraction plus replacement and rollback gives safer behavior.

---

### Decision 18 — Install in topological order

**Chosen:** Dependencies install before dependents.

**Rejected:** Registry order, lockfile order, or arbitrary order.

**Reason:** A dependency graph should produce a dependency-first install order. It also makes CLI output and tests predictable.

---

### Decision 19 — Roll back failed installs

**Chosen:** On install failure, restore previous installed records and package directories where possible, and remove new cache files not referenced by the previous state.

**Rejected:** Leaving partially installed packages in `.pypm/`.

**Reason:** Store integrity matters. A package manager should not leave the project in an ambiguous half-installed state.

---

### Decision 20 — Keep concurrency out of scope

**Chosen:** Assume one user runs one `pypm` command at a time.

**Rejected:** File locks around `.pypm/` and registry index mutation.

**Reason:** The capstone already covers resolver, registry, archive, install, verify, and graph behavior. Concurrency would be a meaningful future ADR, not an implicit claim.

---

## Consequences

**Positive:**
- The project demonstrates dependency resolution clearly.
- Resolver logic is pure and testable.
- Lockfiles are deterministic and complete.
- Install side effects are project-local.
- Registry validation catches malformed package metadata early.
- Safe tar extraction prevents path traversal and basic decompression-bomb cases.
- Install rollback and pruning keep `.pypm/` aligned with the resolved graph.
- Verification checks multiple layers of correctness.
- CLI commands cover realistic package-manager workflows.
- Non-goals are explicit and honest.

**Negative / Trade-offs:**
- Not compatible with pip, PyPI, wheels, Poetry, npm, virtualenvs, or global installs.
- Package archives are inert and do not run build steps.
- Constraint/version model is simplified.
- Resolver targets small educational graphs, not large real-world universes.
- No concurrency safety.
- No authentication, trust, signatures, ownership, moderation, or remote registry.
- Tree/why renderers assume modest graph size.
- Verification hashes paths and file contents, not empty directories or file permissions.

---

## Alternatives Not Explored

- PubGrub.
- SAT solving.
- PEP 440.
- Wheels.
- Public package index.
- Remote registry protocol.
- Authentication and authorization.
- Signed packages.
- Virtual environments.
- Executable entry points.
- Build isolation.
- Global installation.
- Cross-project cache.
- File locking.
- Django/HTMX registry browser as primary product.

---

*Constitution reference: Article 1 (Python fundamentals and architectural thinking), Article 3.3 (scope discipline), Article 4 (quality proportional to scope), Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity).*

---


# Technical Design Document
## App — Package Manager
**Package Management Systems Group | Document 2 of 5**

---

## Overview

PyPM Lab is a local educational package manager. It manages a project manifest, local registry, deterministic lockfile, and project-local `.pypm/` store. It resolves dependencies through a pure deterministic backtracking resolver and installs inert tar archives after integrity and extraction checks.

**Package:** `pypm-lab`  
**Import module:** `pypm_lab`  
**Console command:** `pypm`  
**Python:** `>=3.11.4`  
**Runtime dependencies:** none  
**Dev tools:** pytest, pytest-cov, Hypothesis, mypy, ruff  
**Coverage gate:** 95%

---

## System Context

```text
User / CI
  │
  ▼
pypm CLI
  │
  ├── package.json
  ├── registry/index.json
  ├── registry/archives/*.tar.gz
  ├── pypm-lock.json
  └── .pypm/
        ├── store/<name>/<version>/
        ├── cache/sha256/<digest>.tar.gz
        ├── tmp/
        └── installed.json
```

---

## Main Package Areas

```text
src/pypm_lab/
  cli.py                 # command-line interface and command orchestration
  versions.py            # strict major.minor.patch parsing
  constraints.py         # comparator, caret, tilde, range parsing
  requirements.py        # package name and requirement parsing
  models.py              # PackageVersion, ResolvedPackage, ResolvedGraph, StoreRecord
  resolver.py            # pure deterministic backtracking resolver
  conflicts.py           # conflict evidence and explanations
  graph.py               # cycle detection, topo sort, tree/why/graph renderers
  manifest.py            # package.json load/save/mutation
  lockfile.py            # deterministic lockfile serialization and parsing
  registry.py            # LocalRegistry and InMemoryRegistry
  registry_validation.py # registry/archive metadata validation
  tar_safe.py            # guarded tar inspection/extraction
  installer.py           # install graph into .pypm with cache/rollback/prune
  store.py               # .pypm installed records and clean
  integrity.py           # SHA-256 file/tree hashing
  verify.py              # end-to-end project verification
  publish.py             # local publish support
  outdated.py            # outdated/missing registry report
  fsio.py                # atomic JSON/text writes
  jsonio.py              # duplicate-key-safe JSON loading
  errors.py              # error hierarchy
```

---

## Data Model

### Project manifest

File:
```text
package.json
```

Shape:
```json
{
  "name": "demo-app",
  "dependencies": {
    "alpha": "^1.2.0",
    "bravo": ">=2.0.0,<3.0.0"
  }
}
```

Purpose:
- declares direct dependencies and version constraints
- does not pin exact transitive graph

---

### Lockfile

File:
```text
pypm-lock.json
```

Shape:
```json
{
  "lockfileVersion": 1,
  "roots": ["alpha"],
  "packages": {
    "alpha": {
      "version": "1.2.4",
      "integrity": "sha256:...",
      "dependencies": {
        "shared": ">=1.0.0,<2.0.0"
      }
    }
  }
}
```

Purpose:
- records exact selected versions
- records dependency edges
- records integrity hashes
- supports reproducible install
- supports graph/tree/why operations without re-solving

---

### Local registry

File:
```text
registry/index.json
```

Shape:
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

Purpose:
- maps package/version to archive, integrity, and dependency facts
- is local-only
- is structurally validated before being used

---

### Project store

Directory:
```text
.pypm/
  store/
    alpha/1.2.4/
  cache/
    sha256/<digest>.tar.gz
  tmp/
  installed.json
```

Purpose:
- install package data into project-local store
- cache archives by digest
- keep temporary extraction/placement state isolated
- record installed version/integrity/tree hash

---

## Core Data Structures

### `Version`

```python
@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int
```

Rules:
- strict `major.minor.patch`
- non-negative integer parts
- no pre-release, build metadata, or epochs

---

### `VersionConstraint`

```python
@dataclass(frozen=True)
class VersionConstraint:
    raw: str
    comparators: tuple[Comparator, ...]
```

Supports:
- wildcard `*`
- exact versions
- comma ranges
- caret ranges
- tilde ranges

All comparators are AND-combined.

---

### `Requirement`

```python
@dataclass(frozen=True)
class Requirement:
    name: str
    raw_constraint: str
    constraint: VersionConstraint
    raw: str
    source: str = "project manifest"
```

Purpose:
- direct or transitive constraint with source evidence
- normalized package name
- parsed constraint object

---

### `PackageVersion`

```python
@dataclass(frozen=True)
class PackageVersion:
    name: str
    version: Version
    dependencies: Mapping[str, str]
    integrity: str
    archive: Path | str
    metadata: Mapping[str, Any]
```

Purpose:
- package facts from registry
- input to resolver and installer

---

### `ResolvedGraph`

```python
@dataclass(frozen=True)
class ResolvedGraph:
    packages: Mapping[str, ResolvedPackage]
    roots: tuple[str, ...]
```

Provides:
- deterministic edge map
- root set for tree/why rendering
- input to lockfile and installer

---

### `StoreRecord`

```python
@dataclass(frozen=True)
class StoreRecord:
    name: str
    version: str
    integrity: str
    tree_hash: str
    path: str
```

Purpose:
- record installed state in `.pypm/installed.json`
- verify installed content has not been tampered with

---

## Resolver Design

### Input

```python
Resolver(registry).resolve(manifest.requirements())
```

### Narrow registry protocol

```python
class RegistryReader(Protocol):
    def available_versions(self, name: str) -> Sequence[Version]: ...
    def get_package_version(self, name: str, version: Version) -> PackageVersion: ...
```

### Algorithm

```text
resolve(requirements)
  ├── collect direct constraints by package
  ├── search(assignments={}, constraints, edges={})
  │    ├── check assigned versions still satisfy all constraints
  │    ├── find unresolved packages
  │    ├── select package with fewest compatible candidates
  │    ├── sort candidates highest-first
  │    ├── try candidate
  │    ├── add dependency constraints
  │    ├── detect graph cycle
  │    ├── recurse
  │    └── backtrack on failure
  └── return Resolution(graph, trace)
```

### Determinism

Determinism is enforced by:
- sorting requirements
- sorting package names
- sorting dependencies
- choosing most-constrained variable by candidate count and name
- sorting compatible versions highest-first
- sorting final graph packages

### Failure reporting

Resolution conflicts include:
- package name
- accumulated constraint evidence
- candidate rejections
- missing registry package message
- cycle message when detected

---

## Graph Design

### Cycle detection

`detect_cycle()` uses iterative DFS:
- deterministic node/dependency ordering
- no Python recursion-limit risk
- returns a concrete cycle path

### Topological sort

`topological_sort()`:
- rejects cycles
- returns dependencies before dependents
- used for install order

### Renderers

- `dependency_tree()`
- `why_paths()`
- `format_why()`
- `export_graph(fmt="adjacency"|"json"|"dot")`

Known limit:
- tree and why recursively walk modest resolved DAGs and can enumerate every path.

---

## Registry Design

### `InMemoryRegistry`

Used for pure resolver tests:
- no filesystem
- package facts injected as mappings
- normalized package names
- strict versions

### `LocalRegistry`

Backed by:
```text
registry/index.json
registry/archives/*.tar.gz
```

Load behavior:
- optionally validates registry
- builds `PackageVersion` objects
- resolves archive paths relative to registry root
- exposes available versions and exact package versions

---

## Registry Validation

Validation catches:
- missing registry index
- malformed JSON
- duplicate JSON keys
- invalid package names
- invalid versions
- missing versions object
- missing archive path
- absolute or escaping archive paths
- unsupported integrity format
- malformed constraints
- dependency on missing package
- archive missing
- archive hash mismatch
- unsafe archive member paths
- archive metadata name/version mismatch
- archive dependency disagreement

Validation is cumulative where possible, so users see multiple registry problems at once.

---

## Archive Safety

`safe_extractall()`:
- opens tar archive
- validates every member target stays inside destination
- sums declared member sizes
- rejects archives above the declared-size cap
- extracts with `filter="data"`

`read_archive_manifest()`:
- validates members before reading metadata
- finds the shallowest `package.json`
- parses JSON without duplicate keys
- requires package metadata to be an object

---

## Install Flow

```text
install_resolved(project_dir, graph, registry)
  ├── ensure .pypm/store, cache, tmp, installed.json
  ├── read previous installed records
  ├── topological_sort(graph)
  ├── for each package:
  │    ├── fetch exact PackageVersion from registry
  │    ├── verify resolved integrity matches registry integrity
  │    ├── cache archive by sha256 digest
  │    ├── verify cache file integrity
  │    ├── extract archive safely into .pypm/tmp
  │    ├── move content into placement dir
  │    ├── atomically replace .pypm/store/name/version
  │    ├── hash installed tree
  │    └── update installed record
  ├── prune records/directories not in graph
  ├── write installed.json
  └── return InstallReport
```

### Rollback

If install fails:
- previous directories are restored where possible
- newly installed attempted directories are removed
- new cache files not referenced by previous records are removed
- previous `installed.json` is rewritten
- incomplete rollback raises an explicit `InstallError`

---

## Lockfile Flow

### Write lockfile from graph

```python
Lockfile.from_graph(graph).dumps()
```

Properties:
- stable JSON ordering
- versioned schema
- complete roots and package entries
- dependency edges included

### Parse lockfile

Checks:
- JSON object
- supported `lockfileVersion`
- roots list
- packages object
- package names
- semantic versions
- integrity format
- dependency names
- every root exists
- every dependency points to a lockfile package

---

## Verification Flow

`verify_project()` checks:
- manifest roots match lockfile roots
- direct manifest constraints allow pinned root versions
- every lockfile package is reachable from roots
- every lockfile dependency constraint is satisfied by pinned dependency version
- each locked package exists in registry
- registry integrity matches lockfile integrity
- registry dependencies match lockfile dependencies
- registry archive bytes match lockfile integrity
- installed record exists
- installed version matches lockfile
- installed integrity matches lockfile
- installed package directory exists
- installed content tree hash matches record
- no installed records exist outside lockfile graph

---

## Publish Flow

```text
publish_archive(registry_dir, archive)
  ├── init registry if needed
  ├── read archive package.json
  ├── validate name/version/dependencies
  ├── copy archive into registry/archives via temp file + replace
  ├── compute sha256 integrity
  ├── add registry index entry
  ├── validate new entry
  ├── atomic-write registry/index.json
  └── return PackageVersion
```

---

## CLI Behavior

Primary commands:
- `init`
- `add`
- `remove`
- `resolve`
- `install`
- `update`
- `list`
- `tree`
- `why`
- `graph`
- `outdated`
- `verify`
- `clean`
- `publish`

Global options:
- `--version`
- `--project-dir`
- `--registry`

Exit codes:
- `0` success
- `1` runtime error/resolution failure/verification failure
- `2` usage error

---

## Known Limits

- Local-only.
- No remotes.
- No PyPI.
- No wheels.
- No virtual environments.
- No global installation.
- No package execution.
- No signatures or trust model.
- No authentication or ownership.
- No concurrency safety.
- No file locks.
- No decompression sandbox beyond path and declared-size checks.
- Verify does not hash empty directories or permissions.
- Tree/why graph renderers assume modest graph sizes.

---

## Verification Summary

The repository configures:
- Python 3.11.4+
- zero runtime dependencies
- pytest
- pytest-cov
- Hypothesis
- mypy with strict typed functions
- ruff lint
- coverage over `pypm_lab`
- coverage fail-under 95
- CI on Ubuntu for Python 3.11.4, 3.12, 3.13, and 3.14
- coverage XML artifact upload on 3.11.4

README states:
- 282 tests
- local coverage around 98%
- property-based tests for semver/constraint invariants and resolution invariance
- tests covering resolver backtracking, graph algorithms, lockfiles, registry validation, install rollback, tar safety, verify tamper detection, and CLI exit codes

---

*Constitution reference: Article 4 (engineering quality), Article 6 (behavior verification), Article 7 (progressive complexity), and Article 8 (valid learner work).*

---


# Interface Design Specification
## App — Package Manager
**Package Management Systems Group | Document 3 of 5**

---

## Public CLI Interface

### Console command

```powershell
pypm <command> [options]
```

### Global options

```powershell
pypm --version
pypm --project-dir <path> <command>
pypm --registry <path> <command>
```

Defaults:
- project dir: current directory
- registry: `registry` relative to project unless absolute

---

## Command Reference

### `init`

```powershell
pypm init
pypm init --name demo-app
```

Creates:
- `package.json`
- `registry/index.json`
- `registry/archives/`
- `.pypm/store/`
- `.pypm/cache/sha256/`
- `.pypm/tmp/`
- `.pypm/installed.json`

---

### `publish`

```powershell
pypm publish examples\dist\alpha-1.2.4.tar.gz
```

Behavior:
- reads archive package metadata
- copies archive into local registry
- computes `sha256:` integrity
- updates `registry/index.json`

---

### `add`

```powershell
pypm add alpha ^1.2.0
pypm add alpha@^1.2.0
```

Behavior:
- validates package name
- parses constraint
- updates `package.json`
- warns when an existing lockfile/store is now out of sync

---

### `remove`

```powershell
pypm remove alpha
```

Behavior:
- removes a direct dependency from `package.json`
- warns when lockfile/store is now out of sync

---

### `resolve`

```powershell
pypm resolve
pypm resolve --trace
```

Behavior:
- loads manifest
- loads local registry
- resolves dependency graph
- writes `pypm-lock.json`
- does not install packages
- prints a note when `.pypm/` is out of sync
- trace mode prints resolver decisions

---

### `install`

```powershell
pypm install
pypm install --locked
```

Behavior:
- default install uses an existing lockfile when it satisfies the manifest
- re-resolves only when the lockfile is missing or stale
- installs exact graph into `.pypm/`
- writes/updates lockfile only after successful install when re-resolution occurs
- prunes packages no longer in the resolved graph

`--locked` behavior:
- reads `pypm-lock.json`
- skips resolution
- installs exact pinned graph
- verifies pinned integrity against registry

---

### `update`

```powershell
pypm update
```

Behavior:
- always resolves latest compatible graph
- installs resolved graph
- writes lockfile after successful install

---

### `list`

```powershell
pypm list
```

Behavior:
- reads `.pypm/installed.json`
- prints installed package versions
- prints `no packages installed` when empty

---

### `tree`

```powershell
pypm tree
```

Behavior:
- reads `pypm-lock.json`
- prints dependency tree from roots

---

### `why`

```powershell
pypm why shared
pypm why shared --all
```

Behavior:
- reads lockfile graph
- prints shortest dependency path by default
- `--all` prints every path
- exits `1` when target is not present in graph

---

### `graph`

```powershell
pypm graph
pypm graph --format json
pypm graph --format dot
```

Formats:
- `adjacency`
- `json`
- `dot`

---

### `outdated`

```powershell
pypm outdated
pypm outdated --strict
```

Behavior:
- reads lockfile and manifest
- compares locked versions with registry versions
- reports newest version and newest manifest-compatible version for direct dependencies
- reports registry-missing lockfile packages
- `--strict` exits `1` only when packages are missing from registry

---

### `verify`

```powershell
pypm verify
```

Behavior:
- checks manifest, lockfile, registry archive integrity, installed records, installed directories, content hashes, reachability, and constraint consistency
- prints `verification passed` on success
- exits `1` on failure

---

### `clean`

```powershell
pypm clean
pypm clean --dry-run
```

Behavior:
- removes orphaned store directories
- removes cache archives not referenced by installed records
- removes leftover temp files
- dry-run reports without deletion

---

## Version Interface

Valid version:

```text
1.2.3
0.0.1
10.20.30
```

Invalid:
- `1.2`
- `1.2.3-alpha`
- `v1.2.3`
- `1.2.3+build`
- negative versions

---

## Constraint Interface

Supported:

```text
*
1.2.3
=1.2.3
==1.2.3
>=1.2.0
>=1.2.0,<2.0.0
^1.2.3
^0.2.3
^0.0.3
~1.2.3
```

Caret expansion:
- `^1.2.3` -> `>=1.2.3,<2.0.0`
- `^0.2.3` -> `>=0.2.3,<0.3.0`
- `^0.0.3` -> `>=0.0.3,<0.0.4`

Tilde expansion:
- `~1.2.3` -> `>=1.2.3,<1.3.0`

---

## Requirement Interface

Supported forms:

```text
alpha@^1.2.0
bravo@>=2.0.0,<3.0.0
charlie@1.4.2
delta@~1.2.0
```

CLI split form:

```powershell
pypm add alpha ^1.2.0
```

Package name rules:
- lowercased
- letters, numbers, dots, dashes, underscores
- cannot contain path separators
- cannot start or end with dot
- cannot be empty

---

## Registry Archive Contract

Archive shape:

```text
alpha-1.2.4/
  package.json
  src/
    alpha.txt
  README.md
```

Archive `package.json`:

```json
{
  "name": "alpha",
  "version": "1.2.4",
  "dependencies": {
    "shared": ">=1.0.0,<2.0.0"
  }
}
```

Rules:
- archive metadata name must match registry package name
- archive metadata version must match registry version
- archive metadata dependencies must match registry index dependencies
- archive paths must not escape extraction root
- archive must not exceed declared-size cap
- archive is inert and not executed

---

## Public Python API Surface

The project is CLI-first, but major components are importable.

Common imports:

```python
from pypm_lab.versions import Version
from pypm_lab.constraints import VersionConstraint
from pypm_lab.requirements import parse_requirement, parse_requirement_parts
from pypm_lab.registry import InMemoryRegistry, LocalRegistry
from pypm_lab.resolver import Resolver, resolve
from pypm_lab.lockfile import Lockfile, load_lockfile, write_lockfile
from pypm_lab.installer import install_resolved, install_from_lockfile
from pypm_lab.verify import verify_project
```

---

## CLI Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Runtime error, resolution failure, integrity failure, verification failure, missing why target |
| `2` | Usage error or invalid arguments |

---

## Side Effects

| Operation | Side Effect |
|---|---|
| `init` | Creates manifest, registry, and `.pypm/` structure |
| `publish` | Copies archive and updates registry index |
| `add` / `remove` | Mutates `package.json` |
| `resolve` | Writes `pypm-lock.json` |
| `install` | Installs packages into `.pypm/`, may write lockfile |
| `install --locked` | Installs from existing lockfile only |
| `update` | Re-resolves, installs, writes lockfile |
| `verify` | Reads and hashes registry/store files |
| `clean` | Prunes store/cache/tmp |
| `tree` / `why` / `graph` | Reads lockfile graph |
| `outdated` | Reads lockfile, manifest, registry |

---

## Error Output Contract

Errors are printed to stderr:
- resolution conflict explanations
- registry validation errors
- PyPM runtime errors as `error: ...`

Examples:
```text
error: missing manifest package.json; run `pypm init` first
Dependency cycle detected: a -> b -> a.
error: hash mismatch for ...
```

---

*Constitution reference: Article 4 (input/output boundaries), Article 6 (verification), and Article 8 (understandable and verifiable work).*

---


# Runbook
## App — Package Manager
**Package Management Systems Group | Document 4 of 5**

---

## Requirements

### Runtime

- Python 3.11.4+
- No runtime dependencies

### Development

- pytest
- pytest-cov
- Hypothesis
- mypy
- ruff

---

## Installation

### Development install

```powershell
python -m pip install -r requirements-dev.txt
```

Alternative:

```powershell
python -m pip install -e ".[dev]"
```

---

## First Smoke Test

### Windows PowerShell

```powershell
python examples\build_archives.py
pypm init
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

### Linux/macOS

```bash
python examples/build_archives.py
pypm init
pypm publish examples/dist/shared-1.5.0.tar.gz
pypm publish examples/dist/alpha-1.2.4.tar.gz
pypm add alpha ^1.2.0
pypm resolve --trace
pypm install
pypm verify
```

Expected:
- registry index is created
- packages are published locally
- manifest records `alpha`
- lockfile pins exact versions
- install populates `.pypm/store`
- verify passes

---

## Common Workflows

### Initialize

```powershell
pypm init --name demo-app
```

### Add dependency

```powershell
pypm add alpha ^1.2.0
```

### Reproducible install

```powershell
pypm install
```

### Locked install

```powershell
pypm install --locked
```

### Force re-resolution

```powershell
pypm update
```

### Remove dependency and reconcile store

```powershell
pypm remove alpha
pypm install
```

### Clean unused store/cache files

```powershell
pypm clean --dry-run
pypm clean
```

---

## Inspecting the Graph

### Tree

```powershell
pypm tree
```

### Why

```powershell
pypm why shared
pypm why shared --all
```

### Export graph

```powershell
pypm graph
pypm graph --format json
pypm graph --format dot
```

---

## Outdated Check

```powershell
pypm outdated
pypm outdated --strict
```

Use `--strict` in CI only when missing registry packages should fail the build.

---

## Verification

```powershell
pypm verify
```

A passing project prints:

```text
verification passed
```

Failing verification can indicate:
- manifest and lockfile mismatch
- missing registry archive
- archive hash mismatch
- installed package directory missing
- installed contents modified
- installed record not in lockfile
- lockfile dependency inconsistency

---

## Registry Maintenance

### Publish archive

```powershell
pypm publish path\to\package-1.0.0.tar.gz
```

Publish order:
- unconstrained
- dependency packages do not have to be published first
- all dependencies must exist before resolve/install uses the registry

### Registry files

```text
registry/
  index.json
  archives/
    alpha-1.2.4.tar.gz
```

Do not hand-edit unless intentionally testing validation failures.

---

## Quality Checks

### Ruff

```powershell
python -m ruff check src tests examples benchmarks
```

### Mypy

```powershell
python -m mypy
```

### Tests with coverage

```powershell
python -m pytest --cov=pypm_lab --cov-report=term-missing --cov-fail-under=95
```

---

## CI Parity

GitHub Actions runs:
- Ubuntu latest
- Python 3.11.4, 3.12, 3.13, 3.14
- install package and dev tools
- Ruff over `src`, `tests`, `examples`, `benchmarks`
- mypy
- pytest with coverage
- coverage fail-under 95
- coverage XML upload for Python 3.11.4

---

## Benchmark

```powershell
python benchmarks\bench_resolver.py
```

or:

```bash
python benchmarks/bench_resolver.py
```

Purpose:
- show resolver scaling on generated package universes
- not a production performance guarantee

---

## Troubleshooting

### `missing manifest package.json; run pypm init first`

Fix:
```powershell
pypm init
```

---

### `manifest and lockfile differ`

Cause:
- `add` or `remove` changed direct dependencies after a lockfile existed

Fix:
```powershell
pypm install
```

or:

```powershell
pypm update
```

---

### `lockfile written; run pypm install`

Cause:
- `resolve` updated the lockfile only

Fix:
```powershell
pypm install
```

---

### Dependency cannot resolve

Actions:
- run `pypm resolve --trace`
- check every dependency exists in registry
- check constraints overlap
- check for cycles
- inspect registry dependencies for transitive conflicts

---

### Hash mismatch

Cause:
- archive bytes changed after publish
- registry index integrity was edited
- cache archive was corrupted

Actions:
- re-publish package archive
- inspect `registry/index.json`
- delete affected cache file and reinstall
- run `pypm verify`

---

### Archive extraction failure

Possible causes:
- archive member escapes destination
- tar member size cap exceeded
- malformed tar archive
- missing package.json

Fix:
- rebuild the archive using `examples/build_archives.py` as a reference
- ensure top-level package directory contains package.json

---

### `why` exits 1

Cause:
- target package is not present in lockfile graph

Fix:
- run `pypm tree`
- check spelling
- run `pypm resolve` or `pypm install` if lockfile is stale

---

### `outdated --strict` exits 1

Cause:
- a lockfile package is missing from registry

Fix:
- publish the missing package version
- or update/remove the dependency and re-run install/update

---

### Store has old packages

Fix:
```powershell
pypm install
pypm clean
```

Install prunes packages dropped by the resolved graph. Clean removes extra store/cache/tmp leftovers.

---

## Maintenance Notes

- Keep resolver pure.
- Keep installs project-local.
- Keep packages inert.
- Do not add pip/PyPI compatibility claims.
- Add tests before changing constraint parsing.
- Add tests before changing resolver selection order.
- Add tests before changing lockfile schema.
- Add tests before changing safe extraction.
- Preserve deterministic JSON serialization.
- Preserve install rollback behavior.
- Preserve the difference between `install` and `update`.
- Add an ADR before introducing concurrency locks.
- Add an ADR before introducing remote registry/auth/signatures.

---

*Constitution reference: Article 6 (behavior verification), Article 5 (constraints and trade-offs), and Article 8 (verifiable learner work).*

---


# Lessons Learned
## App — Package Manager
**Package Management Systems Group | Document 5 of 5**

---

## Why This Design Was Chosen

This design was chosen because a package manager is a strong systems capstone. It touches multiple hard areas at once: version parsing, constraint satisfaction, dependency graphs, deterministic lockfiles, archive integrity, safe extraction, installation ordering, rollback, and verification.

The most important design choice was separating pure resolution from filesystem mutation. The resolver does not know about files. It only asks a registry interface for available versions and package facts. That makes the core algorithm easy to test and explain.

The second important choice was making packages inert and project-local. This keeps the project safe and bounded. It demonstrates package-manager mechanics without claiming to solve the much larger security and compatibility problems of real package ecosystems.

The third important choice was deterministic output. Stable lockfile ordering, deterministic candidate selection, and stable graph rendering make the tool reviewable and testable.

---

## What Was Intentionally Omitted

**Pip/PyPI compatibility:** Out of scope.

**Wheels and build backends:** Out of scope.

**Virtual environments:** Out of scope.

**Global package installs:** Out of scope.

**Executable entry points:** Out of scope.

**Running package code:** Omitted for safety.

**Remote registry:** Deferred.

**Authentication/authorization:** Deferred.

**Package signatures/trust:** Deferred.

**Concurrency safety:** Deferred.

**Large production-scale solver:** Deferred.

**Django/HTMX registry UI:** Stretch-only and should call the same service layer.

---

## Biggest Weakness

The biggest weakness is that the project is not concurrency-safe. The CLI assumes one user runs one command at a time. That is acceptable for a local educational package manager, but a production package manager would need lock files or another coordination mechanism around `.pypm/`, `package.json`, `pypm-lock.json`, and `registry/index.json`.

The second weakness is solver sophistication. Deterministic backtracking is readable and effective for the project’s intended scale, but real package ecosystems often need more advanced conflict explanation and search behavior.

The third weakness is trust. SHA-256 integrity detects changes, but it does not prove who created a package. A real registry would need signing, identity, ownership, moderation, and revocation policies.

---

## Scaling Considerations

**If registry size grows:**
- index package metadata more efficiently
- avoid validating every archive during common commands
- cache parsed registry metadata
- add package/version lookup indexes

**If resolver complexity grows:**
- add better conflict minimization
- consider PubGrub
- add decision-level trace reports
- benchmark deeper and wider graphs

**If install safety grows:**
- add lock files
- add transaction journal
- add stronger rollback recovery
- add content-addressed unpacked store
- add permission hashing

**If trust grows:**
- add signature verification
- add publisher identity
- add registry ownership rules
- add revocation metadata

**If UX grows:**
- add a registry browser
- add lockfile diff output
- add explain-resolution reports
- add command aliases and shell completion

---

## What the Next Refactor Would Be

1. **Repository locks** — serialize writes to manifest, lockfile, registry, and `.pypm/`.

2. **Conflict report improvements** — make resolver failures explain the smallest useful cause set.

3. **Lockfile diff command** — show what changed between current lockfile and a newly resolved graph.

4. **Package signature model** — distinguish integrity from authenticity.

5. **Content-addressed unpacked store** — deduplicate identical installed package contents.

---

## What This Project Taught

- **Dependency resolution is constraint solving.** The hard part is not reading a JSON file; it is reconciling all constraints that reach a package.

- **Determinism matters.** Stable ordering makes resolver behavior easier to test and trust.

- **Lockfiles are contracts.** A good lockfile must describe a complete graph, not only root packages.

- **Install should be transactional.** A package manager should not leave half-installed state after failure.

- **Integrity is not trust.** Hashes detect tampering but do not authenticate publishers.

- **Archive extraction is dangerous by default.** Path traversal and large declared sizes must be guarded.

- **Pure cores make better systems.** Keeping resolver logic independent from filesystem I/O made the package manager easier to verify.

- **Scope discipline is strength.** A focused local package manager is more defensible than a vague claim to compete with pip or PyPI.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity) for Package Manager.*
