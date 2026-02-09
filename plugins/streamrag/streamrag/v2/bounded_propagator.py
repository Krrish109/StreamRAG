"""Bounded propagator: priority-based ripple with sync/async phases."""

import heapq
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from streamrag.graph import LiquidGraph


@dataclass
class PropagatorConfig:
    max_sync_updates: int = 5
    max_async_updates: int = 50
    max_depth: int = 3
    sync_timeout_ms: float = 50.0
    open_file_boost: float = 100.0
    recent_edit_boost: float = 50.0
    test_file_penalty: float = 30.0
    depth_penalty: float = 20.0


@dataclass(order=True)
class PendingPropagation:
    """A pending propagation item in the priority queue."""
    priority: float
    file_path: str = field(compare=False)
    depth: int = field(compare=False, default=0)
    source_file: str = field(compare=False, default="")


class PropagationResult:
    """Result of a propagation pass."""

    def __init__(self) -> None:
        self.sync_processed: List[str] = []
        self.async_queued: List[str] = []
        self.deferred: List[str] = []
        self.total_affected: int = 0
        self.sync_time_ms: float = 0.0


class BoundedPropagator:
    """Priority-based change propagation with bounded processing.

    Propagation phases:
    1. Find affected files via BFS on cross-file edges (depth-limited)
    2. Prioritize all affected files
    3. Phase 1 SYNC: process top files up to max_sync_updates or sync_timeout_ms
    4. Phase 2 ASYNC: queue next batch up to max_async_updates (heapq)
    5. Everything else: DEFERRED

    Priority formula (lower = higher priority):
        priority = depth * depth_penalty
                 - open_file_boost (if open)
                 - recent_edit_boost (if edited in last 5 min)
                 + test_file_penalty (if 'test' in path)
                 + 50 (if 'generated' or 'build' in path)
    """

    def __init__(
        self,
        graph: Optional[LiquidGraph] = None,
        config: Optional[PropagatorConfig] = None,
    ) -> None:
        self.graph = graph or LiquidGraph()
        self.config = config or PropagatorConfig()
        self._async_queue: List[PendingPropagation] = []
        self._open_files: Set[str] = set()
        self._recent_edits: Dict[str, float] = {}  # file_path -> timestamp

    def set_open_files(self, files: Set[str]) -> None:
        """Update the set of currently open files."""
        self._open_files = set(files)

    def record_edit(self, file_path: str) -> None:
        """Record that a file was recently edited."""
        self._recent_edits[file_path] = time.monotonic()

    def compute_priority(self, file_path: str, depth: int) -> float:
        """Compute update priority for a file (lower = higher priority)."""
        priority = depth * self.config.depth_penalty

        if file_path in self._open_files:
            priority -= self.config.open_file_boost

        # Check if edited in last 5 minutes
        edit_time = self._recent_edits.get(file_path)
        if edit_time and (time.monotonic() - edit_time) < 300:
            priority -= self.config.recent_edit_boost

        path_lower = file_path.lower()
        if "test" in path_lower:
            priority += self.config.test_file_penalty

        if "generated" in path_lower or "build" in path_lower:
            priority += 50.0

        return priority

    def find_affected_files(
        self, changed_file: str, graph: Optional[LiquidGraph] = None
    ) -> List[Tuple[str, int]]:
        """Find affected files via BFS on cross-file edges (depth-limited).

        Returns list of (file_path, depth) tuples.
        """
        g = graph or self.graph
        affected: List[Tuple[str, int]] = []
        visited: Set[str] = {changed_file}
        queue: deque = deque([(changed_file, 0)])

        while queue:
            current_file, depth = queue.popleft()
            if depth >= self.config.max_depth:
                continue

            nodes = g.get_nodes_by_file(current_file)
            for node in nodes:
                for edge in self.graph.get_incoming_edges(node.id):
                    source = g.get_node(edge.source_id)
                    if source and source.file_path not in visited:
                        visited.add(source.file_path)
                        affected.append((source.file_path, depth + 1))
                        queue.append((source.file_path, depth + 1))

        return affected

    def propagate(
        self,
        changed_file: str,
        update_fn: Optional[Callable[[str], None]] = None,
        graph: Optional[LiquidGraph] = None,
    ) -> PropagationResult:
        """Execute bounded propagation.

        Args:
            changed_file: The file that changed
            update_fn: Callback to process a file update
            graph: Optional graph override
        """
        result = PropagationResult()

        # 1. Find affected files
        affected = self.find_affected_files(changed_file, graph)
        result.total_affected = len(affected)

        if not affected:
            return result

        # 2. Prioritize
        prioritized = [
            PendingPropagation(
                priority=self.compute_priority(fp, depth),
                file_path=fp,
                depth=depth,
                source_file=changed_file,
            )
            for fp, depth in affected
        ]
        prioritized.sort(key=lambda p: p.priority)

        # 3. Phase 1: SYNC
        sync_start = time.perf_counter()
        sync_count = 0
        idx = 0

        for idx, item in enumerate(prioritized):
            if sync_count >= self.config.max_sync_updates:
                break
            elapsed_ms = (time.perf_counter() - sync_start) * 1000
            if elapsed_ms >= self.config.sync_timeout_ms:
                break

            if update_fn:
                update_fn(item.file_path)
            result.sync_processed.append(item.file_path)
            sync_count += 1

        result.sync_time_ms = (time.perf_counter() - sync_start) * 1000
        remaining = prioritized[sync_count:]

        # 4. Phase 2: ASYNC
        async_items = remaining[:self.config.max_async_updates]
        for item in async_items:
            heapq.heappush(self._async_queue, item)
            result.async_queued.append(item.file_path)

        # 5. Phase 3: DEFERRED
        deferred_items = remaining[self.config.max_async_updates:]
        for item in deferred_items:
            result.deferred.append(item.file_path)

        return result

    def process_async_queue(
        self,
        max_items: int = 10,
        update_fn: Optional[Callable[[str], None]] = None,
    ) -> List[str]:
        """Process items from the async queue."""
        processed: List[str] = []
        for _ in range(min(max_items, len(self._async_queue))):
            if not self._async_queue:
                break
            item = heapq.heappop(self._async_queue)
            if update_fn:
                update_fn(item.file_path)
            processed.append(item.file_path)
        return processed

    @property
    def async_queue_size(self) -> int:
        return len(self._async_queue)

    def clear_async_queue(self) -> None:
        self._async_queue = []
