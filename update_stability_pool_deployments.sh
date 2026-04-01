#!/bin/zsh
set -euo pipefail

events_out="${EVENTS_OUT:-data/stability_pool_balance_changes_full.jsonl}"
lots_out="${LOTS_OUT:-data/stability_pool_deployments.json}"
marks_out="${MARKS_OUT:-data/stability_pool_deployment_marks.jsonl}"
html_out="${HTML_OUT:-stability_pool_deployments.html}"
tracker_html_out="${TRACKER_HTML_OUT:-stability_pool_onchain_tracker.html}"
max_pages="${MAX_PAGES:-8}"
page_size="${PAGE_SIZE:-1000}"

python3 stability_pool_onchain_tracker.py backfill --out "$events_out" --max-pages "$max_pages" --page-size "$page_size"
python3 render_stability_pool_tracker_html.py --events "$events_out" --out "$tracker_html_out"
python3 stability_pool_deployments_monitor.py update --events "$events_out" --lots-out "$lots_out" --marks-out "$marks_out" "$@"
python3 render_stability_pool_deployments_html.py --lots "$lots_out" --marks "$marks_out" --out "$html_out"

echo "$html_out"
