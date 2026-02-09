"""Hierarchical graph with HOT/WARM/COLD zones for prioritized updates."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from streamrag.graph import LiquidGraph
from streamrag.models import GraphNode


class Zone(Enum):
    HOT = "HOT"    # Open files, sync updates, <10ms target
    WARM = "WARM"  # Transitive deps / recent files, async queue
    COLD = "COLD"  # Everything else, lazy/on-demand


@dataclass
class HierarchicalGraphConfig:
    max_hot_files: int = 10
    max_warm_files: int = 50
    warm_delay_ms: float = 100.0
    cold_stale_seconds: float = 300.0


@dataclass
class FileState:
    """Tracks the state of a file in the hierarchical graph."""
    file_path: str
    zone: Zone = Zone.COLD
    is_open: bool = False
    last_access: float = 0.0
    last_update: float = 0.0
    priority: float = 100.0


class HierarchicalGraph:
    """Graph with zone-based caching for open/recent/cold files.

    Zone transitions:
    - File opened -> promote to HOT, deps promoted to WARM
    - File closed -> demote to WARM (not COLD, in case reopened)
    - HOT limit exceeded -> oldest non-open file demoted to WARM

    Update priority (lower=higher):
    - Base 100
    - -50 if open
    - -30 if accessed <60s ago
    - +20 if test file
    """

    def __init__(
        self,
        graph: Optional[LiquidGraph] = None,
        config: Optional[HierarchicalGraphConfig] = None,
    ) -> None:
        self.graph = graph or LiquidGraph()
        self.config = config or HierarchicalGraphConfig()
        self._file_states: Dict[str, FileState] = {}
        self._hot_files: Set[str] = set()
        self._warm_files: Set[str] = set()
        self._cold_files: Set[str] = set()

    def _ensure_file_state(self, file_path: str) -> FileState:
        if file_path not in self._file_states:
            state = FileState(file_path=file_path, last_access=time.monotonic())
            self._file_states[file_path] = state
            self._cold_files.add(file_path)
        return self._file_states[file_path]

    def open_file(self, file_path: str) -> None:
        """Mark a file as opened -> promote to HOT zone."""
        state = self._ensure_file_state(file_path)
        state.is_open = True
        state.last_access = time.monotonic()
        self._promote_to_zone(file_path, Zone.HOT)

        # Promote dependencies to WARM
        nodes = self.graph.get_nodes_by_file(file_path)
        for node in nodes:
            for edge in self.graph.get_outgoing_edges(node.id):
                target = self.graph.get_node(edge.target_id)
                if target and target.file_path != file_path:
                    dep_state = self._ensure_file_state(target.file_path)
                    if dep_state.zone == Zone.COLD:
                        self._promote_to_zone(target.file_path, Zone.WARM)

        # Check HOT eviction
        self._evict_hot_if_needed()

    def close_file(self, file_path: str) -> None:
        """Mark a file as closed -> demote to WARM (not COLD)."""
        state = self._ensure_file_state(file_path)
        state.is_open = False
        self._promote_to_zone(file_path, Zone.WARM)

    def access_file(self, file_path: str) -> None:
        """Record a file access (read/edit without open)."""
        state = self._ensure_file_state(file_path)
        state.last_access = time.monotonic()

    def get_zone(self, file_path: str) -> Zone:
        """Get the current zone of a file."""
        state = self._file_states.get(file_path)
        return state.zone if state else Zone.COLD

    def get_update_priority(self, file_path: str) -> float:
        """Calculate update priority (lower = higher priority)."""
        state = self._ensure_file_state(file_path)
        priority = 100.0

        if state.is_open:
            priority -= 50.0

        elapsed = time.monotonic() - state.last_access
        if elapsed < 60.0:
            priority -= 30.0

        if "test" in file_path.lower():
            priority += 20.0

        return priority

    def get_files_by_zone(self, zone: Zone) -> Set[str]:
        """Get all files in a zone."""
        if zone == Zone.HOT:
            return set(self._hot_files)
        elif zone == Zone.WARM:
            return set(self._warm_files)
        return set(self._cold_files)

    def _promote_to_zone(self, file_path: str, zone: Zone) -> None:
        """Move a file to a specific zone."""
        # Remove from current zone
        self._hot_files.discard(file_path)
        self._warm_files.discard(file_path)
        self._cold_files.discard(file_path)

        # Add to new zone
        if zone == Zone.HOT:
            self._hot_files.add(file_path)
        elif zone == Zone.WARM:
            self._warm_files.add(file_path)
        else:
            self._cold_files.add(file_path)

        self._file_states[file_path].zone = zone

    def _evict_hot_if_needed(self) -> None:
        """Evict oldest non-open file from HOT if limit exceeded."""
        while len(self._hot_files) > self.config.max_hot_files:
            # Find oldest non-open file
            candidates = [
                fp for fp in self._hot_files
                if not self._file_states[fp].is_open
            ]
            if not candidates:
                break

            oldest = min(candidates, key=lambda fp: self._file_states[fp].last_access)
            self._promote_to_zone(oldest, Zone.WARM)

    def get_stats(self) -> Dict:
        return {
            "hot_files": len(self._hot_files),
            "warm_files": len(self._warm_files),
            "cold_files": len(self._cold_files),
            "total_files": len(self._file_states),
        }
