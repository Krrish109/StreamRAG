"""StreamRAG Daemon: persistent asyncio server keeping DeltaGraphBridge in memory.

Eliminates per-hook process spawn + JSON deserialization overhead by serving
all hook requests over a Unix domain socket.

Protocol: newline-delimited JSON requests/responses.
Socket: ~/.claude/streamrag/daemon_{project_hash}.sock
PID: ~/.claude/streamrag/daemon_{project_hash}.pid
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Set

# Ensure plugin root is on path
_PLUGIN_ROOT = os.environ.get(
    "CLAUDE_PLUGIN_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
_parent = os.path.dirname(_PLUGIN_ROOT)
if _parent not in sys.path:
    sys.path.insert(0, _parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange, SUPPORTED_EXTENSIONS
from streamrag.storage.memory import (
    load_project_state,
    save_project_state,
    is_state_stale,
    serialize_graph,
    deserialize_graph,
)
from streamrag.languages.registry import create_default_registry

logger = logging.getLogger("streamrag.daemon")

SAVE_INTERVAL_S = 60.0
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    "target", "out", "bin", "obj",
}


def _get_state_dir() -> str:
    d = os.path.expanduser("~/.claude/streamrag")
    os.makedirs(d, exist_ok=True)
    return d


def _project_hash(project_path: str) -> str:
    return hashlib.sha256(os.path.abspath(project_path).encode()).hexdigest()[:12]


def get_socket_path(project_path: str) -> str:
    return os.path.join(_get_state_dir(), f"daemon_{_project_hash(project_path)}.sock")


def get_pid_path(project_path: str) -> str:
    return os.path.join(_get_state_dir(), f"daemon_{_project_hash(project_path)}.pid")


class StreamRAGDaemon:
    """Single-process daemon keeping DeltaGraphBridge in memory."""

    def __init__(self, project_path: str) -> None:
        self.project_path = os.path.abspath(project_path)
        self.bridge: Optional[DeltaGraphBridge] = None
        self.registry = create_default_registry()
        self._dirty = False
        self._initialized = False
        self._save_task: Optional[asyncio.Task] = None
        self._server: Optional[asyncio.AbstractServer] = None
        self._cleanup_counter = 0

    # ---- lifecycle --------------------------------------------------------

    def _load_or_create_bridge(self) -> DeltaGraphBridge:
        """Load existing state or create fresh bridge."""
        bridge = None
        if not is_state_stale(self.project_path):
            bridge = load_project_state(self.project_path)
        if bridge is None:
            bridge = DeltaGraphBridge()

        # Enable versioned graph
        if bridge._versioned is None:
            try:
                from streamrag.v2.versioned_graph import VersionedGraph
                bridge._versioned = VersionedGraph(bridge.graph)
            except ImportError:
                pass

        # Enable hierarchical graph + propagator
        try:
            from streamrag.v2.hierarchical_graph import HierarchicalGraph
            from streamrag.v2.bounded_propagator import BoundedPropagator
            if bridge._hierarchical is None:
                bridge._hierarchical = HierarchicalGraph(graph=bridge.graph)
            if bridge._propagator is None:
                bridge._propagator = BoundedPropagator(graph=bridge.graph)
        except ImportError:
            pass

        return bridge

    def _ensure_bridge(self) -> DeltaGraphBridge:
        """Get or lazily create the bridge."""
        if self.bridge is None:
            self.bridge = self._load_or_create_bridge()
        return self.bridge

    def _maybe_auto_init(self, max_files: int = 200, timeout_s: float = 7.0) -> None:
        """Auto-initialize graph from project directory (idempotent)."""
        if self._initialized:
            return

        bridge = self._ensure_bridge()
        tracked = bridge._tracked_files or set(bridge._file_contents.keys())

        # Skip if already populated
        if len(tracked) >= max_files and bridge.graph.node_count > 0:
            self._initialized = True
            return

        if not os.path.isdir(self.project_path):
            self._initialized = True
            return

        supported_count = 0
        new_count = 0
        start = time.time()

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
            for fname in files:
                if not self.registry.can_handle(fname):
                    continue
                supported_count += 1
                if supported_count > max_files:
                    break
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, self.project_path)
                if rel_path in tracked:
                    continue
                if time.time() - start > timeout_s:
                    break
                try:
                    with open(fpath, "r") as f:
                        content = f.read()
                except (IOError, UnicodeDecodeError):
                    continue
                change = CodeChange(file_path=rel_path, old_content="", new_content=content)
                bridge.process_change(change)
                new_count += 1
            else:
                continue
            break

        if new_count > 0:
            self._dirty = True

        self._initialized = True

    def _cleanup_deleted_files(self) -> None:
        """Remove nodes for files that no longer exist on disk (every 10th call)."""
        self._cleanup_counter += 1
        if self._cleanup_counter % 10 != 1:
            return

        bridge = self._ensure_bridge()
        tracked = bridge._tracked_files or set(bridge._file_contents.keys())
        for file_path in list(tracked):
            check_path = file_path
            if not os.path.isabs(file_path):
                check_path = os.path.join(self.project_path, file_path)
            if not os.path.exists(check_path):
                bridge.remove_file(file_path)
                self._dirty = True

    def _save_if_dirty(self) -> None:
        """Save project state if dirty."""
        if self._dirty and self.bridge is not None:
            try:
                save_project_state(self.bridge, self.project_path)
                self._dirty = False
            except Exception as e:
                logger.warning("Failed to save state: %s", e)

    async def _periodic_save_loop(self) -> None:
        """Save state every SAVE_INTERVAL_S if dirty."""
        while True:
            await asyncio.sleep(SAVE_INTERVAL_S)
            self._save_if_dirty()

    # ---- RPC handlers -----------------------------------------------------

    def handle_ping(self, _req: dict) -> dict:
        bridge = self._ensure_bridge()
        return {
            "alive": True,
            "nodes": bridge.graph.node_count,
            "edges": bridge.graph.edge_count,
        }

    def handle_shutdown(self, _req: dict) -> dict:
        self._save_if_dirty()
        # Schedule server stop
        if self._server:
            self._server.close()
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(loop.stop)
        except RuntimeError:
            pass  # No running loop (unit test context)
        return {"ok": True}

    def handle_process_change(self, req: dict) -> dict:
        """Process a file change (Edit/Write/MultiEdit)."""
        file_path = req.get("file_path", "")
        abs_file_path = req.get("abs_file_path", "") or file_path
        project_path = req.get("project_path", self.project_path)

        if not file_path:
            return {}

        # Check if supported
        if not self.registry.can_handle(file_path):
            return {}

        bridge = self._ensure_bridge()

        # Normalize to relative path
        if os.path.isabs(file_path) and project_path:
            try:
                rel = os.path.relpath(file_path, project_path)
                if not rel.startswith(".."):
                    file_path = rel
            except ValueError:
                pass

        # Auto-init on first change
        self._maybe_auto_init()

        # Cleanup deleted files periodically
        self._cleanup_deleted_files()

        # Get old content from cache
        old_content = bridge._file_contents.get(file_path, "")

        # Read new content from disk
        read_path = abs_file_path if os.path.isabs(abs_file_path) else os.path.join(self.project_path, file_path)
        try:
            with open(read_path, "r") as f:
                new_content = f.read()
        except (IOError, OSError):
            return {}

        change = CodeChange(
            file_path=file_path,
            old_content=old_content,
            new_content=new_content,
        )
        ops = bridge.process_change(change)
        self._dirty = True

        if not ops:
            return {}

        # Build minimal summary
        real_ops = [op for op in ops if op.node_type != "propagation"]
        msg = f"StreamRAG: {len(real_ops)} ops"

        # Surface breaking changes
        breaking = []
        for op in ops:
            if op.op_type == "remove_node" and op.properties.get("had_callers"):
                callers = op.properties["had_callers"]
                breaking.append(
                    f"{op.properties['name']} removed (used by {', '.join(callers[:3])})"
                )
        if breaking:
            msg += " | BREAKING: " + "; ".join(breaking)

        # Proactive intelligence (when enabled)
        if os.environ.get("STREAMRAG_PROACTIVE", ""):
            warnings = []
            t0 = time.time()
            try:
                cycles = bridge.check_new_cycles(file_path)
                if cycles:
                    warnings.append(f"Circular dep: {' -> '.join(cycles[0][:4])}")
                if time.time() - t0 < 3.0:
                    dead = bridge.check_new_dead_code(file_path)
                    new_adds = {op.properties.get("name") for op in ops if op.op_type == "add_node"}
                    new_dead = [n for n in dead if n.name in new_adds]
                    if new_dead:
                        warnings.append(f"New unused: {', '.join(n.name for n in new_dead[:3])}")
            except Exception:
                pass
            if warnings:
                msg += " | WARNINGS: " + "; ".join(warnings)

        return {"systemMessage": msg}

    def handle_get_read_context(self, req: dict) -> dict:
        """Get context for a file Read."""
        file_path = req.get("file_path", "")
        if not file_path:
            return {}

        if not any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            return {}

        bridge = self._ensure_bridge()
        self._maybe_auto_init()

        if bridge.graph.node_count == 0:
            return {
                "systemMessage": "[StreamRAG] No code graph yet. It will initialize on your first file edit."
            }

        # Find nodes in this file
        nodes = bridge.graph.get_nodes_by_file(file_path)
        if not nodes:
            for fp in set(n.file_path for n in bridge.graph._nodes.values()):
                if fp.endswith(file_path) or file_path.endswith(fp) or file_path in fp:
                    nodes = bridge.graph.get_nodes_by_file(fp)
                    file_path = fp
                    break

        if not nodes:
            return {}

        # Track access in hierarchical graph
        if bridge._hierarchical:
            bridge._hierarchical.access_file(file_path)

        budget = int(os.environ.get("STREAMRAG_CONTEXT_BUDGET", "1000"))
        try:
            from streamrag.agent.context_builder import get_context_for_file, format_rich_context
            context = get_context_for_file(bridge, file_path)
            msg = format_rich_context(context, max_chars=budget)
        except Exception:
            basename = os.path.basename(file_path)
            entity_count = len([n for n in nodes if n.type in ("function", "class")])
            msg = f"[StreamRAG] {basename}: {entity_count} entities"

        return {"systemMessage": msg}

    def handle_classify_query(self, req: dict) -> dict:
        """Classify and optionally execute a relationship query (Explore/Grep redirect)."""
        tool_name = req.get("tool_name", "")
        tool_input = req.get("tool_input", {})

        bridge = self._ensure_bridge()
        self._maybe_auto_init()

        if bridge.graph.node_count == 0:
            return {}

        if tool_name == "Task":
            return self._handle_task_classify(tool_input, bridge)
        elif tool_name == "Grep":
            return self._handle_grep_classify(tool_input, bridge)
        return {}

    def _handle_task_classify(self, tool_input: dict, bridge: DeltaGraphBridge) -> dict:
        """Handle Task/Explore classification."""
        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type.lower() != "explore":
            return {}

        prompt = tool_input.get("prompt", "")
        description = tool_input.get("description", "")
        if not prompt and not description:
            return {}

        from streamrag.classify import classify_explore_prompt, build_command_str

        result = classify_explore_prompt(prompt) if prompt else None
        if result is None and description:
            result = classify_explore_prompt(description)
        if result is None:
            return {}

        command, args = result
        output = self._execute_command(bridge, command, args)
        if output:
            return {"systemMessage": f"[StreamRAG] Graph context:\n{output}"}

        cmd_str = build_command_str(command, args)
        return {
            "systemMessage": f"[StreamRAG] This query can be answered from the code graph.\nRun: {cmd_str}",
        }

    def _handle_grep_classify(self, tool_input: dict, bridge: DeltaGraphBridge) -> dict:
        """Handle Grep classification."""
        pattern = tool_input.get("pattern", "")
        if not pattern:
            return {}

        from streamrag.classify import classify_grep_pattern, build_command_str, command_description

        result = classify_grep_pattern(pattern)
        if result is None:
            return {}

        command, name = result
        output = self._execute_command(bridge, command, [name])
        if output:
            return {"systemMessage": f"[StreamRAG] Graph context:\n{output}"}

        cmd_str = build_command_str(command, [name])
        desc = command_description(command)
        return {"systemMessage": f"[StreamRAG Hint] Looking for {desc} `{name}`? Try:\n  {cmd_str}"}

    def handle_classify_user_prompt(self, req: dict) -> dict:
        """Classify user prompt and return relevant graph context."""
        user_prompt = req.get("user_prompt", "")
        if not user_prompt or len(user_prompt) < 5:
            return {}

        bridge = self._ensure_bridge()
        self._maybe_auto_init()

        if bridge.graph.node_count == 0:
            return {}

        # Try classifying as a relationship query
        from streamrag.classify import classify_explore_prompt
        result = classify_explore_prompt(user_prompt)
        if result is not None:
            command, args = result
            output = self._execute_command(bridge, command, args)
            if output:
                # Truncate for prompt context (500 chars max)
                if len(output) > 500:
                    output = output[:500] + "\n... (truncated)"
                return {"systemMessage": f"[StreamRAG] Relevant graph context:\n{output}"}

        # Scan for entity/file mentions in the prompt
        import re
        tokens = re.split(r'[\s,;:?!`\'"()\[\]{}]+', user_prompt)
        words = set()
        for token in tokens:
            token = token.strip('./')
            if len(token) >= 2:
                words.add(token)

        matches = []
        for word in words:
            node = bridge.graph.get_node_by_name(word)
            if node:
                incoming = bridge.graph.get_incoming_edges(node.id)
                cross_callers = []
                for e in incoming:
                    src = bridge.graph.get_node(e.source_id)
                    if src and src.file_path != node.file_path:
                        cross_callers.append(f"{os.path.basename(src.file_path)}:{src.name}")

                affected = bridge.get_affected_files(node.file_path, node.name)

                info = f"{node.name} ({node.type}, {os.path.basename(node.file_path)} L{node.line_start}-{node.line_end})"
                if cross_callers:
                    info += f" -- called by: {', '.join(cross_callers[:3])}"
                if affected:
                    aff_names = sorted(set(os.path.basename(f) for f in affected))[:4]
                    info += f" -- affects: {', '.join(aff_names)}"
                matches.append(info)

        # Check for file path mentions
        tracked_files = set()
        for node in bridge.graph.get_all_nodes():
            tracked_files.add(node.file_path)

        for word in words:
            for fp in tracked_files:
                if word in fp and word not in [m.split(' ')[0] for m in matches]:
                    affected = set()
                    for node in bridge.graph.get_nodes_by_file(fp):
                        for f in bridge.get_affected_files(fp, node.name):
                            affected.add(f)
                    if affected:
                        aff_names = sorted(set(os.path.basename(f) for f in affected))[:4]
                        matches.append(f"{fp} -- affects: {', '.join(aff_names)}")
                    else:
                        matches.append(fp)
                    break

        matches = matches[:5]
        if matches:
            lines = ["[StreamRAG] Relevant graph context:"]
            for m in matches:
                lines.append(f"  {m}")
            return {"systemMessage": "\n".join(lines)}

        return {}

    def handle_get_compact_summary(self, req: dict) -> dict:
        """Get compact summary for context preservation (pre_compact)."""
        bridge = self._ensure_bridge()

        if bridge.graph.node_count == 0:
            return {}

        files: Set[str] = set()
        all_nodes = bridge.graph.get_all_nodes()
        for node in all_nodes:
            files.add(node.file_path)

        entity_counts: Dict[str, int] = {}
        for node in all_nodes:
            entity_counts[node.type] = entity_counts.get(node.type, 0) + 1

        lines = [
            f"StreamRAG Code Graph: {bridge.graph.node_count} entities, "
            f"{bridge.graph.edge_count} edges across {len(files)} files.",
        ]
        for etype, count in sorted(entity_counts.items()):
            lines.append(f"  {etype}: {count}")

        cross_file = []
        for edge in bridge.graph.get_all_edges():
            src = bridge.graph.get_node(edge.source_id)
            tgt = bridge.graph.get_node(edge.target_id)
            if src and tgt and src.file_path != tgt.file_path:
                cross_file.append(f"{src.file_path}:{src.name} -> {tgt.file_path}:{tgt.name}")

        if cross_file:
            lines.append(f"Cross-file deps ({len(cross_file)}):")
            for dep in cross_file[:10]:
                lines.append(f"  {dep}")

        return {"systemMessage": "\n".join(lines)}

    def _execute_command(self, bridge: DeltaGraphBridge, command: str, args: list) -> Optional[str]:
        """Execute a StreamRAG query command, return output string or None."""
        scripts_dir = os.path.join(_PLUGIN_ROOT, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from io import StringIO
        import contextlib

        try:
            if "query_graph" in sys.modules:
                qg = sys.modules["query_graph"]
            else:
                import query_graph as qg

            cmd_fn = qg.COMMANDS.get(command)
            if cmd_fn is None:
                return None

            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_fn(bridge, args)

            output = buf.getvalue().strip()
            if not output:
                return None
            if len(output) > 2000:
                output = output[:2000] + "\n... (truncated)"
            return output
        except Exception:
            return None

    # ---- dispatch ---------------------------------------------------------

    HANDLERS = {
        "ping": "handle_ping",
        "shutdown": "handle_shutdown",
        "process_change": "handle_process_change",
        "get_read_context": "handle_get_read_context",
        "classify_query": "handle_classify_query",
        "classify_user_prompt": "handle_classify_user_prompt",
        "get_compact_summary": "handle_get_compact_summary",
    }

    def dispatch(self, request: dict) -> dict:
        cmd = request.get("cmd", "")
        handler_name = self.HANDLERS.get(cmd)
        if handler_name is None:
            return {"error": f"Unknown command: {cmd}"}
        handler = getattr(self, handler_name)
        try:
            return handler(request)
        except Exception as e:
            logger.exception("Error handling %s", cmd)
            return {"error": str(e)}

    # ---- server -----------------------------------------------------------

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single client connection."""
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not data:
                return

            request = json.loads(data.decode())
            response = self.dispatch(request)
            response_bytes = json.dumps(response).encode() + b"\n"
            writer.write(response_bytes)
            await writer.drain()
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            try:
                err = json.dumps({"error": str(e)}).encode() + b"\n"
                writer.write(err)
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def run(self) -> None:
        """Start the daemon server."""
        sock_path = get_socket_path(self.project_path)
        pid_path = get_pid_path(self.project_path)

        # Clean up stale socket
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        # Write PID
        with open(pid_path, "w") as f:
            f.write(str(os.getpid()))

        # Pre-load bridge
        self._ensure_bridge()
        self._maybe_auto_init()

        self._server = await asyncio.start_unix_server(self._handle_client, path=sock_path)
        self._save_task = asyncio.create_task(self._periodic_save_loop())

        logger.info("Daemon started: pid=%d socket=%s nodes=%d edges=%d",
                     os.getpid(), sock_path,
                     self.bridge.graph.node_count if self.bridge else 0,
                     self.bridge.graph.edge_count if self.bridge else 0)

        # Handle signals for clean shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self._shutdown()))

        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup(sock_path, pid_path)

    async def _shutdown(self) -> None:
        """Graceful shutdown."""
        self._save_if_dirty()
        if self._server:
            self._server.close()

    async def _cleanup(self, sock_path: str, pid_path: str) -> None:
        """Clean up socket and PID files."""
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass

        self._save_if_dirty()

        for path in (sock_path, pid_path):
            try:
                os.unlink(path)
            except OSError:
                pass

        logger.info("Daemon stopped")


def main() -> None:
    """Entry point: python3 -m streamrag.daemon --project-path <path>"""
    import argparse

    parser = argparse.ArgumentParser(description="StreamRAG daemon server")
    parser.add_argument("--project-path", required=True, help="Project root directory")
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    daemon = StreamRAGDaemon(args.project_path)
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
