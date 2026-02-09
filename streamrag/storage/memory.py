"""In-memory graph serialization for hook state persistence."""

import hashlib
import json
import os
import time
from typing import Optional

from streamrag.bridge import DeltaGraphBridge
from streamrag.graph import LiquidGraph
from streamrag.models import GraphEdge, GraphNode

CURRENT_FORMAT_VERSION = 3


def serialize_graph(bridge: DeltaGraphBridge) -> dict:
    """Serialize a DeltaGraphBridge to a JSON-safe dict."""
    nodes = []
    for node in bridge.graph._nodes.values():
        nodes.append({
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "file_path": node.file_path,
            "line_start": node.line_start,
            "line_end": node.line_end,
            "properties": node.properties,
        })

    edges = []
    for edge_list in bridge.graph._outgoing_edges.values():
        for edge in edge_list:
            edges.append({
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "edge_type": edge.edge_type,
                "properties": edge.properties,
            })

    result = {
        "format_version": CURRENT_FORMAT_VERSION,
        "nodes": nodes,
        "edges": edges,
        "file_contents_keys": list(bridge._tracked_files),
        "dependency_index": {k: list(v) for k, v in bridge._dependency_index.items()},
        "module_file_index": bridge._module_file_index,
        "module_file_collisions": list(bridge._module_file_collisions),
        "resolution_stats": bridge._resolution_stats,
    }

    # Versioned graph state (if enabled)
    if bridge._versioned:
        result["graph_version"] = bridge._versioned.version
        result["version_vector"] = bridge._versioned._version_vector

    return result


def deserialize_graph(data: dict) -> DeltaGraphBridge:
    """Deserialize a dict into a DeltaGraphBridge.

    Raises ValueError if format_version is newer than supported.
    """
    version = data.get("format_version", 1)
    if version > CURRENT_FORMAT_VERSION:
        raise ValueError(
            f"State file format v{version} is newer than supported "
            f"v{CURRENT_FORMAT_VERSION}. Please update StreamRAG."
        )
    graph = LiquidGraph()

    for nd in data.get("nodes", []):
        graph.add_node(GraphNode(
            id=nd["id"],
            type=nd["type"],
            name=nd["name"],
            file_path=nd["file_path"],
            line_start=nd["line_start"],
            line_end=nd["line_end"],
            properties=nd.get("properties", {}),
        ))

    for ed in data.get("edges", []):
        graph.add_edge(GraphEdge(
            source_id=ed["source_id"],
            target_id=ed["target_id"],
            edge_type=ed["edge_type"],
            properties=ed.get("properties", {}),
        ))

    bridge = DeltaGraphBridge(graph=graph)
    # Backward compat: old format stored full file contents, new format stores only keys
    if "file_contents_keys" in data:
        bridge._file_contents = {}
        bridge._tracked_files = set(data.get("file_contents_keys", []))
    elif "file_contents" in data:
        bridge._file_contents = data["file_contents"]
        bridge._tracked_files = set(bridge._file_contents.keys())
    else:
        bridge._file_contents = {}
        bridge._tracked_files = set()

    dep_idx = data.get("dependency_index", {})
    for k, v in dep_idx.items():
        bridge._dependency_index[k] = set(v)

    bridge._module_file_index = data.get("module_file_index", {})
    bridge._module_file_collisions = set(data.get("module_file_collisions", []))

    stats = data.get("resolution_stats", {})
    bridge._resolution_stats = {
        "total_attempted": stats.get("total_attempted", 0),
        "resolved": stats.get("resolved", 0),
        "ambiguous": stats.get("ambiguous", 0),
        "to_test_file": stats.get("to_test_file", 0),
        "external_skipped": stats.get("external_skipped", 0),
    }

    # Restore versioned graph state (if present in data)
    graph_version = data.get("graph_version")
    version_vector = data.get("version_vector")
    if graph_version is not None:
        from streamrag.v2.versioned_graph import VersionedGraph
        bridge._versioned = VersionedGraph(bridge.graph)
        bridge._versioned._version = graph_version
        if version_vector:
            bridge._versioned._version_vector = version_vector

    return bridge


def save_state(bridge: DeltaGraphBridge, session_id: str) -> str:
    """Save graph state to ~/.claude/streamrag_graph_{session_id}.json."""
    state_dir = os.path.expanduser("~/.claude")
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, f"streamrag_graph_{session_id}.json")

    data = serialize_graph(bridge)
    with open(state_file, "w") as f:
        json.dump(data, f)

    return state_file


def load_state(session_id: str) -> Optional[DeltaGraphBridge]:
    """Load graph state from ~/.claude/streamrag_graph_{session_id}.json."""
    state_file = os.path.expanduser(f"~/.claude/streamrag_graph_{session_id}.json")
    if not os.path.exists(state_file):
        return None

    try:
        with open(state_file, "r") as f:
            data = json.load(f)
        return deserialize_graph(data)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IOError) as exc:
        import sys as _sys
        print(f"StreamRAG: corrupt state {state_file}, removing ({type(exc).__name__})",
              file=_sys.stderr)
        try:
            os.remove(state_file)
        except OSError:
            pass
        return None


# --- Project-level persistence (cross-session) ---


def _get_project_id(project_path: str) -> str:
    """Generate a stable project ID from the absolute project path."""
    return hashlib.sha256(os.path.abspath(project_path).encode()).hexdigest()[:12]


def _get_project_state_path(project_path: str) -> str:
    """Get the state file path for a project."""
    state_dir = os.path.expanduser("~/.claude/streamrag")
    project_id = _get_project_id(project_path)
    return os.path.join(state_dir, f"graph_{project_id}.json")


def save_project_state(bridge: DeltaGraphBridge, project_path: str) -> str:
    """Save graph state keyed by project path (persists across sessions)."""
    state_file = _get_project_state_path(project_path)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)

    data = serialize_graph(bridge)
    data["project_path"] = os.path.abspath(project_path)
    data["saved_at"] = time.time()

    with open(state_file, "w") as f:
        json.dump(data, f)

    return state_file


def load_project_state(project_path: str) -> Optional[DeltaGraphBridge]:
    """Load graph state by project path."""
    state_file = _get_project_state_path(project_path)

    if not os.path.exists(state_file):
        return None

    try:
        with open(state_file, "r") as f:
            data = json.load(f)
        return deserialize_graph(data)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IOError) as exc:
        import sys as _sys
        print(f"StreamRAG: corrupt project state {state_file}, removing ({type(exc).__name__})",
              file=_sys.stderr)
        try:
            os.remove(state_file)
        except OSError:
            pass
        return None


def is_state_stale(project_path: str, max_age_hours: float = 24.0) -> bool:
    """Check if the project state file is too old to be useful.

    Uses file mtime instead of parsing JSON for speed.
    """
    state_file = _get_project_state_path(project_path)
    if not os.path.exists(state_file):
        return True
    try:
        mtime = os.path.getmtime(state_file)
        return (time.time() - mtime) > (max_age_hours * 3600)
    except OSError:
        return True
