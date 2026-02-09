"""Fine-grained graph operations with inverse support and atomic batches."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from streamrag.graph import LiquidGraph
from streamrag.models import GraphEdge, GraphNode


class GraphOp(ABC):
    """Base class for all graph operations."""

    @abstractmethod
    def apply(self, graph: LiquidGraph) -> bool:
        """Apply this operation to the graph. Returns True on success."""
        ...

    @abstractmethod
    def inverse(self) -> "GraphOp":
        """Return the inverse operation that undoes this one."""
        ...


@dataclass
class AddNode(GraphOp):
    """Add a node to the graph."""
    node: GraphNode
    edges: List[GraphEdge] = field(default_factory=list)

    def apply(self, graph: LiquidGraph) -> bool:
        if graph.get_node(self.node.id) is not None:
            return False
        graph.add_node(self.node)
        for edge in self.edges:
            graph.add_edge(edge)
        return True

    def inverse(self) -> "RemoveNode":
        return RemoveNode(node_id=self.node.id, _captured_node=self.node, _captured_edges=list(self.edges))


@dataclass
class RemoveNode(GraphOp):
    """Remove a node and its edges from the graph."""
    node_id: str
    _captured_node: Optional[GraphNode] = field(default=None, repr=False)
    _captured_edges: List[GraphEdge] = field(default_factory=list, repr=False)

    def apply(self, graph: LiquidGraph) -> bool:
        node = graph.get_node(self.node_id)
        if node is None:
            return False
        # Capture state before removal for inverse
        self._captured_node = GraphNode(
            id=node.id, type=node.type, name=node.name,
            file_path=node.file_path, line_start=node.line_start,
            line_end=node.line_end, properties=dict(node.properties),
        )
        self._captured_edges = list(graph.get_outgoing_edges(self.node_id))
        graph.remove_node(self.node_id)
        return True

    def inverse(self) -> AddNode:
        if self._captured_node is None:
            return AddNode(node=GraphNode(id=self.node_id, type="", name="",
                                          file_path="", line_start=0, line_end=0))
        return AddNode(node=self._captured_node, edges=self._captured_edges)


@dataclass
class UpdateNode(GraphOp):
    """Update properties of an existing node."""
    node_id: str
    updates: Dict[str, Any] = field(default_factory=dict)
    _previous_values: Dict[str, Any] = field(default_factory=dict, repr=False)

    def apply(self, graph: LiquidGraph) -> bool:
        node = graph.get_node(self.node_id)
        if node is None:
            return False
        self._previous_values = {}
        for key, value in self.updates.items():
            self._previous_values[key] = node.properties.get(key)
            node.properties[key] = value
        return True

    def inverse(self) -> "UpdateNode":
        return UpdateNode(
            node_id=self.node_id,
            updates=dict(self._previous_values),
            _previous_values=dict(self.updates),
        )


@dataclass
class RenameNode(GraphOp):
    """Rename a node. Node ID stays the same, edges preserved."""
    node_id: str
    old_name: str
    new_name: str

    def apply(self, graph: LiquidGraph) -> bool:
        node = graph.get_node(self.node_id)
        if node is None:
            return False

        # Update _nodes_by_name index directly
        old_set = graph._nodes_by_name.get(self.old_name)
        if old_set:
            old_set.discard(self.node_id)
            if not old_set:
                del graph._nodes_by_name[self.old_name]

        graph._nodes_by_name[self.new_name].add(self.node_id)
        node.name = self.new_name
        node.properties["renamed_from"] = self.old_name
        return True

    def inverse(self) -> "RenameNode":
        return RenameNode(node_id=self.node_id, old_name=self.new_name, new_name=self.old_name)


@dataclass
class MoveNode(GraphOp):
    """Move a node to a different file/location."""
    node_id: str
    old_file_path: str
    new_file_path: str
    old_line_start: int = 0
    new_line_start: int = 0
    old_line_end: int = 0
    new_line_end: int = 0

    def apply(self, graph: LiquidGraph) -> bool:
        node = graph.get_node(self.node_id)
        if node is None:
            return False

        # Update _nodes_by_file index
        old_set = graph._nodes_by_file.get(self.old_file_path)
        if old_set:
            old_set.discard(self.node_id)
            if not old_set:
                del graph._nodes_by_file[self.old_file_path]

        graph._nodes_by_file[self.new_file_path].add(self.node_id)
        node.file_path = self.new_file_path
        node.line_start = self.new_line_start
        node.line_end = self.new_line_end
        return True

    def inverse(self) -> "MoveNode":
        return MoveNode(
            node_id=self.node_id,
            old_file_path=self.new_file_path, new_file_path=self.old_file_path,
            old_line_start=self.new_line_start, new_line_start=self.old_line_start,
            old_line_end=self.new_line_end, new_line_end=self.old_line_end,
        )


@dataclass
class AddEdge(GraphOp):
    """Add an edge to the graph."""
    edge: GraphEdge

    def apply(self, graph: LiquidGraph) -> bool:
        graph.add_edge(self.edge)
        return True

    def inverse(self) -> "RemoveEdge":
        return RemoveEdge(
            source_id=self.edge.source_id,
            target_id=self.edge.target_id,
            edge_type=self.edge.edge_type,
        )


@dataclass
class RemoveEdge(GraphOp):
    """Remove an edge from the graph."""
    source_id: str
    target_id: str
    edge_type: str
    _captured_edge: Optional[GraphEdge] = field(default=None, repr=False)

    def apply(self, graph: LiquidGraph) -> bool:
        removed = graph.remove_edge(self.source_id, self.target_id, self.edge_type)
        if removed:
            self._captured_edge = removed
            return True
        return False

    def inverse(self) -> AddEdge:
        if self._captured_edge:
            return AddEdge(edge=self._captured_edge)
        return AddEdge(edge=GraphEdge(
            source_id=self.source_id, target_id=self.target_id,
            edge_type=self.edge_type,
        ))


@dataclass
class RetargetEdge(GraphOp):
    """Change the target of an existing edge."""
    source_id: str
    old_target_id: str
    new_target_id: str
    edge_type: str

    def apply(self, graph: LiquidGraph) -> bool:
        removed = graph.remove_edge(self.source_id, self.old_target_id, self.edge_type)
        if removed is None:
            return False
        graph.add_edge(GraphEdge(
            source_id=self.source_id, target_id=self.new_target_id,
            edge_type=self.edge_type, properties=removed.properties,
        ))
        return True

    def inverse(self) -> "RetargetEdge":
        return RetargetEdge(
            source_id=self.source_id,
            old_target_id=self.new_target_id,
            new_target_id=self.old_target_id,
            edge_type=self.edge_type,
        )


@dataclass
class SetNodeProperty(GraphOp):
    """Set a single property on a node."""
    node_id: str
    key: str
    new_value: Any
    _old_value: Any = field(default=None, repr=False)

    def apply(self, graph: LiquidGraph) -> bool:
        node = graph.get_node(self.node_id)
        if node is None:
            return False
        self._old_value = node.properties.get(self.key)
        node.properties[self.key] = self.new_value
        return True

    def inverse(self) -> "SetNodeProperty":
        return SetNodeProperty(
            node_id=self.node_id, key=self.key,
            new_value=self._old_value, _old_value=self.new_value,
        )


class OperationBatch:
    """Atomic transaction: applies all ops or rolls back on failure."""

    def __init__(self, operations: List[GraphOp]) -> None:
        self.operations = operations
        self._applied: List[GraphOp] = []

    def apply(self, graph: LiquidGraph) -> bool:
        """Apply all operations. Rolls back if any fail."""
        self._applied = []
        for op in self.operations:
            if op.apply(graph):
                self._applied.append(op)
            else:
                self.rollback(graph)
                return False
        return True

    def rollback(self, graph: LiquidGraph) -> None:
        """Roll back applied operations via their inverses (best-effort)."""
        for op in reversed(self._applied):
            try:
                op.inverse().apply(graph)
            except Exception:
                pass  # Best-effort rollback
        self._applied = []
