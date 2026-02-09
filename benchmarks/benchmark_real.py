#!/usr/bin/env python3
"""Real-world benchmark: Claude Code WITH vs WITHOUT StreamRAG.

Runs 8 test prompts against the Incredible-API codebase through the Claude CLI,
comparing performance with and without the StreamRAG plugin.

Metrics: wall-clock time, token usage (including cache), cost, accuracy, turns.

Usage:
    python3 benchmarks/benchmark_real.py --project-dir /path/to/project
    python3 benchmarks/benchmark_real.py --project-dir /path/to/project --runs 3
    python3 benchmarks/benchmark_real.py --dry-run --project-dir /path/to/project
"""

import argparse
import csv
import json
import math
import os
import pathlib
import random
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# -- Configuration -----------------------------------------------------------

DEFAULT_PROJECT_DIR = None  # Required: pass --project-dir
DEFAULT_PLUGIN_DIR = str(pathlib.Path(__file__).resolve().parent.parent)

# Resolve claude CLI path (subprocess may not have ~/.local/bin in PATH)
def _find_claude_binary() -> str:
    """Find the claude CLI binary."""
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    # Common install locations
    for candidate in [
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
        os.path.expanduser("~/.npm-global/bin/claude"),
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "claude"  # fallback, let it fail with a clear error

CLAUDE_BIN = _find_claude_binary()

# Sonnet pricing (per million tokens)
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0
CACHE_WRITE_COST_PER_M = 3.75
CACHE_READ_COST_PER_M = 0.30

MAX_TURNS = 0  # Unlimited turns
TIMEOUT_SECONDS = 600  # 10 min per prompt (no turn limit)


# -- Data Structures ---------------------------------------------------------

@dataclass
class TestCase:
    id: str
    category: str
    prompt: str
    expected_mentions: List[str]


@dataclass
class RunResult:
    test_id: str
    mode: str
    wall_time_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_tokens: int = 0
    num_turns: int = 0
    cost_usd: float = 0.0
    response_text: str = ""
    accuracy_score: float = 0.0
    mentions_found: List[str] = field(default_factory=list)
    mentions_missed: List[str] = field(default_factory=list)
    files_referenced: int = 0
    response_length: int = 0
    error: str = ""
    raw_json: dict = field(default_factory=dict)
    run_index: int = 0


# -- Test Cases --------------------------------------------------------------

TEST_CASES: List[TestCase] = [
    # Category 1: Dependency Analysis
    TestCase(
        id="01_dependency_callers",
        category="Dependency Analysis",
        prompt=(
            "List every function that calls `validate_api_key` in "
            "`api/auth/api_key_service.py`. Give exact file paths and function names. "
            "Do NOT guess -- only list callers you can verify in the code."
        ),
        expected_mentions=[
            "api/auth/decorators.py",
            "require_api_key",
            "optional_api_key",
            "validate_api_key",
        ],
    ),
    TestCase(
        id="02_dependency_chain",
        category="Dependency Analysis",
        prompt=(
            "What files and functions depend on `api/utils/credits.py`? "
            "Show the full dependency chain -- which files import from it, "
            "and which functions call its exports."
        ),
        expected_mentions=[
            "credits",
            "api/services/text.py",
            "api/services/image.py",
            "track_",
        ],
    ),

    # Category 2: Impact Analysis
    TestCase(
        id="03_refactor_impact",
        category="Impact Analysis",
        prompt=(
            "If I refactor the `AgenticModel` class in "
            "`api/agentic_model/agentic_model.py`, what other files would break? "
            "List every file that imports from or calls into this module."
        ),
        expected_mentions=[
            "api/agentic_model/api.py",
            "AgenticModel",
            "chat_completion",
            "complete",
            "agentic_model",
        ],
    ),
    TestCase(
        id="04_models_dict_impact",
        category="Impact Analysis",
        prompt=(
            "What would be affected if I change the `MODELS` dict in "
            "`api/agentic_model/llm/models.py`? Which files import it, "
            "and how is it used at runtime?"
        ),
        expected_mentions=[
            "models",
            "MODELS",
            "llm/models.py",
            "provider",
        ],
    ),

    # Category 3: Architecture Tracing
    TestCase(
        id="05_chat_completion_trace",
        category="Architecture Tracing",
        prompt=(
            "Trace the complete call chain when a request hits "
            "`/v1/chat/completions`. Start from the route registration in "
            "the server, through the handler, into the model layer, "
            "down to the LLM provider. List each file and function in order."
        ),
        expected_mentions=[
            "server",
            "api.py",
            "chat_completion",
            "AgenticModel",
            "complete",
            "provider",
        ],
    ),
    TestCase(
        id="06_integration_registry_trace",
        category="Architecture Tracing",
        prompt=(
            "How does the integration registry work? Trace from "
            "`api/integrations/registry.py` through discovery to when "
            "an integration's functions are used in a chat request."
        ),
        expected_mentions=[
            "registry",
            "IntegrationRegistry",
            "pipedream",
            "api.py",
        ],
    ),

    # Category 4: Cross-Module Understanding
    TestCase(
        id="07_auth_credit_relationship",
        category="Cross-Module Understanding",
        prompt=(
            "What is the relationship between the auth system (`api/auth/`) "
            "and the credit system (`api/utils/credits.py`, "
            "`api/utils/credit_check.py`)? How do they interact during a request?"
        ),
        expected_mentions=[
            "decorators",
            "require_api_key",
            "credit_check",
            "credits",
            "auth",
        ],
    ),
    TestCase(
        id="08_llm_providers",
        category="Cross-Module Understanding",
        prompt=(
            "List all the different LLM providers in "
            "`api/agentic_model/llm/providers/`. For each one, what model "
            "names does it support and where is it referenced in the MODELS "
            "configuration?"
        ),
        expected_mentions=[
            "fireworks",
            "google_genai",
            "cerebras",
            "novita",
            "models",
            "MODELS",
        ],
    ),
]


# -- Core Functions ----------------------------------------------------------

def run_claude(
    prompt: str,
    with_streamrag: bool,
    project_dir: str,
    plugin_dir: str,
) -> Tuple[dict, float]:
    """Run claude -p and return (parsed_json, wall_time_seconds)."""
    cmd = [
        CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--no-session-persistence",
        *(["--max-turns", str(MAX_TURNS)] if MAX_TURNS > 0 else []),
    ]

    if with_streamrag:
        cmd.extend(["--plugin-dir", plugin_dir])

    # Ensure ~/.local/bin is in PATH for subprocess
    env = os.environ.copy()
    local_bin = os.path.expanduser("~/.local/bin")
    if local_bin not in env.get("PATH", ""):
        env["PATH"] = local_bin + ":" + env.get("PATH", "")

    start = time.perf_counter()
    try:
        # Pipe prompt via stdin to avoid argument parsing issues with --plugin-dir
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            input=prompt,
            timeout=TIMEOUT_SECONDS,
            env=env,
        )
        wall_time = time.perf_counter() - start

        stdout = result.stdout.strip()
        if not stdout:
            return {"error": f"Empty output. stderr: {result.stderr[:500]}"}, wall_time

        try:
            data = json.loads(stdout)
            return data, wall_time
        except json.JSONDecodeError:
            return {"result": stdout, "error": "Non-JSON output"}, wall_time

    except subprocess.TimeoutExpired:
        wall_time = time.perf_counter() - start
        return {"error": f"Timeout after {TIMEOUT_SECONDS}s"}, wall_time
    except FileNotFoundError:
        wall_time = time.perf_counter() - start
        return {"error": "claude CLI not found. Is Claude Code installed?"}, wall_time


def _is_camel_case(s: str) -> bool:
    """Check if a string is CamelCase (e.g., IntegrationRegistry)."""
    return bool(re.match(r'^[A-Z][a-z]+(?:[A-Z][a-z]+)+$', s))


def _split_camel_case(s: str) -> List[str]:
    """Split CamelCase into individual words."""
    return re.findall(r'[A-Z][a-z]+', s)


def _is_genuine_match(mention: str, response: str) -> bool:
    """Check if mention genuinely appears in response with word/path-boundary awareness.

    For file paths (containing / or .): require path-boundary match (not a random substring).
    For prefix patterns (ending with _): require the prefix to start a word.
    For CamelCase names: also check if individual words appear near each other.
    For plain words: require word-boundary match.
    """
    mention_lower = mention.lower()
    response_lower = response.lower()

    # Prefix patterns like "track_": match "track_credits", "track_usage", etc.
    if mention_lower.endswith("_"):
        # Find all occurrences and check they start at a word boundary
        pattern = r'(?:^|[\s,;:({/])' + re.escape(mention_lower)
        return bool(re.search(pattern, response_lower))

    # File path mentions (contain / or end with known extensions)
    if "/" in mention_lower or mention_lower.endswith((".py", ".ts", ".js", ".rs")):
        # Path-boundary match: allow the mention to appear after whitespace, quotes,
        # backticks, or at path separators -- but not as random substring of a word
        # e.g., "llm/" should match "llm/providers" and "api/agentic_model/llm/"
        # but "credits" should NOT match "require_credits" when checking "credits.py"
        pattern = r'(?:^|[\s`"\'/])' + re.escape(mention_lower)
        return bool(re.search(pattern, response_lower))

    # Plain word mentions: word-boundary match
    # e.g., "credits" should match "credits.py" and "api/utils/credits"
    # but NOT "require_credits"
    pattern = r'(?:^|[^a-z0-9_])' + re.escape(mention_lower) + r'(?:[^a-z0-9_]|$)'
    if re.search(pattern, response_lower):
        return True

    # CamelCase-aware fallback: if mention is CamelCase (e.g. "IntegrationRegistry"),
    # check if all component words appear near each other in the response
    if _is_camel_case(mention):
        words = _split_camel_case(mention)
        if len(words) >= 2:
            # Check if all words appear within 100 chars of each other
            first_word = words[0].lower()
            positions = [m.start() for m in re.finditer(re.escape(first_word), response_lower)]
            for pos in positions:
                window = response_lower[max(0, pos - 20):pos + 100]
                if all(w.lower() in window for w in words):
                    return True

    return False


def score_accuracy(
    response: str, expected: List[str]
) -> Tuple[float, List[str], List[str]]:
    """Score response against expected mentions with word-boundary awareness."""
    found = []
    missed = []

    for mention in expected:
        if _is_genuine_match(mention, response):
            found.append(mention)
        else:
            missed.append(mention)

    score = len(found) / len(expected) if expected else 1.0
    return score, found, missed


def count_file_references(response: str) -> int:
    """Count unique source file paths referenced in the response."""
    patterns = re.findall(r'[\w/._-]+\.(?:py|ts|js|rs|java|cpp|c|h)', response)
    return len(set(patterns))


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate cost in USD based on Sonnet pricing (including cache tokens)."""
    return (
        input_tokens * INPUT_COST_PER_M
        + output_tokens * OUTPUT_COST_PER_M
        + cache_read_tokens * CACHE_READ_COST_PER_M
        + cache_creation_tokens * CACHE_WRITE_COST_PER_M
    ) / 1_000_000


def _extract_num_turns(raw_data: dict) -> int:
    """Extract number of turns from Claude JSON output."""
    # Try num_turns field directly
    if "num_turns" in raw_data:
        return raw_data["num_turns"]
    # Try counting from conversation turns
    if isinstance(raw_data.get("messages"), list):
        return sum(1 for m in raw_data["messages"] if m.get("role") == "assistant")
    # Fallback: check subtype for max-turns indicator
    if raw_data.get("subtype") == "error_max_turns":
        return MAX_TURNS
    return 0


def build_run_result(
    test_id: str,
    mode: str,
    raw_data: dict,
    wall_time: float,
    expected_mentions: List[str],
    run_index: int = 0,
) -> RunResult:
    """Build a RunResult from raw Claude JSON output."""
    result = RunResult(
        test_id=test_id, mode=mode, wall_time_s=round(wall_time, 2),
        run_index=run_index,
    )

    if "error" in raw_data and not raw_data.get("result"):
        # Handle max-turns errors: still extract the response text if available
        if raw_data.get("subtype") == "error_max_turns":
            # Try to get partial response from content blocks
            if isinstance(raw_data.get("content"), list):
                response_text = " ".join(
                    b.get("text", "") for b in raw_data["content"] if b.get("type") == "text"
                )
                result.response_text = response_text
                result.response_length = len(response_text)
        else:
            result.error = raw_data["error"]
            result.raw_json = raw_data
            return result

    # Extract response text
    if not result.response_text:
        response_text = raw_data.get("result", "")
        if not response_text and isinstance(raw_data.get("content"), list):
            response_text = " ".join(
                b.get("text", "") for b in raw_data["content"] if b.get("type") == "text"
            )
        result.response_text = response_text
        result.response_length = len(response_text)

    # Extract token usage (including cache tokens)
    usage = raw_data.get("usage", {})
    result.input_tokens = usage.get("input_tokens", 0)
    result.output_tokens = usage.get("output_tokens", 0)
    result.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
    result.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
    result.total_tokens = (
        result.input_tokens + result.output_tokens
        + result.cache_read_tokens + result.cache_creation_tokens
    )

    # Use total_cost_usd from raw JSON if available, otherwise estimate
    if "total_cost_usd" in raw_data:
        result.cost_usd = round(raw_data["total_cost_usd"], 6)
    elif "cost_usd" in raw_data:
        result.cost_usd = round(raw_data["cost_usd"], 6)
    else:
        result.cost_usd = round(estimate_cost(
            result.input_tokens, result.output_tokens,
            result.cache_read_tokens, result.cache_creation_tokens,
        ), 6)

    # Extract num_turns
    result.num_turns = _extract_num_turns(raw_data)

    # Score accuracy
    score, found, missed = score_accuracy(result.response_text, expected_mentions)
    result.accuracy_score = round(score, 3)
    result.mentions_found = found
    result.mentions_missed = missed

    # Count file references
    result.files_referenced = count_file_references(result.response_text)

    result.raw_json = raw_data
    return result


# -- Benchmark Runner --------------------------------------------------------

def run_benchmark(
    project_dir: str,
    plugin_dir: str,
    results_dir: str,
    dry_run: bool = False,
    run_index: int = 0,
    randomize: bool = False,
) -> List[RunResult]:
    """Run all test cases with and without StreamRAG."""
    all_results: List[RunResult] = []
    raw_dir = os.path.join(results_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    total = len(TEST_CASES)

    # Build execution order: list of (test_case, mode_label, with_streamrag) tuples
    execution_order = []
    for tc in TEST_CASES:
        execution_order.append((tc, "without_streamrag", False))
        execution_order.append((tc, "with_streamrag", True))

    if randomize:
        random.shuffle(execution_order)

    for step, (tc, mode_label, with_sr) in enumerate(execution_order):
        n = step + 1
        tag = "WITH StreamRAG" if with_sr else "WITHOUT StreamRAG"
        print(f"\n{'--' * 35}")
        print(f"  Step {n}/{len(execution_order)}: {tc.id} [{tag}]")
        print(f"  Prompt: {tc.prompt[:90]}...")
        print(f"{'--' * 35}")

        print(f"  Running...", end="", flush=True)

        if dry_run:
            # Simulate a response for testing the script itself
            raw_data = {
                "result": f"[DRY RUN] Would run: {tc.prompt[:50]}... (mode={mode_label})",
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 800,
                    "cache_read_input_tokens": 50000,
                    "cache_creation_input_tokens": 3000,
                },
                "num_turns": 5,
                "session_id": "dry-run-session",
            }
            wall_time = 0.5
        else:
            raw_data, wall_time = run_claude(
                tc.prompt, with_sr, project_dir, plugin_dir
            )

        result = build_run_result(
            tc.id, mode_label, raw_data, wall_time, tc.expected_mentions,
            run_index=run_index,
        )
        all_results.append(result)

        # Save raw JSON artifact
        suffix = f"_run{run_index}" if run_index > 0 else ""
        raw_file = os.path.join(raw_dir, f"{tc.id}_{mode_label}{suffix}.json")
        with open(raw_file, "w") as f:
            json.dump(raw_data, f, indent=2, default=str)

        # Print inline summary
        if result.error:
            print(f" ERROR: {result.error[:80]}")
        else:
            print(
                f" Done in {result.wall_time_s}s | "
                f"{result.total_tokens:,} tokens (${result.cost_usd:.4f}) | "
                f"accuracy: {result.accuracy_score:.0%} | "
                f"{result.num_turns} turns"
            )

    return all_results


# -- Multi-Run Aggregation --------------------------------------------------

@dataclass
class AggregatedResult:
    test_id: str
    mode: str
    n_runs: int = 0
    wall_time_mean: float = 0.0
    wall_time_std: float = 0.0
    total_tokens_mean: float = 0.0
    total_tokens_std: float = 0.0
    cost_mean: float = 0.0
    cost_std: float = 0.0
    accuracy_mean: float = 0.0
    accuracy_std: float = 0.0
    turns_mean: float = 0.0
    turns_std: float = 0.0


def _std(values: List[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def aggregate_results(all_run_results: List[List[RunResult]]) -> List[AggregatedResult]:
    """Aggregate results across multiple runs."""
    # Group by (test_id, mode)
    groups: Dict[Tuple[str, str], List[RunResult]] = {}
    for run_results in all_run_results:
        for r in run_results:
            key = (r.test_id, r.mode)
            groups.setdefault(key, []).append(r)

    aggregated = []
    for (test_id, mode), results in sorted(groups.items()):
        times = [r.wall_time_s for r in results]
        tokens = [float(r.total_tokens) for r in results]
        costs = [r.cost_usd for r in results]
        accs = [r.accuracy_score for r in results]
        turns = [float(r.num_turns) for r in results]
        n = len(results)

        aggregated.append(AggregatedResult(
            test_id=test_id,
            mode=mode,
            n_runs=n,
            wall_time_mean=round(sum(times) / n, 2),
            wall_time_std=round(_std(times), 2),
            total_tokens_mean=round(sum(tokens) / n, 0),
            total_tokens_std=round(_std(tokens), 0),
            cost_mean=round(sum(costs) / n, 6),
            cost_std=round(_std(costs), 6),
            accuracy_mean=round(sum(accs) / n, 3),
            accuracy_std=round(_std(accs), 3),
            turns_mean=round(sum(turns) / n, 1),
            turns_std=round(_std(turns), 1),
        ))

    return aggregated


# -- Artifact Saving ---------------------------------------------------------

def save_results_json(results: List[RunResult], results_dir: str):
    """Save all results as structured JSON."""
    data = []
    for r in results:
        d = asdict(r)
        del d["raw_json"]  # Already saved separately
        d["response_text"] = d["response_text"][:5000]  # Truncate for sanity
        data.append(d)

    path = os.path.join(results_dir, "results.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_summary_csv(results: List[RunResult], results_dir: str):
    """Save metrics as CSV for easy analysis."""
    path = os.path.join(results_dir, "summary.csv")
    fieldnames = [
        "test_id", "mode", "run_index", "wall_time_s",
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
        "total_tokens", "num_turns", "cost_usd", "accuracy_score",
        "files_referenced", "response_length",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: getattr(r, k) for k in fieldnames})


def save_config(results_dir: str, project_dir: str, plugin_dir: str, dry_run: bool,
                num_runs: int = 1, randomize: bool = False):
    """Save run configuration."""
    config = {
        "timestamp": datetime.now().isoformat(),
        "project_dir": project_dir,
        "plugin_dir": plugin_dir,
        "dry_run": dry_run,
        "max_turns": MAX_TURNS,
        "timeout_seconds": TIMEOUT_SECONDS,
        "test_count": len(TEST_CASES),
        "num_runs": num_runs,
        "randomize": randomize,
        "input_cost_per_m": INPUT_COST_PER_M,
        "output_cost_per_m": OUTPUT_COST_PER_M,
        "cache_write_cost_per_m": CACHE_WRITE_COST_PER_M,
        "cache_read_cost_per_m": CACHE_READ_COST_PER_M,
    }
    path = os.path.join(results_dir, "config.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


# -- Report Generation -------------------------------------------------------

def generate_report(results: List[RunResult], results_dir: str, project_dir: str,
                    num_runs: int = 1) -> str:
    """Generate a comprehensive markdown comparison report."""
    lines = []
    lines.append("# StreamRAG Benchmark: WITH vs WITHOUT")
    lines.append("")
    lines.append("## Configuration")
    lines.append(f"- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **Project**: `{project_dir}`")
    lines.append(f"- **Max turns**: {MAX_TURNS}")
    lines.append(f"- **Test cases**: {len(TEST_CASES)}")
    lines.append(f"- **Runs**: {num_runs}")
    lines.append("")

    # Build paired results (use last run for single-run, or average for multi-run)
    pairs: Dict[str, Dict[str, RunResult]] = {}
    for r in results:
        pairs.setdefault(r.test_id, {})[r.mode] = r

    # -- Summary Table -------------------------------------------------------
    lines.append("## Results Summary")
    lines.append("")
    lines.append(
        "| # | Test | "
        "Time (w/o) | Time (w/) | "
        "Tokens (w/o) | Tokens (w/) | "
        "Turns (w/o) | Turns (w/) | "
        "Accuracy (w/o) | Accuracy (w/) | "
        "Cost (w/o) | Cost (w/) |"
    )
    lines.append("|---|------|" + "---|" * 10)

    totals = {
        "time_without": 0, "time_with": 0,
        "tokens_without": 0, "tokens_with": 0,
        "cost_without": 0, "cost_with": 0,
        "acc_without": 0, "acc_with": 0,
        "turns_without": 0, "turns_with": 0,
    }
    count = 0

    for i, tc in enumerate(TEST_CASES):
        pair = pairs.get(tc.id, {})
        wo = pair.get("without_streamrag")
        wi = pair.get("with_streamrag")
        if not wo or not wi:
            continue
        count += 1

        totals["time_without"] += wo.wall_time_s
        totals["time_with"] += wi.wall_time_s
        totals["tokens_without"] += wo.total_tokens
        totals["tokens_with"] += wi.total_tokens
        totals["cost_without"] += wo.cost_usd
        totals["cost_with"] += wi.cost_usd
        totals["acc_without"] += wo.accuracy_score
        totals["acc_with"] += wi.accuracy_score
        totals["turns_without"] += wo.num_turns
        totals["turns_with"] += wi.num_turns

        lines.append(
            f"| {i+1} | {tc.id} | "
            f"{wo.wall_time_s}s | {wi.wall_time_s}s | "
            f"{wo.total_tokens:,} | {wi.total_tokens:,} | "
            f"{wo.num_turns} | {wi.num_turns} | "
            f"{wo.accuracy_score:.0%} | {wi.accuracy_score:.0%} | "
            f"${wo.cost_usd:.4f} | ${wi.cost_usd:.4f} |"
        )

    # Totals row
    avg_acc_wo = totals["acc_without"] / count if count else 0
    avg_acc_wi = totals["acc_with"] / count if count else 0
    lines.append(
        f"| | **TOTAL** | "
        f"**{totals['time_without']:.1f}s** | **{totals['time_with']:.1f}s** | "
        f"**{totals['tokens_without']:,}** | **{totals['tokens_with']:,}** | "
        f"**{totals['turns_without']}** | **{totals['turns_with']}** | "
        f"**{avg_acc_wo:.0%}** | **{avg_acc_wi:.0%}** | "
        f"**${totals['cost_without']:.4f}** | **${totals['cost_with']:.4f}** |"
    )
    lines.append("")

    # -- Key Metrics ---------------------------------------------------------
    lines.append("## Key Metrics")
    lines.append("")

    time_diff = totals["time_without"] - totals["time_with"]
    time_pct = (time_diff / totals["time_without"] * 100) if totals["time_without"] else 0
    token_diff = totals["tokens_without"] - totals["tokens_with"]
    token_pct = (token_diff / totals["tokens_without"] * 100) if totals["tokens_without"] else 0
    cost_diff = totals["cost_without"] - totals["cost_with"]
    acc_diff = (avg_acc_wi - avg_acc_wo) * 100
    turns_diff = totals["turns_without"] - totals["turns_with"]

    lines.append(f"| Metric | Without | With | Delta |")
    lines.append(f"|--------|---------|------|-------|")
    lines.append(
        f"| Total Time | {totals['time_without']:.1f}s | {totals['time_with']:.1f}s | "
        f"{'+' if time_diff < 0 else '-'}{abs(time_diff):.1f}s ({abs(time_pct):.1f}%) |"
    )
    lines.append(
        f"| Total Tokens | {totals['tokens_without']:,} | {totals['tokens_with']:,} | "
        f"{'+' if token_diff < 0 else '-'}{abs(token_diff):,} ({abs(token_pct):.1f}%) |"
    )
    lines.append(
        f"| Total Turns | {totals['turns_without']} | {totals['turns_with']} | "
        f"{'+' if turns_diff < 0 else '-'}{abs(turns_diff)} |"
    )
    lines.append(
        f"| Total Cost | ${totals['cost_without']:.4f} | ${totals['cost_with']:.4f} | "
        f"{'+' if cost_diff < 0 else '-'}${abs(cost_diff):.4f} |"
    )
    lines.append(
        f"| Avg Accuracy | {avg_acc_wo:.0%} | {avg_acc_wi:.0%} | "
        f"{'+' if acc_diff >= 0 else ''}{acc_diff:.1f}pp |"
    )
    lines.append("")

    # -- Per-Category Breakdown ----------------------------------------------
    lines.append("## Per-Category Breakdown")
    lines.append("")

    categories: Dict[str, List[Tuple[RunResult, RunResult]]] = {}
    for tc in TEST_CASES:
        pair = pairs.get(tc.id, {})
        wo = pair.get("without_streamrag")
        wi = pair.get("with_streamrag")
        if wo and wi:
            categories.setdefault(tc.category, []).append((wo, wi))

    for cat, cat_pairs in categories.items():
        avg_acc_wo_cat = sum(wo.accuracy_score for wo, wi in cat_pairs) / len(cat_pairs)
        avg_acc_wi_cat = sum(wi.accuracy_score for wo, wi in cat_pairs) / len(cat_pairs)
        avg_time_wo = sum(wo.wall_time_s for wo, wi in cat_pairs) / len(cat_pairs)
        avg_time_wi = sum(wi.wall_time_s for wo, wi in cat_pairs) / len(cat_pairs)
        avg_tok_wo = sum(wo.total_tokens for wo, wi in cat_pairs) / len(cat_pairs)
        avg_tok_wi = sum(wi.total_tokens for wo, wi in cat_pairs) / len(cat_pairs)
        avg_turns_wo = sum(wo.num_turns for wo, wi in cat_pairs) / len(cat_pairs)
        avg_turns_wi = sum(wi.num_turns for wo, wi in cat_pairs) / len(cat_pairs)

        lines.append(f"### {cat}")
        lines.append(f"- Avg Accuracy: {avg_acc_wo_cat:.0%} (without) vs {avg_acc_wi_cat:.0%} (with)")
        lines.append(f"- Avg Time: {avg_time_wo:.1f}s (without) vs {avg_time_wi:.1f}s (with)")
        lines.append(f"- Avg Tokens: {avg_tok_wo:,.0f} (without) vs {avg_tok_wi:,.0f} (with)")
        lines.append(f"- Avg Turns: {avg_turns_wo:.1f} (without) vs {avg_turns_wi:.1f} (with)")
        lines.append("")

    # -- Token Usage Comparison ----------------------------------------------
    lines.append("## Token Usage Comparison")
    lines.append("")
    lines.append(
        "| Test | Input (w/o) | Input (w/) | Output (w/o) | Output (w/) | "
        "Cache Read (w/o) | Cache Read (w/) | Turns (w/o) | Turns (w/) |"
    )
    lines.append("|------|" + "---|" * 8)

    for tc in TEST_CASES:
        pair = pairs.get(tc.id, {})
        wo = pair.get("without_streamrag")
        wi = pair.get("with_streamrag")
        if wo and wi:
            lines.append(
                f"| {tc.id} | {wo.input_tokens:,} | {wi.input_tokens:,} | "
                f"{wo.output_tokens:,} | {wi.output_tokens:,} | "
                f"{wo.cache_read_tokens:,} | {wi.cache_read_tokens:,} | "
                f"{wo.num_turns} | {wi.num_turns} |"
            )
    lines.append("")

    # -- Auto-Generated Findings ---------------------------------------------
    lines.append("## Key Findings")
    lines.append("")

    if acc_diff > 0:
        lines.append(f"- StreamRAG improved average accuracy by **{acc_diff:.1f} percentage points**")
    elif acc_diff < 0:
        lines.append(f"- StreamRAG decreased average accuracy by **{abs(acc_diff):.1f} percentage points**")
    else:
        lines.append("- Accuracy was the same with and without StreamRAG")

    if token_diff > 0:
        lines.append(f"- StreamRAG used **{abs(token_diff):,}** fewer tokens total ({abs(token_pct):.1f}% reduction)")
    elif token_diff < 0:
        lines.append(f"- StreamRAG used **{abs(token_diff):,}** more tokens total ({abs(token_pct):.1f}% increase)")

    if turns_diff > 0:
        lines.append(f"- StreamRAG used **{abs(turns_diff)}** fewer turns total")
    elif turns_diff < 0:
        lines.append(f"- StreamRAG used **{abs(turns_diff)}** more turns total")

    if time_diff > 0:
        lines.append(f"- StreamRAG was **{abs(time_diff):.1f}s faster** total ({abs(time_pct):.1f}%)")
    elif time_diff < 0:
        lines.append(f"- StreamRAG was **{abs(time_diff):.1f}s slower** total ({abs(time_pct):.1f}%)")

    # Best performing category
    best_cat = None
    best_improvement = -999
    for cat, cat_pairs in categories.items():
        avg_wo = sum(wo.accuracy_score for wo, wi in cat_pairs) / len(cat_pairs)
        avg_wi = sum(wi.accuracy_score for wo, wi in cat_pairs) / len(cat_pairs)
        improvement = avg_wi - avg_wo
        if improvement > best_improvement:
            best_improvement = improvement
            best_cat = cat

    if best_cat and best_improvement > 0:
        lines.append(
            f"- Best improvement category: **{best_cat}** "
            f"(+{best_improvement*100:.1f}pp accuracy)"
        )

    lines.append("")

    # -- Individual Test Details ---------------------------------------------
    lines.append("## Individual Test Details")
    lines.append("")

    for i, tc in enumerate(TEST_CASES):
        pair = pairs.get(tc.id, {})
        wo = pair.get("without_streamrag")
        wi = pair.get("with_streamrag")

        lines.append(f"### {i+1}. {tc.id} [{tc.category}]")
        lines.append(f"**Prompt**: {tc.prompt}")
        lines.append(f"**Expected mentions**: {', '.join(tc.expected_mentions)}")
        lines.append("")

        if wo:
            lines.append(f"**WITHOUT StreamRAG**: {wo.accuracy_score:.0%} accuracy, "
                         f"{wo.wall_time_s}s, {wo.total_tokens:,} tokens, {wo.num_turns} turns")
            if wo.mentions_found:
                lines.append(f"  - Found: {', '.join(wo.mentions_found)}")
            if wo.mentions_missed:
                lines.append(f"  - Missed: {', '.join(wo.mentions_missed)}")
        if wi:
            lines.append(f"**WITH StreamRAG**: {wi.accuracy_score:.0%} accuracy, "
                         f"{wi.wall_time_s}s, {wi.total_tokens:,} tokens, {wi.num_turns} turns")
            if wi.mentions_found:
                lines.append(f"  - Found: {', '.join(wi.mentions_found)}")
            if wi.mentions_missed:
                lines.append(f"  - Missed: {', '.join(wi.mentions_missed)}")
        lines.append("")

    report = "\n".join(lines)

    # Save report
    report_path = os.path.join(results_dir, "comparison_report.md")
    with open(report_path, "w") as f:
        f.write(report)

    return report


# -- Terminal Output ---------------------------------------------------------

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"


def print_summary_table(results: List[RunResult]):
    """Print a pretty summary table to terminal."""
    pairs: Dict[str, Dict[str, RunResult]] = {}
    for r in results:
        pairs.setdefault(r.test_id, {})[r.mode] = r

    print(f"\n{BOLD}{'=' * 90}{NC}")
    print(f"{BOLD}  BENCHMARK RESULTS{NC}")
    print(f"{'=' * 90}\n")

    # Header
    header = (
        f"  {'Test':<26} | {'Time':>10} | {'Tokens':>12} | {'Turns':>6} | "
        f"{'Accuracy':>8} | {'Cost':>9}"
    )
    print(f"{CYAN}{header}{NC}")
    print(f"  {'-' * 26}-+-{'-' * 10}-+-{'-' * 12}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 9}")

    total_time_wo, total_time_wi = 0.0, 0.0
    total_tok_wo, total_tok_wi = 0, 0
    total_cost_wo, total_cost_wi = 0.0, 0.0
    total_acc_wo, total_acc_wi = 0.0, 0.0
    total_turns_wo, total_turns_wi = 0, 0
    count = 0

    for tc in TEST_CASES:
        pair = pairs.get(tc.id, {})
        wo = pair.get("without_streamrag")
        wi = pair.get("with_streamrag")
        if not wo or not wi:
            continue
        count += 1

        total_time_wo += wo.wall_time_s
        total_time_wi += wi.wall_time_s
        total_tok_wo += wo.total_tokens
        total_tok_wi += wi.total_tokens
        total_cost_wo += wo.cost_usd
        total_cost_wi += wi.cost_usd
        total_acc_wo += wo.accuracy_score
        total_acc_wi += wi.accuracy_score
        total_turns_wo += wo.num_turns
        total_turns_wi += wi.num_turns

        # Without
        print(
            f"  {tc.id:<26} | {wo.wall_time_s:>8.1f}s | {wo.total_tokens:>12,} | "
            f"{wo.num_turns:>6} | {wo.accuracy_score:>7.0%} | ${wo.cost_usd:>7.4f}"
        )
        # With
        acc_color = GREEN if wi.accuracy_score >= wo.accuracy_score else RED
        time_color = GREEN if wi.wall_time_s <= wo.wall_time_s else RED
        tok_color = GREEN if wi.total_tokens <= wo.total_tokens else RED
        turns_color = GREEN if wi.num_turns <= wo.num_turns else RED
        print(
            f"  {'  + StreamRAG':<26} | "
            f"{time_color}{wi.wall_time_s:>8.1f}s{NC} | "
            f"{tok_color}{wi.total_tokens:>12,}{NC} | "
            f"{turns_color}{wi.num_turns:>6}{NC} | "
            f"{acc_color}{wi.accuracy_score:>7.0%}{NC} | "
            f"${wi.cost_usd:>7.4f}"
        )
        print(f"  {'-' * 26}-+-{'-' * 10}-+-{'-' * 12}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 9}")

    # Totals
    avg_acc_wo = total_acc_wo / count if count else 0
    avg_acc_wi = total_acc_wi / count if count else 0

    print(f"\n{BOLD}  Totals:{NC}")
    print(f"  Time:     {total_time_wo:.1f}s (without) vs {total_time_wi:.1f}s (with)")
    print(f"  Tokens:   {total_tok_wo:,} (without) vs {total_tok_wi:,} (with)")
    print(f"  Turns:    {total_turns_wo} (without) vs {total_turns_wi} (with)")
    print(f"  Cost:     ${total_cost_wo:.4f} (without) vs ${total_cost_wi:.4f} (with)")
    print(f"  Accuracy: {avg_acc_wo:.0%} (without) vs {avg_acc_wi:.0%} (with)")

    # Delta summary
    print(f"\n{BOLD}  Deltas:{NC}")
    time_delta = total_time_wi - total_time_wo
    tok_delta = total_tok_wi - total_tok_wo
    cost_delta = total_cost_wi - total_cost_wo
    acc_delta = (avg_acc_wi - avg_acc_wo) * 100
    turns_delta = total_turns_wi - total_turns_wo

    c = GREEN if time_delta <= 0 else RED
    print(f"  Time:     {c}{time_delta:+.1f}s{NC}")
    c = GREEN if tok_delta <= 0 else RED
    print(f"  Tokens:   {c}{tok_delta:+,}{NC}")
    c = GREEN if turns_delta <= 0 else RED
    print(f"  Turns:    {c}{turns_delta:+}{NC}")
    c = GREEN if cost_delta <= 0 else RED
    print(f"  Cost:     {c}${cost_delta:+.4f}{NC}")
    c = GREEN if acc_delta >= 0 else RED
    print(f"  Accuracy: {c}{acc_delta:+.1f}pp{NC}")


# -- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Claude Code with and without StreamRAG"
    )
    parser.add_argument(
        "--project-dir", required=True,
        help="Project directory to analyze (required)"
    )
    parser.add_argument(
        "--plugin-dir", default=DEFAULT_PLUGIN_DIR,
        help=f"StreamRAG plugin directory (default: auto-detected)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run without calling Claude (test script logic)"
    )
    parser.add_argument(
        "--test-ids", nargs="+",
        help="Run only specific test IDs (e.g., 01_dependency_callers 03_refactor_impact)"
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of runs (default: 1, recommended: 3 for statistical significance)"
    )
    parser.add_argument(
        "--randomize", action="store_true",
        help="Randomize test/mode execution order (reduces cache bias)"
    )
    args = parser.parse_args()

    # Validate paths
    if not os.path.isdir(args.project_dir):
        print(f"Error: project directory not found: {args.project_dir}")
        sys.exit(1)
    if not args.dry_run and not os.path.isdir(args.plugin_dir):
        print(f"Error: plugin directory not found: {args.plugin_dir}")
        sys.exit(1)

    # Filter test cases if requested
    global TEST_CASES
    if args.test_ids:
        TEST_CASES = [tc for tc in TEST_CASES if tc.id in args.test_ids]
        if not TEST_CASES:
            print(f"Error: no test cases match IDs: {args.test_ids}")
            sys.exit(1)

    # Setup results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, "results", timestamp)
    os.makedirs(results_dir, exist_ok=True)

    # Also create/update a "latest" symlink
    latest_link = os.path.join(script_dir, "results", "latest")
    if os.path.islink(latest_link):
        os.unlink(latest_link)
    if not os.path.exists(latest_link):
        os.symlink(results_dir, latest_link)

    print(f"\n{BOLD}{'=' * 90}{NC}")
    print(f"{BOLD}  StreamRAG Real-World Benchmark{NC}")
    print(f"{'=' * 90}")
    print(f"  Project:    {CYAN}{args.project_dir}{NC}")
    print(f"  Plugin:     {CYAN}{args.plugin_dir}{NC}")
    print(f"  Results:    {CYAN}{results_dir}{NC}")
    print(f"  Tests:      {len(TEST_CASES)}")
    print(f"  Runs:       {args.runs}")
    print(f"  Max turns:  {MAX_TURNS}")
    print(f"  Randomize:  {args.randomize}")
    print(f"  Dry run:    {args.dry_run}")
    print(f"{'=' * 90}")

    # Save config
    save_config(results_dir, args.project_dir, args.plugin_dir, args.dry_run,
                num_runs=args.runs, randomize=args.randomize)

    # Initialize StreamRAG graph for the project
    if not args.dry_run:
        init_script = os.path.join(args.plugin_dir, "scripts", "init_graph.py")
        if os.path.isfile(init_script):
            print(f"\n  Initializing StreamRAG graph for {args.project_dir}...")
            try:
                subprocess.run(
                    [sys.executable, init_script, args.project_dir],
                    timeout=60,
                    capture_output=True,
                )
                print(f"  {GREEN}Graph initialized.{NC}")
            except Exception as e:
                print(f"  {YELLOW}Graph init warning: {e}{NC}")

    # Run benchmark(s)
    start_time = time.perf_counter()
    all_run_results: List[List[RunResult]] = []

    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"\n{BOLD}{'=' * 90}{NC}")
            print(f"{BOLD}  RUN {run_idx + 1}/{args.runs}{NC}")
            print(f"{'=' * 90}")

        run_results = run_benchmark(
            args.project_dir, args.plugin_dir, results_dir, args.dry_run,
            run_index=run_idx, randomize=args.randomize,
        )
        all_run_results.append(run_results)

    total_time = time.perf_counter() - start_time

    # Flatten all results for saving
    all_results = [r for run in all_run_results for r in run]

    # Save all artifacts
    save_results_json(all_results, results_dir)
    save_summary_csv(all_results, results_dir)

    # Use last run for report (or aggregate for multi-run)
    if args.runs > 1:
        aggregated = aggregate_results(all_run_results)
        # Save aggregation
        agg_path = os.path.join(results_dir, "aggregated.json")
        with open(agg_path, "w") as f:
            json.dump([asdict(a) for a in aggregated], f, indent=2)

    report = generate_report(all_run_results[-1], results_dir, args.project_dir,
                             num_runs=args.runs)

    # Print terminal summary (last run)
    print_summary_table(all_run_results[-1])

    if args.runs > 1:
        print(f"\n{BOLD}  Multi-run Statistics ({args.runs} runs):{NC}")
        for agg in aggregated:
            tag = "W/O " if agg.mode.startswith("without") else "WITH"
            print(
                f"  {agg.test_id:<28} [{tag}] "
                f"acc={agg.accuracy_mean:.0%}+/-{agg.accuracy_std:.0%}  "
                f"tok={agg.total_tokens_mean:,.0f}+/-{agg.total_tokens_std:,.0f}  "
                f"turns={agg.turns_mean:.1f}+/-{agg.turns_std:.1f}"
            )

    print(f"\n{BOLD}{'=' * 90}{NC}")
    print(f"  {GREEN}Benchmark complete in {total_time:.1f}s{NC}")
    print(f"  Results:  {results_dir}/")
    print(f"  Report:   {results_dir}/comparison_report.md")
    print(f"  CSV:      {results_dir}/summary.csv")
    print(f"  Raw data: {results_dir}/raw/")
    print(f"  JSON:     {results_dir}/results.json")
    if args.runs > 1:
        print(f"  Stats:    {results_dir}/aggregated.json")
    print(f"{BOLD}{'=' * 90}{NC}\n")


if __name__ == "__main__":
    main()
