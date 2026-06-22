#!/usr/bin/env bash
# Log one paper cycle and append a reminder to paper_trial_log.md
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="data/research/paper_trial_log.md"
echo "=== Paper trial --once $(date -Iseconds) ==="
python run_agent.py --once
python tools/status.py 2>/dev/null || true
echo ""
echo "Log this session in: $LOG"
echo "  Date | entries | exits | notes from logs/trades_*.jsonl"
