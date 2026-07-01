# ADR 0002: Local registry and inert archives

## Status

Accepted.

## Context

PyPM Lab teaches **local registry mechanics** and **integrity**, not Python packaging standards. The project must stay inspectable on disk, avoid mutating global Python installations, and treat third-party archives as untrusted data. The capstone is CLI-first; a web registry layer (Django + HTMX) is stretch-only and must not own resolver logic.

Packages must never execute code from archives. Demonstrations should work entirely under a project directory (`.pypm/`) and a file-based `registry/index.json`.

## Decision

**Custom local registry**

- Store authoritative package metadata in `registry/index.json`: versions, dependency ranges, archive paths, and `sha256:` integrity values.
- Keep `publish` **local-only**: no accounts, authentication, ownership, or moderation.
- Validate the index structurally on load. Do **not** require dependencies to exist at publish time so cyclic pairs can be published in any order; cross-package existence is enforced when the registry is loaded for `resolve` / `install`.
- Re-hash archives on demand via `validate_registry` for callers that want full byte checks; routine commands rely on structural validation plus install-time / `verify` hashing (see [ADR 0003](0003-lockfile-install-verify-store-model.md)).

**Inert archives**

- Packages are `.tar.gz` archives whose top-level directory is `<name>-<version>/` with an inner `package.json` matching registry name, version, and dependencies.
- Installation **never executes** archive contents; files are copied, hashed, and unpacked as data only.
- Install only into `.pypm/` — never global site-packages, user site-packages, or system paths.
- PyPM Lab is **not pip/PyPI compatible** by design.

**Safe extraction**

- Share one `tar_safe` module for publish and install: path-escape checks, symlink/hard-link rejection, tarfile `data` filter (Python ≥ 3.11.4), and a fixed declared-size cap to limit decompression-bomb risk.
- Reject archives whose metadata disagrees with the registry before resolution begins.

## Alternatives considered

| Alternative | Why not chosen |
|-------------|----------------|
| **PyPI / pip metadata and wheels** | Shifts focus to ecosystem compatibility instead of constraint solving and local integrity. |
| **Require dependencies to exist before `publish`** | Blocks end-to-end cycle demos and forces artificial publish ordering. |
| **Hash every archive on every registry read** | Too slow for interactive CLI; integrity is enforced where it matters (install + `verify`). |
| **Execute setup hooks or entry points** | Out of scope; violates inert-archive teaching boundary. |

## Consequences

**Positive**

- Registry and archives are human-readable on disk, ideal for grading and debugging.
- Structural vs byte-level validation split keeps CLI responsive while preserving tamper detection at install time.
- Shared tar safety logic reduces duplicate validation bugs.

**Negative**

- Not interoperable with real Python packaging tools.
- Declared-size cap is a basic guard, not a sandbox; permissions and empty-directory hashing are intentionally limited (documented in README limitations).

**Follow-ups**

- Optional Django + HTMX browser would call the same service layer; it does not replace this contract.
