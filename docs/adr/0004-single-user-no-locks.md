# ADR 0004: Single-user CLI with no file locks

## Status

Accepted.

## Context

PyPM Lab targets **educational demonstrations** on a single machine: one student runs one terminal session against one project directory and one local registry. Adding cross-process locking, file watchers, or concurrent publish/install coordination would expand scope into distributed systems problems the capstone does not require.

Several commands perform multi-step read/modify/write sequences across `registry/index.json`, `pypm-lock.json`, and `.pypm/` without transactional filesystem guarantees beyond atomic single-file writes.

## Decision

Treat the CLI as **single-user and non-concurrent**:

- Take **no advisory or mandatory locks** on `.pypm/`, the registry index, or project manifests.
- Assume at most one `pypm` process mutates a given project or registry at a time.
- Document this boundary explicitly in README limitations rather than implying production-grade concurrency safety.

Atomic **single-file** writes (manifest, lockfile, index, `installed.json`) remain required so a crash mid-write does not produce parsable-but-partial JSON; that is not the same as serializing concurrent writers.

## Alternatives considered

| Alternative | Why not chosen |
|-------------|----------------|
| **File locks (e.g. `fcntl`, `msvcrt`)** | Platform-specific complexity; errors when locks stale; not needed for demo use. |
| **SQLite registry backend** | Hides the “inspect JSON on disk” teaching goal. |
| **Optimistic concurrency tokens on index.json** | More machinery than the project size warrants. |
| **Document nothing and hope** | Reviewers cannot tell omission from oversight under Tier L ADR expectations. |

## Consequences

**Positive**

- Implementation stays small; tests use sequential CLI invocations in temp dirs without lock fixtures.
- Failure modes from concurrent use are out of scope rather than silently undefined.

**Negative**

- Parallel `pypm install` or `pypm publish` against the same paths can corrupt state; callers must serialize externally.
- Not suitable as a multi-tenant registry service without a redesign.

**Follow-ups**

- A future web layer (stretch) would need its own concurrency story if it shared the same on-disk registry.
