#!/usr/bin/env bash
set -euo pipefail

events_out="${EVENTS_OUT:-data/stability_pool_balance_changes_full.jsonl}"
lots_out="${LOTS_OUT:-data/stability_pool_deployments.json}"
marks_out="${MARKS_OUT:-data/stability_pool_deployment_marks.jsonl}"
html_out="${HTML_OUT:-stability_pool_deployments.html}"
tracker_html_out="${TRACKER_HTML_OUT:-stability_pool_onchain_tracker.html}"
current_buys_json_out="${CURRENT_BUYS_JSON_OUT:-data/current_buy_xsol_events.json}"
current_buys_html_out="${CURRENT_BUYS_HTML_OUT:-current_buy_xsol_events.html}"
signal_json_out="${SIGNAL_JSON_OUT:-data/stability_pool_signal_report.json}"
signal_html_out="${SIGNAL_HTML_OUT:-stability_pool_signal_report.html}"
ohlcv_out="${OHLCV_OUT:-data/xsol_usdc_ohlcv_5m.json}"
max_pages="${MAX_PAGES:-8}"
page_size="${PAGE_SIZE:-1000}"

if ! python3 stability_pool_onchain_tracker.py backfill --out "$events_out" --max-pages "$max_pages" --page-size "$page_size"; then
  if [[ -f "$events_out" ]]; then
    echo "warning: backfill failed, keeping cached event history at $events_out" >&2
  else
    exit 1
  fi
fi
python3 render_stability_pool_tracker_html.py --events "$events_out" --out "$tracker_html_out"
python3 stability_pool_deployments_monitor.py update --events "$events_out" --lots-out "$lots_out" --marks-out "$marks_out" "$@"
python3 refresh_xsol_ohlcv.py --out "$ohlcv_out"
python3 extract_current_buy_xsol.py --backfill "$events_out" --ohlcv "$ohlcv_out" --json-out "$current_buys_json_out" --html-out "$current_buys_html_out"
python3 analyze_signal_episodes.py --backfill "$events_out" --ohlcv "$ohlcv_out" --json-out "$signal_json_out" --html-out "$signal_html_out"
python3 render_stability_pool_deployments_html.py --lots "$lots_out" --marks "$marks_out" --out "$html_out"

echo "$html_out"
