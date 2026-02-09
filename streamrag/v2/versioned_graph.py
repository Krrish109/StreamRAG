"""Versioned graph with conflict detection and AI session management."""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from streamrag.graph import LiquidGraph
from streamrag.models import GraphOperation


class ConflictType(Enum):
    DELETION = "DELETION"           # Entity was deleted since base version
    RENAME = "RENAME"               # Entity was renamed since base version
    CONCURRENT_EDIT = "CONCURRENT_EDIT"  # Same entity edited by both sides


class ConflictSeverity(Enum):
    ERROR = "error"     # Cannot auto-resolve
    WARNING = "warning"  # Can potentially auto-resolve


@dataclass
class Conflict:
    """A conflict detected between versions."""
    conflict_type: ConflictType
    severity: ConflictSeverity
    node_id: str
    description: str
    existing_op: Optional[GraphOperation] = None
    proposed_op: Optional[GraphOperation] = None


@dataclass
class SessionResult:
    """Result of completing an AI session."""
    status: str  # 'clean' | 'clean_with_drift' | 'conflicts'
    drift: int = 0
    conflicts: List[Conflict] = field(default_factory=list)
    can_apply: bool = True


@dataclass
class AISession:
    """An active AI session with captured state."""
    session_id: str
    base_version: int
    snapshot: LiquidGraph
    created_at: float
    completed: bool = False


class VersionedGraph:
    """Thread-safe graph with version tracking and conflict detection.

    Tracks:
    - Global monotonic version counter
    - Per-file version vector
    - Operation log (capped at max_log_size)
    """

    def __init__(self, graph: Optional[LiquidGraph] = None, max_log_size: int = 1000) -> None:
        self.graph = graph or LiquidGraph()
        self._lock = threading.Lock()
        self._version: int = 0
        self._version_vector: Dict[str, int] = {}
        self._operation_log: List[Tuple[int, float, GraphOperation]] = []
        self._max_log_size = max_log_size

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def record_operation(self, op: GraphOperation, file_path: str = "") -> int:
        """Record an operation and increment version."""
        with self._lock:
            self._version += 1
            version = self._version
            self._operation_log.append((version, time.time(), op))

            if file_path:
                self._version_vector[file_path] = version

            # Trim log if needed
            if len(self._operation_log) > self._max_log_size:
                excess = len(self._operation_log) - self._max_log_size
                self._operation_log = self._operation_log[excess:]

            return version

    def get_operations_since(self, base_version: int) -> List[Tuple[int, float, GraphOperation]]:
        """Get all operations since a base version."""
        with self._lock:
            return [
                (v, t, op) for v, t, op in self._operation_log
                if v > base_version
            ]

    def get_file_version(self, file_path: str) -> int:
        """Get the latest version for a file."""
        with self._lock:
            return self._version_vector.get(file_path, 0)

    def detect_conflicts(
        self,
        base_version: int,
        proposed_changes: List[GraphOperation],
    ) -> List[Conflict]:
        """Detect conflicts between existing operations and proposed changes."""
        conflicts: List[Conflict] = []

        recent_ops = self.get_operations_since(base_version)
        if not recent_ops:
            return conflicts

        # Index existing operations by node_id
        ops_by_node: Dict[str, List[GraphOperation]] = {}
        for _, _, op in recent_ops:
            ops_by_node.setdefault(op.node_id, []).append(op)

        for proposed in proposed_changes:
            existing_ops = ops_by_node.get(proposed.node_id, [])
            for existing in existing_ops:
                # Check for deletion conflict
                if existing.op_type == "remove_node":
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.DELETION,
                        severity=ConflictSeverity.ERROR,
                        node_id=proposed.node_id,
                        description=f"Node {proposed.node_id} was deleted since base version",
                        existing_op=existing,
                        proposed_op=proposed,
                    ))

                # Check for rename conflict
                elif existing.properties.get("renamed_from"):
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.RENAME,
                        severity=ConflictSeverity.WARNING,
                        node_id=proposed.node_id,
                        description=f"Node {proposed.node_id} was renamed from {existing.properties['renamed_from']}",
                        existing_op=existing,
                        proposed_op=proposed,
                    ))

                # Check for concurrent edit
                elif existing.op_type == "update_node" and proposed.op_type == "update_node":
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.CONCURRENT_EDIT,
                        severity=ConflictSeverity.WARNING,
                        node_id=proposed.node_id,
                        description=f"Node {proposed.node_id} was concurrently edited",
                        existing_op=existing,
                        proposed_op=proposed,
                    ))

            # Check if proposed op references a renamed entity's old_name
            for _, _, op in recent_ops:
                old_name = op.properties.get("renamed_from")
                if old_name and old_name in str(proposed.properties.get("calls", [])):
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.RENAME,
                        severity=ConflictSeverity.WARNING,
                        node_id=proposed.node_id,
                        description=f"Proposed change references renamed entity '{old_name}'",
                        existing_op=op,
                        proposed_op=proposed,
                    ))

        return conflicts

    def resolve_rename_conflicts(
        self,
        proposed_changes: List[GraphOperation],
        renames: Dict[str, str],  # old_name -> new_name
    ) -> List[GraphOperation]:
        """Resolve rename conflicts by replacing old names with new names."""
        resolved = []
        for op in proposed_changes:
            new_op = GraphOperation(
                op_type=op.op_type,
                node_id=op.node_id,
                node_type=op.node_type,
                properties=dict(op.properties),
                edges=list(op.edges),
            )
            # Replace in calls
            calls = new_op.properties.get("calls", [])
            if calls:
                new_op.properties["calls"] = [
                    renames.get(c, c) for c in calls
                ]
            # Replace in uses
            uses = new_op.properties.get("uses", [])
            if uses:
                new_op.properties["uses"] = [
                    renames.get(u, u) for u in uses
                ]
            resolved.append(new_op)
        return resolved

    def resolve_deletion_conflicts(
        self,
        proposed_changes: List[GraphOperation],
        deleted_node_ids: Set[str],
    ) -> List[GraphOperation]:
        """Filter out operations targeting deleted nodes."""
        return [op for op in proposed_changes if op.node_id not in deleted_node_ids]


class AISessionManager:
    """Manages AI sessions with version tracking.

    start_session() -> captures version + graph snapshot
    complete_session() -> checks for drift, detects conflicts
    """

    def __init__(
        self,
        versioned_graph: VersionedGraph,
        max_age_seconds: float = 300.0,
        max_active: int = 10,
    ) -> None:
        self._vg = versioned_graph
        self._sessions: Dict[str, AISession] = {}
        self._max_age = max_age_seconds
        self._max_active = max_active
        self._next_id: int = 0

    def start_session(self) -> AISession:
        """Start a new AI session capturing current state."""
        self._cleanup_stale()
        session_id = f"session_{self._next_id}"
        self._next_id += 1

        session = AISession(
            session_id=session_id,
            base_version=self._vg.version,
            snapshot=self._vg.graph.snapshot(),
            created_at=time.time(),
        )
        self._sessions[session_id] = session
        return session

    def complete_session(
        self,
        session_id: str,
        proposed_changes: Optional[List[GraphOperation]] = None,
    ) -> SessionResult:
        """Complete a session and check for conflicts."""
        session = self._sessions.get(session_id)
        if session is None:
            return SessionResult(status="error", can_apply=False)

        session.completed = True
        drift = self._vg.version - session.base_version

        if drift == 0:
            return SessionResult(status="clean", drift=0)

        if not proposed_changes:
            return SessionResult(status="clean_with_drift", drift=drift)

        conflicts = self._vg.detect_conflicts(session.base_version, proposed_changes)
        if conflicts:
            return SessionResult(
                status="conflicts", drift=drift,
                conflicts=conflicts, can_apply=False,
            )

        return SessionResult(status="clean_with_drift", drift=drift)

    def get_session(self, session_id: str) -> Optional[AISession]:
        return self._sessions.get(session_id)

    def _cleanup_stale(self) -> None:
        """Remove expired sessions and enforce max_active limit."""
        now = time.time()
        # Remove old sessions
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.created_at > self._max_age or s.completed
        ]
        for sid in expired:
            del self._sessions[sid]

        # Enforce max active
        while len(self._sessions) >= self._max_active:
            oldest = min(self._sessions.values(), key=lambda s: s.created_at)
            del self._sessions[oldest.session_id]
