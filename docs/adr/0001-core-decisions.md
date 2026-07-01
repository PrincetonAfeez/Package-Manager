# ADR 0001: Core Project Decisions

## Status

Accepted.

## Decisions

1. PyPM Lab is CLI-first because the capstone goal is systems behavior that can be demonstrated directly from the terminal.
2. Django + HTMX is stretch-only because the package manager core should not depend on a web layer.
3. PyPM Lab is not pip-compatible because the project teaches dependency solving and local registry mechanics rather than Python packaging standards.
4. Packages install only into `.pypm/` so demos never modify global Python, user site-packages, or system paths.
5. The registry is custom and local so package facts stay inspectable and deterministic.
6. Package archives are inert data, and installation never executes archive contents.
7. The resolver is pure and separated from I/O so it can be unit-tested with an in-memory registry.
8. The resolver uses deterministic backtracking because it makes graph search visible without introducing a full PubGrub implementation.
9. Conflict reporting uses a `Conflict` object so explanations are testable and not scattered across CLI strings.
10. Lockfiles are deterministic and stable so equivalent inputs produce reproducible installs.
11. `install --locked` skips resolution because lockfiles represent exact prior solver output.
12. Atomic install behavior is required so a failed package is not marked installed.
13. SHA-256 integrity verification is core because the registry, lockfile, cache, and install path all rely on byte identity.
14. `publish` is local-only and intentionally excludes accounts, auth, ownership, and moderation.
15. Graph export supports adjacency text, JSON, and DOT so the resolved DAG can be inspected in several common forms.
16. The resolver selects the most-constrained unresolved package first (fewest compatible candidates, ties broken by name). This most-constrained-variable heuristic is deterministic and fails fast on conflicts.
17. `publish` validates the index structurally but does not require a package's dependencies to already exist, so packages — including cyclic pairs — can be published in any order. Cross-package dependency existence is enforced later, when the registry is loaded for resolve/install. This keeps the cycle-detection demo reachable end-to-end instead of forcing reverse-topological publishing.
18. `install` is reproducible by default: it reuses an existing lockfile when that lockfile still satisfies the manifest, and only re-resolves when the lockfile is missing or stale. `update` always re-resolves to the newest compatible graph. `install --locked` never resolves and fails if the lockfile is missing.
19. Archive byte integrity is verified by the installer immediately before placement and by `verify`, which is where a hash mismatch matters. Loading the registry index therefore performs structural validation by default rather than re-hashing every archive on every command; the standalone `validate_registry` still offers full archive hashing for callers that want it.
20. `install` reconciles the store to the resolved set, pruning packages (directories and `installed.json` records) that are no longer part of the graph, so a `remove` followed by `install` leaves `verify` clean. `clean` is a separate, explicit command for pruning cache archives no longer referenced by an installed package.
21. Archive extraction uses the tarfile `data` filter and a fixed total-size cap, treating archives as untrusted-but-inert data: traversal, escaping links, and decompression bombs are rejected, but contents are never executed.
22. `install` and `update` persist the lockfile only after a successful install; a failed install leaves the prior lockfile untouched. `resolve` writes the lockfile without installing and warns when `.pypm/` is out of sync.
23. Manifest, lockfile, registry index, and `installed.json` are written atomically and parsed with duplicate-key rejection so silent JSON overwrites cannot drop dependency entries.
24. `verify` checks manifest-lockfile alignment, lockfile reachability from roots, lockfile-registry dependency agreement, and archive integrity — not just internal lockfile consistency.
25. Tar inspection for publish and install shares one safe-tar module (`tar_safe`) with path-escape checks, declared-size caps, and the `data` filter on extraction.
26. Failed graph installs roll back store directories, cache entries, and `installed.json`, reporting every restore failure in one error.
27. Orphan store directories are removed only after `installed.json` is updated successfully, so a failed install cannot delete packages that were still recorded.
28. `add` and `remove` warn on stderr when a lockfile exists but the manifest no longer matches it or `.pypm/` is out of sync, mirroring the note `resolve` prints after writing a lockfile.
