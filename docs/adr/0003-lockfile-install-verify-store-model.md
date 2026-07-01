# ADR 0003: Lockfile, install, verify, and store model

## Status

Accepted.

## Context

After resolution, users need **reproducible installs**, **atomic failure behavior**, and **integrity checks** across manifest, lockfile, registry, cache, and `.pypm/store/`. Manifest edits, failed installs, and partial graphs must not leave silent corruption or orphaned state.

The CLI exposes separate commands (`resolve`, `install`, `update`, `verify`, `clean`) whose ordering and persistence rules are easy to get wrong without an explicit model.

## Decision

**Artifacts**

- `package.json` — desired ranges (manifest).
- `pypm-lock.json` — exact resolved versions, integrity hashes, dependency edges; **stable serialization** for deterministic output.
- `.pypm/store/`, `.pypm/cache/sha256/`, `.pypm/tmp/`, `.pypm/installed.json` — project-local install state.

**Lockfile lifecycle**

- `resolve` writes the lockfile **without installing** and prints a note when `.pypm/` is out of sync with the new graph.
- `install` is reproducible by default: reuse an existing lockfile when it still satisfies the manifest; re-resolve only when the lockfile is missing or stale.
- `update` always re-resolves to the newest compatible graph.
- `install --locked` never resolves; it fails if the lockfile is missing and installs exact pinned versions only.
- `install` and `update` persist the lockfile **only after a successful install**; a failed install leaves the prior lockfile untouched.

**Manifest-edit sync notes**

- `add` and `remove` print a **stderr note** when a lockfile exists but the manifest no longer matches it or `.pypm/` is out of sync, mirroring the post-`resolve` install reminder. This makes manual manifest edits visible without auto-running install.

**Install and store**

- Install order follows a **topological sort** of the resolved DAG (dependencies first).
- Each package: copy archive to content-addressed cache, re-hash, safe unpack to a temp dir, atomic move into `store/`, then record in `installed.json`.
- Failed graph installs **roll back** store directories, cache entries, and `installed.json`, aggregating every restore failure in one error.
- Remove orphan store directories **only after** `installed.json` updates successfully so a failed install cannot delete still-recorded packages.
- After install, **reconcile** the store to the resolved set (prune removed packages from `store/` and `installed.json`). `clean` is a separate command for pruning unreferenced cache archives.

**Integrity and JSON safety**

- SHA-256 is the sole integrity algorithm across registry, lockfile, cache, and installed trees.
- Manifest, lockfile, registry index, and `installed.json` use **atomic writes** and **duplicate-key rejection** on parse.
- `verify` checks manifest–lockfile alignment, lockfile reachability from roots, lockfile–registry dependency agreement, installed records, on-disk trees, content hashes, and internal lockfile constraint consistency — not lockfile self-consistency alone.

## Alternatives considered

| Alternative | Why not chosen |
|-------------|----------------|
| **Write lockfile before install completes** | Leaves lockfile ahead of store after failures; breaks `verify` trust. |
| **Auto-install on every manifest edit** | Hides the resolve/install split and surprises users mid-demo. |
| **Silent manifest/lockfile drift** | Manual edits look successful until a later command fails obscurely. |
| **Leave orphaned store dirs after failed install** | Complicates `verify` and confuses “what is installed?” |
| **Verify lockfile JSON only** | Misses registry skew, unreachable packages, and on-disk tampering. |

## Consequences

**Positive**

- Clear command boundaries for teaching: resolve → install → verify.
- Rollback and atomic JSON writes make failure modes testable.
- Sync notes guide users after manifest edits without forcing side effects.

**Negative**

- Users must run `install` after `resolve` or manifest changes; extra step by design.
- `verify` is thorough and therefore slower than a checksum-only spot check.

**Related ADRs**

- Resolver output: [ADR 0001](0001-deterministic-backtracking-resolver.md)
- Archive handling: [ADR 0002](0002-local-registry-and-inert-archives.md)
- Concurrency limits: [ADR 0004](0004-single-user-no-locks.md)
