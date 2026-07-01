"""Micro-benchmark for the dependency resolver on a generated package universe

Run with:

    python benchmarks/bench_resolver.py

It builds synthetic, acyclic package universes of increasing size (each package
depends only on lower-indexed packages, with permissive constraints) and times a
full resolution. This exercises the common, mostly-greedy path; adversarial
constraint graphs can still force the backtracking search toward its worst case,
which is the documented limitation of a simple backtracking resolver.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypm_lab.registry import InMemoryRegistry  # noqa: E402
from pypm_lab.requirements import parse_requirement  # noqa: E402
from pypm_lab.resolver import Resolver  # noqa: E402


def build_universe(
    n_packages: int,
    *,
    versions_per_package: int = 3,
    max_deps: int = 4,
    seed: int = 1234,
) -> dict[str, dict[str, dict[str, object]]]:
    rng = random.Random(seed)
    names = [f"pkg{i:04d}" for i in range(n_packages)]
    universe: dict[str, dict[str, dict[str, object]]] = {}
    for index, name in enumerate(names):
        versions: dict[str, dict[str, object]] = {}
        for minor in range(versions_per_package):
            lower = names[:index]
            dependencies: dict[str, str] = {}
            if lower:
                count = rng.randint(0, min(max_deps, len(lower)))
                for dep in rng.sample(lower, count):
                    dependencies[dep] = ">=1.0.0"  # permissive: stays satisfiable
            versions[f"1.{minor}.0"] = {"dependencies": dependencies}
        universe[name] = versions
    return universe


def main() -> None:
    print(f"{'packages':>10} {'resolved':>10} {'time (ms)':>12}")
    for n_packages in (10, 50, 100, 250, 500):
        universe = build_universe(n_packages)
        registry = InMemoryRegistry(universe)
        # Require every package so the whole universe is resolved each run.
        requirements = [parse_requirement(f"{name}@>=1.0.0") for name in universe]

        start = time.perf_counter()
        resolution = Resolver(registry).resolve(requirements)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        print(f"{n_packages:>10} {len(resolution.graph.packages):>10} {elapsed_ms:>12.1f}")


if __name__ == "__main__":
    main()
