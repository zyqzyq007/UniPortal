"""Bounded Personalized PageRank and short-path utilities."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite

__all__ = ["PPRResult", "bounded_shortest_paths", "personalized_pagerank"]


@dataclass(frozen=True)
class PPRResult:
    scores: dict[str, float]
    converged: bool
    iterations: int
    degraded: bool


def _bounded_reachable(
    adjacency: dict[str, dict[str, float]],
    seeds: set[str],
    maximum: int,
) -> list[str]:
    queue = deque(sorted(seed for seed in seeds if seed in adjacency))
    visited: set[str] = set()
    while queue and len(visited) < maximum:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in sorted(adjacency.get(node, {})):
            if neighbor not in visited and neighbor in adjacency:
                queue.append(neighbor)
    return sorted(visited)


def personalized_pagerank(
    adjacency: dict[str, dict[str, float]],
    seeds: set[str],
    *,
    alpha: float = 0.85,
    max_iterations: int = 30,
    tolerance: float = 1e-6,
    max_nodes: int = 5000,
) -> PPRResult:
    """Run deterministic, bounded PPR over the seed-reachable subgraph."""
    bounded_seeds = {seed for seed in seeds if seed in adjacency}
    nodes = _bounded_reachable(adjacency, bounded_seeds, max(1, int(max_nodes)))
    if not nodes or not bounded_seeds:
        return PPRResult({}, converged=True, iterations=0, degraded=False)
    alpha = max(0.0, min(float(alpha), 0.99))
    personalization = {
        node: (1.0 / len(bounded_seeds) if node in bounded_seeds else 0.0) for node in nodes
    }
    scores = dict(personalization)
    converged = False
    iterations = 0
    for iteration in range(1, max(1, int(max_iterations)) + 1):
        updated = {node: (1.0 - alpha) * personalization[node] for node in nodes}
        dangling_mass = 0.0
        for node in nodes:
            neighbors = {
                neighbor: max(0.0, float(weight))
                for neighbor, weight in adjacency.get(node, {}).items()
                if neighbor in updated and isfinite(float(weight)) and float(weight) > 0
            }
            total = sum(neighbors.values())
            if total <= 0:
                dangling_mass += scores.get(node, 0.0)
                continue
            for neighbor, weight in neighbors.items():
                updated[neighbor] += alpha * scores.get(node, 0.0) * weight / total
        if dangling_mass:
            for node in nodes:
                updated[node] += alpha * dangling_mass * personalization[node]
        total_score = sum(updated.values())
        if total_score > 0:
            updated = {node: max(0.0, score / total_score) for node, score in updated.items()}
        delta = sum(abs(updated[node] - scores.get(node, 0.0)) for node in nodes)
        scores = updated
        iterations = iteration
        if delta <= max(0.0, float(tolerance)):
            converged = True
            break
    return PPRResult(
        scores=scores,
        converged=converged,
        iterations=iterations,
        degraded=not converged,
    )


def bounded_shortest_paths(
    adjacency: dict[str, dict[str, float]],
    seeds: set[str],
    *,
    max_depth: int = 3,
    max_paths: int = 8,
) -> list[list[str]]:
    """Return deterministic short paths connecting seed pairs."""
    ordered_seeds = sorted(seed for seed in seeds if seed in adjacency)
    paths: list[list[str]] = []
    for index, start in enumerate(ordered_seeds):
        for target in ordered_seeds[index + 1 :]:
            queue = deque([[start]])
            visited_depth = {start: 0}
            found: list[str] | None = None
            while queue:
                path = queue.popleft()
                node = path[-1]
                depth = len(path) - 1
                if depth >= max(0, int(max_depth)):
                    continue
                for neighbor in sorted(adjacency.get(node, {})):
                    if neighbor not in adjacency or neighbor in path:
                        continue
                    candidate = [*path, neighbor]
                    if neighbor == target:
                        found = candidate
                        queue.clear()
                        break
                    next_depth = depth + 1
                    if visited_depth.get(neighbor, next_depth + 1) < next_depth:
                        continue
                    visited_depth[neighbor] = next_depth
                    queue.append(candidate)
            if found is not None:
                paths.append(found)
                if len(paths) >= max(1, int(max_paths)):
                    return paths
    return paths
