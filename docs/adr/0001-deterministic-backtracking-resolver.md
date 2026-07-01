# ADR 0001: Deterministic backtracking resolver

## Status

Accepted.

## Context

PyPM Lab is a capstone systems project whose primary learning goal is **dependency resolution as a graph and constraint problem**. The resolver must be understandable in code review, unit-testable without a filesystem, and reproducible: the same registry facts and manifest must always yield the same resolved graph and lockfile.

Real package managers (npm, Cargo, Poetry, and others) often use more advanced solvers. PubGrub in particular minimizes backtracking and produces excellent conflict explanations, but implementing it would dominate the project scope and obscure the graph search mechanics the course is meant to demonstrate.

## Decision

Implement a **pure resolver** separated from I/O:

- Query package facts through a registry interface; no direct filesystem access inside the resolver.
- Accumulate all constraints that reach each package during search.
- Resolve with **deterministic depth-first backtracking**:
  1. Choose the next unresolved package by **most-constrained variable**: fewest compatible candidate versions, ties broken by package name.
  2. Try candidate versions in **highest-first** order.
  3. Propagate dependency constraints and recurse.
  4. Backtrack on conflict, recording why each candidate was rejected.
- Detect cycles during search: an edge that would close a cycle is rejected like any other dead end; unsatisfiable searches report an explicit `Dependency cycle detected: …` line.
- Represent conflicts as structured `Conflict` objects so explanations are testable rather than ad hoc CLI strings.
- Serialize the resolved DAG into a stable lockfile (see [ADR 0003](0003-lockfile-install-verify-store-model.md)).

## Alternatives considered

| Alternative | Why not chosen |
|-------------|----------------|
| **PubGrub / version-set solver** | Best-in-class for production registries, but a full implementation would crowd out graph, backtracking, and test coverage goals. |
| **Greedy highest-version pick without backtracking** | Fails on common dependency diamonds and hides constraint propagation. |
| **Random or hash-based tie-breaking** | Breaks reproducibility and makes lockfile diffs non-deterministic. |
| **Resolver coupled to registry files** | Harder to test; mixes persistence with search logic. |

## Consequences

**Positive**

- Resolver behavior is visible in traces (`pypm resolve --trace`) and small enough to reason about in lectures.
- In-memory registry fixtures make unit tests fast and exhaustive.
- Deterministic ordering supports stable lockfiles and property-based tests.

**Negative**

- Search can revisit more branches than PubGrub on large universes; graph renderers (`tree`, `why --all`) assume modest fixture sizes.
- Conflict messages are correct but not as minimal as PubGrub’s “incompatibility” narratives.

**Follow-ups**

- Graph export (adjacency, JSON, DOT) documents the resolved DAG for inspection outside the CLI.
