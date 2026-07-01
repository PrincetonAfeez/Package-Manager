# Architecture Decision Records

PyPM Lab documents non-obvious design trade-offs as [Architecture Decision Records (ADRs)](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions). Each ADR is a short, accepted decision with context, alternatives, and consequences.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-deterministic-backtracking-resolver.md) | Deterministic backtracking resolver | Accepted |
| [0002](0002-local-registry-and-inert-archives.md) | Local registry and inert archives | Accepted |
| [0003](0003-lockfile-install-verify-store-model.md) | Lockfile, install, verify, and store model | Accepted |
| [0004](0004-single-user-no-locks.md) | Single-user CLI with no file locks | Accepted |

## Scope

These ADRs cover the educational package manager core: dependency resolution, local registry contracts, reproducible installs, and explicit non-goals. They do **not** cover the optional Django + HTMX registry browser (stretch-only).

## Adding or changing decisions

1. Propose a new numbered ADR or amend an existing one in a pull request.
2. Keep the decision text aligned with behavior in `src/pypm_lab/` and the README.
3. Reference the ADR path and section in `CHANGELOG.md` when a user-visible behavior is tied to a recorded decision.
