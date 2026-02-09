#!/bin/bash
#
# Real Benchmark: Claude Code WITH vs WITHOUT StreamRAG
#
# Runs the same prompts through Claude Code twice:
#   1. WITHOUT StreamRAG (baseline)
#   2. WITH StreamRAG plugin loaded
#
# Measures: response time, response quality, context awareness
#
# Usage:
#   chmod +x benchmarks/real_claude_benchmark.sh
#   ./benchmarks/real_claude_benchmark.sh [project_dir]
#
# Default project: /Users/krrish/Incredible/Incredible-API

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
if [ -z "${1:-}" ]; then
    echo "Usage: $0 <project_dir>"
    exit 1
fi
PROJECT_DIR="$1"
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="${PLUGIN_DIR}/benchmarks/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$RESULTS_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Real Benchmark: Claude Code WITH vs WITHOUT StreamRAG${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "  Project:   ${CYAN}${PROJECT_DIR}${NC}"
echo -e "  Plugin:    ${CYAN}${PLUGIN_DIR}${NC}"
echo -e "  Results:   ${CYAN}${RESULTS_DIR}/${TIMESTAMP}/${NC}"
echo ""

RESULT_DIR="${RESULTS_DIR}/${TIMESTAMP}"
mkdir -p "$RESULT_DIR"

# ── StreamRAG Prompt Prefix ───────────────────────────────────────
# Prepended to prompts in "with_streamrag" mode so the model knows
# to use the graph query commands instead of defaulting to grep/glob.

STREAMRAG_PREFIX="You have access to a pre-built code dependency graph for this project via StreamRAG. BEFORE using grep or glob to explore code relationships, use these Bash commands:

python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <name>   # Who calls this?
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees <name>   # What does this call?
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps <file>     # What depends on this file?
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file> [name]  # Impact analysis
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file <file>      # All entities in a file
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py summary          # Architecture overview
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path <src> <dst> # Dependency chain

Use these graph queries as your primary source for dependency, caller, and impact information. Supplement with grep/read only to verify details or look at actual code.

"

# ── Test Prompts ───────────────────────────────────────────────────
# These prompts are designed to test dependency awareness, context
# quality, and architectural understanding — areas where StreamRAG
# should provide measurably better context.

declare -a PROMPT_NAMES=(
    "dependency_analysis"
    "impact_analysis"
    "architecture_question"
    "cross_file_trace"
    "refactor_suggestion"
)

declare -a PROMPTS=(
    "What functions call the validate function in api/auth/auth_service.py? List every caller across all files with the exact file path and function name. Be precise — don't guess."
    "If I change the credit_check function in api/utils/credit_check.py, what other files and functions would be affected? Show the full dependency chain."
    "Explain the architecture of the agentic_model module. How do the files in api/agentic_model/ connect to each other? Which file is the entry point, what calls what, and how does data flow through the system?"
    "Trace the full call chain when a user hits the chat completion endpoint. Start from api/server.py, go through the route handler, into the service layer, and down to the LLM provider call. List each function and file in order."
    "What would be the safest way to refactor api/utils/credits.py? What depends on it, and what's the risk of breaking other modules?"
)

# ── Run Function ───────────────────────────────────────────────────

run_claude() {
    local label="$1"        # "without" or "with"
    local prompt="$2"
    local prompt_name="$3"
    local output_file="${RESULT_DIR}/${prompt_name}_${label}.txt"
    local time_file="${RESULT_DIR}/${prompt_name}_${label}.time"
    local extra_flags=""

    if [ "$label" = "with_streamrag" ]; then
        extra_flags="--plugin-dir ${PLUGIN_DIR}"
        prompt="${STREAMRAG_PREFIX}${prompt}"
    fi

    echo -e "  ${YELLOW}Running ${label}...${NC}"

    # Record start time
    local start_time=$(python3 -c "import time; print(time.time())")

    # Run Claude Code in print mode (prompt via stdin to avoid --plugin-dir parsing issues)
    echo "$prompt" | claude -p \
        --output-format json \
        --no-session-persistence \
        $extra_flags \
        2>/dev/null > "$output_file" || true

    # Record end time
    local end_time=$(python3 -c "import time; print(time.time())")
    local elapsed=$(python3 -c "print(f'{${end_time} - ${start_time}:.2f}')")

    echo "$elapsed" > "$time_file"
    echo -e "  ${GREEN}Done in ${elapsed}s${NC} → ${output_file}"
}

# ── Main Benchmark Loop ───────────────────────────────────────────

# ── Initialize StreamRAG Graph ─────────────────────────────────────
INIT_SCRIPT="${PLUGIN_DIR}/scripts/init_graph.py"
if [ -f "$INIT_SCRIPT" ]; then
    echo -e "  ${YELLOW}Initializing StreamRAG graph for ${PROJECT_DIR}...${NC}"
    python3 "$INIT_SCRIPT" "$PROJECT_DIR" 2>/dev/null || echo -e "  ${YELLOW}Graph init warning (non-fatal)${NC}"
    echo -e "  ${GREEN}Graph initialized.${NC}"
    echo ""
fi

echo -e "${BOLD}Running ${#PROMPTS[@]} test prompts, each WITH and WITHOUT StreamRAG...${NC}"
echo ""

for i in "${!PROMPTS[@]}"; do
    prompt="${PROMPTS[$i]}"
    name="${PROMPT_NAMES[$i]}"
    n=$((i + 1))

    echo -e "${BLUE}━━━ Test ${n}/${#PROMPTS[@]}: ${name} ━━━${NC}"
    echo -e "  ${CYAN}Prompt:${NC} ${prompt:0:80}..."
    echo ""

    # Run WITHOUT StreamRAG first
    (cd "$PROJECT_DIR" && run_claude "without_streamrag" "$prompt" "$name")

    # Run WITH StreamRAG
    (cd "$PROJECT_DIR" && run_claude "with_streamrag" "$prompt" "$name")

    echo ""
done

# ── Generate Comparison Report ─────────────────────────────────────

REPORT_FILE="${RESULT_DIR}/comparison_report.md"

cat > "$REPORT_FILE" << 'HEADER'
# Claude Code Benchmark: WITH vs WITHOUT StreamRAG

## Test Configuration
HEADER

echo "- **Date**: $(date)" >> "$REPORT_FILE"
echo "- **Project**: \`${PROJECT_DIR}\`" >> "$REPORT_FILE"
echo "- **Plugin**: \`${PLUGIN_DIR}\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

echo "## Results Summary" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "| Test | Without StreamRAG | With StreamRAG | Speedup |" >> "$REPORT_FILE"
echo "|------|-------------------|----------------|---------|" >> "$REPORT_FILE"

total_without=0
total_with=0

for i in "${!PROMPT_NAMES[@]}"; do
    name="${PROMPT_NAMES[$i]}"

    time_without=$(cat "${RESULT_DIR}/${name}_without_streamrag.time" 2>/dev/null || echo "N/A")
    time_with=$(cat "${RESULT_DIR}/${name}_with_streamrag.time" 2>/dev/null || echo "N/A")

    if [[ "$time_without" != "N/A" && "$time_with" != "N/A" ]]; then
        speedup=$(python3 -c "
w = float('${time_without}')
s = float('${time_with}')
if s > 0:
    print(f'{w/s:.1f}x')
else:
    print('N/A')
")
        total_without=$(python3 -c "print(${total_without} + ${time_without})")
        total_with=$(python3 -c "print(${total_with} + ${time_with})")
    else
        speedup="N/A"
    fi

    echo "| ${name} | ${time_without}s | ${time_with}s | ${speedup} |" >> "$REPORT_FILE"
done

if (( $(echo "$total_with > 0" | bc -l 2>/dev/null || echo 0) )); then
    overall_speedup=$(python3 -c "print(f'{${total_without}/${total_with}:.1f}x')")
else
    overall_speedup="N/A"
fi
echo "| **TOTAL** | **${total_without}s** | **${total_with}s** | **${overall_speedup}** |" >> "$REPORT_FILE"

echo "" >> "$REPORT_FILE"
echo "## Detailed Responses" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for i in "${!PROMPT_NAMES[@]}"; do
    name="${PROMPT_NAMES[$i]}"
    prompt="${PROMPTS[$i]}"

    echo "### ${n}. ${name}" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo "**Prompt**: ${prompt}" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"

    echo "#### WITHOUT StreamRAG" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    # Extract just the result text from JSON output
    python3 -c "
import json, sys
try:
    with open('${RESULT_DIR}/${name}_without_streamrag.txt') as f:
        data = json.load(f)
    print(data.get('result', data.get('content', str(data)))[:2000])
except:
    with open('${RESULT_DIR}/${name}_without_streamrag.txt') as f:
        print(f.read()[:2000])
" >> "$REPORT_FILE" 2>/dev/null || echo "(no output)" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"

    echo "#### WITH StreamRAG" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    python3 -c "
import json, sys
try:
    with open('${RESULT_DIR}/${name}_with_streamrag.txt') as f:
        data = json.load(f)
    print(data.get('result', data.get('content', str(data)))[:2000])
except:
    with open('${RESULT_DIR}/${name}_with_streamrag.txt') as f:
        print(f.read()[:2000])
" >> "$REPORT_FILE" 2>/dev/null || echo "(no output)" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
done

# ── Print Summary ─────────────────────────────────────────────────

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  BENCHMARK COMPLETE${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${CYAN}Response Times:${NC}"
echo -e "  ┌──────────────────────────┬───────────────┬──────────────┐"
printf "  │ %-24s │ %13s │ %12s │\n" "Test" "Without" "With StreamRAG"
echo -e "  ├──────────────────────────┼───────────────┼──────────────┤"

for i in "${!PROMPT_NAMES[@]}"; do
    name="${PROMPT_NAMES[$i]}"
    time_without=$(cat "${RESULT_DIR}/${name}_without_streamrag.time" 2>/dev/null || echo "N/A")
    time_with=$(cat "${RESULT_DIR}/${name}_with_streamrag.time" 2>/dev/null || echo "N/A")
    printf "  │ %-24s │ %12ss │ %11ss │\n" "$name" "$time_without" "$time_with"
done

echo -e "  └──────────────────────────┴───────────────┴──────────────┘"
echo ""
echo -e "${GREEN}Full report: ${RESULT_DIR}/comparison_report.md${NC}"
echo -e "${GREEN}Raw outputs: ${RESULT_DIR}/*.txt${NC}"
echo ""
echo -e "${YELLOW}Tip: Review the response quality manually — StreamRAG should${NC}"
echo -e "${YELLOW}provide more precise dependency info and cross-file awareness.${NC}"
