"""Tests for query_graph.py script functions."""

import sys
import os

# Add parent to path so script can import streamrag
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from scripts.query_graph import (
    _resolve_name, cmd_callers, cmd_callees, cmd_deps, cmd_rdeps,
    cmd_file, cmd_entity, cmd_impact, cmd_dead, cmd_path,
    cmd_search, cmd_cycles, cmd_exports,
)


def _make_bridge():
    """Create a bridge with a small multi-file graph."""
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("models.py", "", (
        "class User:\n"
        "    pass\n\n"
        "class Response:\n"
        "    pass\n"
    )))
    bridge.process_change(CodeChange("service.py", "", (
        "from models import User\n\n"
        "def get_user(uid):\n"
        "    return User()\n\n"
        "def delete_user(uid):\n"
        "    get_user(uid)\n"
    )))
    bridge.process_change(CodeChange("api.py", "", (
        "from service import get_user\n\n"
        "def handle_request():\n"
        "    get_user(1)\n"
    )))
    return bridge


def test_resolve_name_exact():
    bridge = _make_bridge()
    nodes = _resolve_name(bridge, "User")
    assert len(nodes) >= 1
    assert any(n.name == "User" for n in nodes)


def test_resolve_name_suffix():
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("test.py", "", (
        "class Foo:\n"
        "    def bar(self):\n"
        "        pass\n"
    )))
    nodes = _resolve_name(bridge, "bar")
    assert len(nodes) >= 1
    assert any(n.name == "Foo.bar" for n in nodes)


def test_resolve_name_regex():
    bridge = _make_bridge()
    nodes = _resolve_name(bridge, "get_.*")
    assert len(nodes) >= 1


def test_resolve_name_not_found():
    bridge = _make_bridge()
    nodes = _resolve_name(bridge, "nonexistent_xyz_123")
    assert len(nodes) == 0


def test_cmd_callers(capsys):
    bridge = _make_bridge()
    cmd_callers(bridge, ["get_user"])
    captured = capsys.readouterr()
    assert "Callers of" in captured.out


def test_cmd_callees(capsys):
    bridge = _make_bridge()
    cmd_callees(bridge, ["delete_user"])
    captured = capsys.readouterr()
    assert "Callees of" in captured.out


def test_cmd_deps(capsys):
    bridge = _make_bridge()
    cmd_deps(bridge, ["service.py"])
    captured = capsys.readouterr()
    assert "Forward dependencies" in captured.out


def test_cmd_rdeps(capsys):
    bridge = _make_bridge()
    cmd_rdeps(bridge, ["models.py"])
    captured = capsys.readouterr()
    assert "Reverse dependencies" in captured.out


def test_cmd_file(capsys):
    bridge = _make_bridge()
    cmd_file(bridge, ["service.py"])
    captured = capsys.readouterr()
    assert "Entities in service.py" in captured.out


def test_cmd_entity(capsys):
    bridge = _make_bridge()
    cmd_entity(bridge, ["User"])
    captured = capsys.readouterr()
    assert "Name:" in captured.out
    assert "User" in captured.out


def test_cmd_impact(capsys):
    bridge = _make_bridge()
    cmd_impact(bridge, ["models.py"])
    captured = capsys.readouterr()
    assert "Files affected" in captured.out


def test_cmd_dead(capsys):
    bridge = _make_bridge()
    cmd_dead(bridge, [])
    captured = capsys.readouterr()
    assert "dead code" in captured.out.lower()


def test_cmd_path(capsys):
    bridge = _make_bridge()
    cmd_path(bridge, ["handle_request", "User"])
    captured = capsys.readouterr()
    # Either finds a path or says none found
    assert "Path from" in captured.out or "No path" in captured.out


def test_cmd_search(capsys):
    bridge = _make_bridge()
    cmd_search(bridge, ["get_.*"])
    captured = capsys.readouterr()
    assert "get_user" in captured.out


def test_cmd_cycles(capsys):
    bridge = _make_bridge()
    cmd_cycles(bridge, [])
    captured = capsys.readouterr()
    assert "Circular file dependencies" in captured.out


def test_cmd_exports(capsys):
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("mymod.py", "", (
        '__all__ = ["foo", "bar"]\n\n'
        "def foo():\n"
        "    pass\n\n"
        "def bar():\n"
        "    pass\n\n"
        "def _private():\n"
        "    pass\n"
    )))
    cmd_exports(bridge, ["mymod.py"])
    captured = capsys.readouterr()
    assert "foo" in captured.out
    assert "bar" in captured.out


def test_cmd_exports_no_all(capsys):
    bridge = DeltaGraphBridge()
    bridge.process_change(CodeChange("mymod.py", "", (
        "def public_func():\n"
        "    pass\n\n"
        "def _private():\n"
        "    pass\n"
    )))
    cmd_exports(bridge, ["mymod.py"])
    captured = capsys.readouterr()
    assert "public_func" in captured.out
