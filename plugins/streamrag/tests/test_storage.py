"""Tests for persistent storage."""

import json
import os
import tempfile
import time

import pytest

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from streamrag.storage.memory import (
    CURRENT_FORMAT_VERSION,
    _get_project_id,
    deserialize_graph,
    is_state_stale,
    load_project_state,
    load_state,
    save_project_state,
    serialize_graph,
)


def test_project_state_round_trip():
    """Save and load project state preserves graph data."""
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("a.py", "", "def foo():\n    pass\n"))

    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch state dir for test isolation
        project_path = tmpdir
        state_file = save_project_state(bridge, project_path)
        assert os.path.exists(state_file)

        loaded = load_project_state(project_path)
        assert loaded is not None
        assert loaded.graph.node_count == bridge.graph.node_count


def test_project_id_deterministic():
    """Same path always produces same project ID."""
    id1 = _get_project_id("/some/path")
    id2 = _get_project_id("/some/path")
    assert id1 == id2
    assert len(id1) == 12


def test_project_id_differs_for_different_paths():
    id1 = _get_project_id("/path/a")
    id2 = _get_project_id("/path/b")
    assert id1 != id2


def test_load_missing_project_returns_none():
    """Loading a nonexistent project returns None."""
    result = load_project_state("/nonexistent/path/that/does/not/exist")
    assert result is None


def test_staleness_check():
    """State file with very old mtime is stale."""
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("a.py", "", "def foo():\n    pass\n"))

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = tmpdir
        state_file = save_project_state(bridge, project_path)

        # Not stale immediately
        assert is_state_stale(project_path, max_age_hours=1.0) is False

        # Set file mtime to ~28 hours ago
        old_time = time.time() - 100000
        os.utime(state_file, (old_time, old_time))

        assert is_state_stale(project_path, max_age_hours=24.0) is True


def test_staleness_missing_file():
    """Missing state file is considered stale."""
    assert is_state_stale("/nonexistent/path", max_age_hours=1.0) is True


# --- Format version validation tests ---


def test_deserialize_rejects_future_format_version():
    """Deserialization raises ValueError for unsupported future format versions."""
    data = {"format_version": 999, "nodes": [], "edges": []}
    with pytest.raises(ValueError, match="newer than supported"):
        deserialize_graph(data)


def test_deserialize_accepts_current_version():
    """Deserialization works with current format version."""
    data = {"format_version": CURRENT_FORMAT_VERSION, "nodes": [], "edges": []}
    bridge = deserialize_graph(data)
    assert bridge.graph.node_count == 0


def test_deserialize_accepts_missing_version():
    """Old state files without format_version are accepted (assumed v1)."""
    data = {"nodes": [], "edges": []}
    bridge = deserialize_graph(data)
    assert bridge.graph.node_count == 0


# --- Corrupt state file cleanup tests ---


def test_corrupt_project_state_file_removed():
    """Corrupt project state file is deleted on load attempt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_id = _get_project_id(tmpdir)
        state_dir = os.path.expanduser("~/.claude/streamrag")
        os.makedirs(state_dir, exist_ok=True)
        state_file = os.path.join(state_dir, f"graph_{project_id}.json")

        try:
            with open(state_file, "w") as f:
                f.write("CORRUPT {{{{ DATA")

            result = load_project_state(tmpdir)
            assert result is None
            assert not os.path.exists(state_file)
        finally:
            if os.path.exists(state_file):
                os.remove(state_file)


def test_corrupt_session_state_file_removed():
    """Corrupt session state file is deleted on load attempt."""
    state_dir = os.path.expanduser("~/.claude")
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, "streamrag_graph_test_corrupt.json")

    try:
        with open(state_file, "w") as f:
            f.write("NOT JSON")

        result = load_state("test_corrupt")
        assert result is None
        assert not os.path.exists(state_file)
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)
