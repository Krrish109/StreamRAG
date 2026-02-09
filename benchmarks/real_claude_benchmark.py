#!/usr/bin/env python3
"""
Real Benchmark: Claude Code WITH vs WITHOUT StreamRAG
=====================================================

Runs identical prompts through Claude Code in two modes:
  1. Baseline  — plain `claude -p` (no plugin)
  2. StreamRAG — `claude -p --plugin-dir <streamrag>`

Each prompt gets its OWN fresh session (--no-session-persistence).

Measures:
  - Wall-clock time (seconds)
  - API time (duration_api_ms)
  - Turns / tool calls (num_turns)
  - Token usage (input, output, cache read/write)
  - Cost ($USD)
  - Response length (chars)

Saves:
  - Per-prompt raw JSON artifacts
  - Per-prompt stderr logs
  - Final comparison_report.md
  - Final comparison_results.json

Usage:
    python3 benchmarks/real_claude_benchmark.py [project_dir]

    Default project: /Users/krrish/Incredible/Incredible-API
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Configuration ──────────────────────────────────────────────────

if len(sys.argv) < 2:
    print("Usage: real_claude_benchmark.py <project_dir>")
    sys.exit(1)
PROJECT_DIR = sys.argv[1]
PLUGIN_DIR = str(Path(__file__).resolve().parent.parent)  # plugins/streamrag
RESULTS_BASE = Path(__file__).resolve().parent / "results"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULT_DIR = RESULTS_BASE / TIMESTAMP

STREAMRAG_PREFIX = (
    "You have access to a pre-built code dependency graph for this project via StreamRAG. "
    "BEFORE using grep or glob to explore code relationships, use these Bash commands:\n\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <name>   # Who calls this?\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees <name>   # What does this call?\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps <file>     # What depends on this file?\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file> [name]  # Impact analysis\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file <file>      # All entities in a file\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py summary          # Architecture overview\n"
    "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path <src> <dst> # Dependency chain\n\n"
    "Use these graph queries as your primary source for dependency, caller, and impact information. "
    "Supplement with grep/read only to verify details or look at actual code.\n\n"
)

# ── Prompts ────────────────────────────────────────────────────────
# Designed to test dependency-awareness, cross-file tracing, and
# architectural understanding — exactly what a code graph helps with.

PROMPTS = [
    {
        "name": "dependency_analysis",
        "prompt": (
            "What functions call the validate function in api/auth/auth_service.py? "
            "List every caller across all files with the exact file path and function name. "
            "Be precise — don't guess."
        ),
    },
    {
        "name": "impact_analysis",
        "prompt": (
            "If I change the credit_check function in api/utils/credit_check.py, "
            "what other files and functions would be affected? "
            "Show the full dependency chain."
        ),
    },
    {
        "name": "architecture_question",
        "prompt": (
            "Explain the architecture of the agentic_model module. "
            "How do the files in api/agentic_model/ connect to each other? "
            "Which file is the entry point, what calls what, and how does data "
            "flow through the system?"
        ),
    },
    {
        "name": "cross_file_trace",
        "prompt": (
            "Trace the full call chain when a user hits the chat completion endpoint. "
            "Start from api/server.py, go through the route handler, into the service "
            "layer, and down to the LLM provider call. "
            "List each function and file in order."
        ),
    },
    {
        "name": "refactor_risk",
        "prompt": (
            "What would be the safest way to refactor api/utils/credits.py? "
            "What depends on it, and what's the risk of breaking other modules?"
        ),
    },
]


# ── Data Classes ───────────────────────────────────────────────────

@dataclass
class RunMetrics:
    """Metrics from a single Claude Code run."""
    mode: str                  # "baseline" or "streamrag"
    prompt_name: str
    prompt_text: str
    wall_time_s: float = 0.0
    api_time_ms: float = 0.0
    num_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    response_length: int = 0
    response_text: str = ""
    models_used: List[str] = field(default_factory=list)
    model_costs: Dict[str, float] = field(default_factory=dict)
    model_tokens: Dict[str, Dict[str, int]] = field(default_factory=dict)
    session_id: str = ""
    success: bool = False
    error: str = ""
    stderr: str = ""
    raw_json: Dict[str, Any] = field(default_factory=dict)


# ── Core Runner ────────────────────────────────────────────────────

def run_claude(prompt: str, prompt_name: str, mode: str) -> RunMetrics:
    """Run a single Claude Code invocation and collect all metrics."""
    metrics = RunMetrics(mode=mode, prompt_name=prompt_name, prompt_text=prompt)

    # IMPORTANT: --plugin-dir is variadic (<paths...>), so the prompt
    # MUST come before it, or be passed via stdin.  We use stdin to be safe.
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--no-session-persistence",
    ]
    if mode == "streamrag":
        cmd.extend(["--plugin-dir", PLUGIN_DIR])
        prompt = STREAMRAG_PREFIX + prompt

    # Save the command for debugging
    cmd_file = RESULT_DIR / f"{prompt_name}_{mode}.cmd"
    cmd_file.write_text(" ".join(cmd) + f"\n\n# Prompt passed via stdin:\n{prompt}")

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,            # pass prompt via stdin
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout per prompt
            cwd=PROJECT_DIR,
        )
        metrics.wall_time_s = round(time.time() - start, 2)

        # Save stderr separately (plugin/debug output goes here)
        stderr_file = RESULT_DIR / f"{prompt_name}_{mode}.stderr"
        stderr_file.write_text(proc.stderr or "")
        metrics.stderr = proc.stderr or ""

        # Save raw stdout
        raw_file = RESULT_DIR / f"{prompt_name}_{mode}.raw.json"
        raw_file.write_text(proc.stdout or "")

        if proc.returncode != 0 and not proc.stdout.strip():
            metrics.error = f"Exit code {proc.returncode}: {proc.stderr[:500]}"
            return metrics

        # Parse JSON output
        if proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            metrics.raw_json = data
            metrics.success = data.get("type") == "result" and not data.get("is_error")

            # Core metrics
            metrics.api_time_ms = data.get("duration_api_ms", 0)
            metrics.num_turns = data.get("num_turns", 0)
            metrics.cost_usd = data.get("total_cost_usd", 0)
            metrics.session_id = data.get("session_id", "")
            metrics.response_text = data.get("result", "")
            metrics.response_length = len(metrics.response_text)

            # Token usage
            usage = data.get("usage", {})
            metrics.input_tokens = usage.get("input_tokens", 0)
            metrics.output_tokens = usage.get("output_tokens", 0)
            metrics.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            metrics.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            metrics.total_tokens = (
                metrics.input_tokens + metrics.output_tokens
                + metrics.cache_read_tokens + metrics.cache_write_tokens
            )

            # Per-model breakdown
            model_usage = data.get("modelUsage", {})
            for model_name, mu in model_usage.items():
                metrics.models_used.append(model_name)
                metrics.model_costs[model_name] = mu.get("costUSD", 0)
                metrics.model_tokens[model_name] = {
                    "input": mu.get("inputTokens", 0),
                    "output": mu.get("outputTokens", 0),
                    "cache_read": mu.get("cacheReadInputTokens", 0),
                    "cache_write": mu.get("cacheCreationInputTokens", 0),
                }
        else:
            metrics.error = "Empty stdout"

    except subprocess.TimeoutExpired:
        metrics.wall_time_s = 300.0
        metrics.error = "Timed out after 300s"
    except json.JSONDecodeError as e:
        metrics.wall_time_s = round(time.time() - start, 2)
        metrics.error = f"JSON parse error: {e}"
    except Exception as e:
        metrics.wall_time_s = round(time.time() - start, 2)
        metrics.error = f"Exception: {e}"

    return metrics


# ── Report Generation ──────────────────────────────────────────────

def generate_report(all_results: List[Dict[str, RunMetrics]]):
    """Generate markdown report + JSON artifacts."""

    # ── Save per-prompt artifacts ──
    for pair in all_results:
        for mode in ("baseline", "streamrag"):
            m = pair[mode]
            artifact = RESULT_DIR / f"{m.prompt_name}_{mode}.artifact.json"
            # Save a clean version (no raw_json to keep it small)
            save_data = asdict(m)
            save_data.pop("raw_json", None)
            save_data.pop("response_text", None)  # kept in .raw.json
            artifact.write_text(json.dumps(save_data, indent=2))

    # ── Build summary data ──
    summary_rows = []
    for pair in all_results:
        b = pair["baseline"]
        s = pair["streamrag"]
        speedup = round(b.wall_time_s / s.wall_time_s, 1) if s.wall_time_s > 0 else 0
        token_saving = round(
            (1 - s.total_tokens / b.total_tokens) * 100, 1
        ) if b.total_tokens > 0 else 0
        cost_saving = round(
            (1 - s.cost_usd / b.cost_usd) * 100, 1
        ) if b.cost_usd > 0 else 0
        turns_diff = b.num_turns - s.num_turns

        summary_rows.append({
            "name": b.prompt_name,
            "baseline_time": b.wall_time_s,
            "streamrag_time": s.wall_time_s,
            "speedup": speedup,
            "baseline_turns": b.num_turns,
            "streamrag_turns": s.num_turns,
            "turns_saved": turns_diff,
            "baseline_tokens": b.total_tokens,
            "streamrag_tokens": s.total_tokens,
            "token_saving_pct": token_saving,
            "baseline_cost": b.cost_usd,
            "streamrag_cost": s.cost_usd,
            "cost_saving_pct": cost_saving,
            "baseline_output_len": b.response_length,
            "streamrag_output_len": s.response_length,
            "baseline_success": b.success,
            "streamrag_success": s.success,
            "baseline_error": b.error,
            "streamrag_error": s.error,
        })

    # ── Save final results JSON ──
    final_json = RESULT_DIR / "comparison_results.json"
    final_data = {
        "timestamp": TIMESTAMP,
        "project": PROJECT_DIR,
        "plugin": PLUGIN_DIR,
        "tests": summary_rows,
        "totals": {
            "baseline_time": sum(r["baseline_time"] for r in summary_rows),
            "streamrag_time": sum(r["streamrag_time"] for r in summary_rows),
            "baseline_cost": sum(r["baseline_cost"] for r in summary_rows),
            "streamrag_cost": sum(r["streamrag_cost"] for r in summary_rows),
            "baseline_tokens": sum(r["baseline_tokens"] for r in summary_rows),
            "streamrag_tokens": sum(r["streamrag_tokens"] for r in summary_rows),
        },
    }
    t = final_data["totals"]
    t["overall_speedup"] = round(t["baseline_time"] / t["streamrag_time"], 1) if t["streamrag_time"] > 0 else 0
    t["overall_token_saving_pct"] = round(
        (1 - t["streamrag_tokens"] / t["baseline_tokens"]) * 100, 1
    ) if t["baseline_tokens"] > 0 else 0
    t["overall_cost_saving_pct"] = round(
        (1 - t["streamrag_cost"] / t["baseline_cost"]) * 100, 1
    ) if t["baseline_cost"] > 0 else 0

    final_json.write_text(json.dumps(final_data, indent=2))

    # ── Generate Markdown Report ──
    report = RESULT_DIR / "comparison_report.md"
    lines = []
    lines.append("# Claude Code Benchmark: WITH vs WITHOUT StreamRAG\n")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**Project:** `{PROJECT_DIR}`  ")
    lines.append(f"**Plugin:** `{PLUGIN_DIR}`\n")

    # Speed table
    lines.append("## Speed Comparison\n")
    lines.append("| Test | Baseline | StreamRAG | Speedup |")
    lines.append("|------|----------|-----------|---------|")
    for r in summary_rows:
        lines.append(
            f"| {r['name']} | {r['baseline_time']}s | {r['streamrag_time']}s | "
            f"**{r['speedup']}x** |"
        )
    lines.append(
        f"| **TOTAL** | **{t['baseline_time']:.1f}s** | **{t['streamrag_time']:.1f}s** | "
        f"**{t['overall_speedup']}x** |"
    )

    # Token usage table
    lines.append("\n## Token Usage\n")
    lines.append("| Test | Baseline Tokens | StreamRAG Tokens | Saved |")
    lines.append("|------|-----------------|------------------|-------|")
    for r in summary_rows:
        lines.append(
            f"| {r['name']} | {r['baseline_tokens']:,} | {r['streamrag_tokens']:,} | "
            f"{r['token_saving_pct']}% |"
        )
    lines.append(
        f"| **TOTAL** | **{t['baseline_tokens']:,}** | **{t['streamrag_tokens']:,}** | "
        f"**{t['overall_token_saving_pct']}%** |"
    )

    # Cost table
    lines.append("\n## Cost Comparison\n")
    lines.append("| Test | Baseline $ | StreamRAG $ | Saved |")
    lines.append("|------|------------|-------------|-------|")
    for r in summary_rows:
        lines.append(
            f"| {r['name']} | ${r['baseline_cost']:.4f} | ${r['streamrag_cost']:.4f} | "
            f"{r['cost_saving_pct']}% |"
        )
    lines.append(
        f"| **TOTAL** | **${t['baseline_cost']:.4f}** | **${t['streamrag_cost']:.4f}** | "
        f"**{t['overall_cost_saving_pct']}%** |"
    )

    # Turns / tool calls
    lines.append("\n## Turns (Tool Call Rounds)\n")
    lines.append("| Test | Baseline Turns | StreamRAG Turns | Saved |")
    lines.append("|------|----------------|-----------------|-------|")
    for r in summary_rows:
        lines.append(
            f"| {r['name']} | {r['baseline_turns']} | {r['streamrag_turns']} | "
            f"{r['turns_saved']} |"
        )

    # Response quality (length + snippet)
    lines.append("\n## Response Quality\n")
    lines.append("| Test | Baseline Len | StreamRAG Len | Baseline OK | StreamRAG OK |")
    lines.append("|------|-------------|---------------|-------------|--------------|")
    for r in summary_rows:
        lines.append(
            f"| {r['name']} | {r['baseline_output_len']:,} chars | "
            f"{r['streamrag_output_len']:,} chars | "
            f"{'✅' if r['baseline_success'] else '❌'} | "
            f"{'✅' if r['streamrag_success'] else '❌'} |"
        )

    # Errors if any
    errors_found = False
    for r in summary_rows:
        if r["baseline_error"] or r["streamrag_error"]:
            if not errors_found:
                lines.append("\n## Errors\n")
                errors_found = True
            if r["baseline_error"]:
                lines.append(f"- **{r['name']}** (baseline): {r['baseline_error']}")
            if r["streamrag_error"]:
                lines.append(f"- **{r['name']}** (streamrag): {r['streamrag_error']}")

    # Detailed responses
    lines.append("\n---\n")
    lines.append("## Detailed Responses\n")
    for i, pair in enumerate(all_results):
        b = pair["baseline"]
        s = pair["streamrag"]
        lines.append(f"### {i+1}. {b.prompt_name}\n")
        lines.append(f"**Prompt:** {b.prompt_text}\n")

        lines.append("#### Baseline (without StreamRAG)\n")
        lines.append(f"*{b.wall_time_s}s · {b.num_turns} turns · "
                     f"{b.total_tokens:,} tokens · ${b.cost_usd:.4f}*\n")
        resp_b = b.response_text[:3000] if b.response_text else "(empty)"
        lines.append(f"```\n{resp_b}\n```\n")

        lines.append("#### StreamRAG\n")
        lines.append(f"*{s.wall_time_s}s · {s.num_turns} turns · "
                     f"{s.total_tokens:,} tokens · ${s.cost_usd:.4f}*\n")
        resp_s = s.response_text[:3000] if s.response_text else "(empty)"
        lines.append(f"```\n{resp_s}\n```\n")

    report.write_text("\n".join(lines))
    return final_data


# ── Pretty Print ───────────────────────────────────────────────────

def print_table(final_data: dict):
    """Print results table to terminal."""
    rows = final_data["tests"]
    t = final_data["totals"]

    print()
    print("=" * 90)
    print("  BENCHMARK RESULTS: Claude Code WITH vs WITHOUT StreamRAG")
    print("=" * 90)
    print()

    # Speed
    print("  SPEED")
    print("  " + "-" * 70)
    print(f"  {'Test':<25} {'Baseline':>10} {'StreamRAG':>10} {'Speedup':>10}")
    print("  " + "-" * 70)
    for r in rows:
        tag = " ⚠" if not r["streamrag_success"] else ""
        print(f"  {r['name']:<25} {r['baseline_time']:>9.1f}s {r['streamrag_time']:>9.1f}s "
              f"{r['speedup']:>9.1f}x{tag}")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<25} {t['baseline_time']:>9.1f}s {t['streamrag_time']:>9.1f}s "
          f"{t['overall_speedup']:>9.1f}x")
    print()

    # Tokens
    print("  TOKENS")
    print("  " + "-" * 70)
    print(f"  {'Test':<25} {'Baseline':>12} {'StreamRAG':>12} {'Saved':>10}")
    print("  " + "-" * 70)
    for r in rows:
        print(f"  {r['name']:<25} {r['baseline_tokens']:>12,} {r['streamrag_tokens']:>12,} "
              f"{r['token_saving_pct']:>9.1f}%")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<25} {t['baseline_tokens']:>12,} {t['streamrag_tokens']:>12,} "
          f"{t['overall_token_saving_pct']:>9.1f}%")
    print()

    # Cost
    print("  COST")
    print("  " + "-" * 70)
    print(f"  {'Test':<25} {'Baseline':>10} {'StreamRAG':>10} {'Saved':>10}")
    print("  " + "-" * 70)
    for r in rows:
        print(f"  {r['name']:<25} ${r['baseline_cost']:>8.4f} ${r['streamrag_cost']:>8.4f} "
              f"{r['cost_saving_pct']:>9.1f}%")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<25} ${t['baseline_cost']:>8.4f} ${t['streamrag_cost']:>8.4f} "
          f"{t['overall_cost_saving_pct']:>9.1f}%")
    print()

    # Turns
    print("  TURNS (tool-call rounds)")
    print("  " + "-" * 55)
    print(f"  {'Test':<25} {'Baseline':>10} {'StreamRAG':>10}")
    print("  " + "-" * 55)
    for r in rows:
        print(f"  {r['name']:<25} {r['baseline_turns']:>10} {r['streamrag_turns']:>10}")
    print()

    # Errors
    has_errors = any(r["baseline_error"] or r["streamrag_error"] for r in rows)
    if has_errors:
        print("  ERRORS")
        print("  " + "-" * 55)
        for r in rows:
            if r["streamrag_error"]:
                print(f"  ⚠ {r['name']} (streamrag): {r['streamrag_error'][:80]}")
            if r["baseline_error"]:
                print(f"  ⚠ {r['name']} (baseline): {r['baseline_error'][:80]}")
        print()

    print(f"  Results saved: {RESULT_DIR}/")
    print(f"    comparison_report.md    — full markdown report")
    print(f"    comparison_results.json — machine-readable results")
    print(f"    *.raw.json              — raw Claude Code outputs")
    print(f"    *.stderr                — plugin/debug logs")
    print(f"    *.artifact.json         — per-test metric summaries")
    print()
    print("=" * 90)


# ── Main ───────────────────────────────────────────────────────────

def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 70)
    print("  Real Benchmark: Claude Code WITH vs WITHOUT StreamRAG")
    print("=" * 70)
    print(f"  Project:  {PROJECT_DIR}")
    print(f"  Plugin:   {PLUGIN_DIR}")
    print(f"  Results:  {RESULT_DIR}/")
    print(f"  Prompts:  {len(PROMPTS)}")
    print(f"  Runs:     {len(PROMPTS) * 2} total (each prompt x 2 modes)")
    print()

    # Initialize StreamRAG graph for the project
    init_script = Path(PLUGIN_DIR) / "scripts" / "init_graph.py"
    if init_script.is_file():
        print(f"  Initializing StreamRAG graph for {PROJECT_DIR}...")
        try:
            subprocess.run(
                [sys.executable, str(init_script), PROJECT_DIR],
                timeout=60,
                capture_output=True,
            )
            print("  Graph initialized.")
        except Exception as e:
            print(f"  Graph init warning: {e}")
    print()

    all_results: List[Dict[str, RunMetrics]] = []

    for i, test in enumerate(PROMPTS):
        name = test["name"]
        prompt = test["prompt"]
        n = i + 1

        print(f"━━━ Test {n}/{len(PROMPTS)}: {name} ━━━")
        print(f"  Prompt: {prompt[:70]}...")
        print()

        # Run baseline (without StreamRAG)
        print(f"  [baseline] Running claude -p (no plugin)...")
        baseline = run_claude(prompt, name, "baseline")
        status_b = f"OK {baseline.wall_time_s}s" if baseline.success else f"ERR {baseline.error[:50]}"
        print(f"  [baseline] {status_b}  |  {baseline.total_tokens:,} tokens  |  ${baseline.cost_usd:.4f}")
        print()

        # Run with StreamRAG
        print(f"  [streamrag] Running claude -p --plugin-dir ...")
        streamrag = run_claude(prompt, name, "streamrag")
        status_s = f"OK {streamrag.wall_time_s}s" if streamrag.success else f"ERR {streamrag.error[:50]}"
        print(f"  [streamrag] {status_s}  |  {streamrag.total_tokens:,} tokens  |  ${streamrag.cost_usd:.4f}")

        # Quick comparison
        if baseline.success and streamrag.success and streamrag.wall_time_s > 0:
            spd = baseline.wall_time_s / streamrag.wall_time_s
            print(f"  -> Speedup: {spd:.1f}x")

        print()
        all_results.append({"baseline": baseline, "streamrag": streamrag})

    # Generate report
    print("Generating report...")
    final_data = generate_report(all_results)
    print_table(final_data)


if __name__ == "__main__":
    main()
