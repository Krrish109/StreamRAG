"""Synchronous client for the StreamRAG daemon.

Used by hook scripts to send requests to the persistent daemon instead of
loading the graph from disk on every invocation.
"""

import json
import os
import socket
import subprocess
import sys
import time
from typing import Optional

from streamrag.daemon import get_socket_path, get_pid_path


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _is_daemon_alive(project_path: str) -> bool:
    """Check if the daemon is running (PID file + process check)."""
    pid_path = get_pid_path(project_path)
    if not os.path.exists(pid_path):
        return False
    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())
        return _is_process_alive(pid)
    except (ValueError, IOError):
        return False


def _cleanup_stale(project_path: str) -> None:
    """Remove stale PID and socket files if daemon is dead."""
    pid_path = get_pid_path(project_path)
    sock_path = get_socket_path(project_path)
    for path in (pid_path, sock_path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _start_daemon(project_path: str) -> bool:
    """Start the daemon as a detached subprocess. Wait up to 2s for socket."""
    # Find the daemon module
    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    parent_dir = os.path.dirname(plugin_root)

    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    # Ensure both plugin root and parent are discoverable
    pythonpath = env.get("PYTHONPATH", "")
    paths = [parent_dir, plugin_root]
    for p in pythonpath.split(os.pathsep):
        if p and p not in paths:
            paths.append(p)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    try:
        subprocess.Popen(
            [sys.executable, "-m", "streamrag.daemon", "--project-path", project_path],
            cwd=parent_dir,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False

    # Wait for socket to appear
    sock_path = get_socket_path(project_path)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if os.path.exists(sock_path):
            return True
        time.sleep(0.05)

    return os.path.exists(sock_path)


def ensure_daemon(project_path: str) -> bool:
    """Ensure the daemon is running. Start it if not. Returns True if alive."""
    if _is_daemon_alive(project_path):
        return True

    # Clean up stale files
    _cleanup_stale(project_path)

    return _start_daemon(project_path)


def send_request(
    project_path: str,
    request: dict,
    timeout: float = 2.0,
    connect_timeout: float = 0.5,
) -> Optional[dict]:
    """Send a JSON request to the daemon and return the response.

    Returns None if the daemon is unreachable or times out.
    """
    sock_path = get_socket_path(project_path)
    if not os.path.exists(sock_path):
        return None

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(connect_timeout)
        sock.connect(sock_path)

        # Send request
        data = json.dumps(request).encode() + b"\n"
        sock.sendall(data)

        # Read response
        sock.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk

        if not buf:
            return None

        line = buf.split(b"\n", 1)[0]
        return json.loads(line.decode())
    except (socket.error, socket.timeout, json.JSONDecodeError, ConnectionRefusedError, OSError):
        return None
    finally:
        sock.close()


def start_session(project_path: str, timeout: float = 2.0) -> Optional[dict]:
    """Start an AI session via the daemon. Returns {session_id, base_version} or None."""
    return send_request(project_path, {"cmd": "start_session"}, timeout=timeout)


def complete_session(
    project_path: str,
    session_id: str,
    proposed_changes: Optional[list] = None,
    timeout: float = 2.0,
) -> Optional[dict]:
    """Complete an AI session. Returns {status, drift, can_apply, conflicts} or None."""
    req = {"cmd": "complete_session", "session_id": session_id}
    if proposed_changes:
        req["proposed_changes"] = proposed_changes
    return send_request(project_path, req, timeout=timeout)
