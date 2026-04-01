#!/usr/bin/env python3
import argparse
import html
import json
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path


SCREENSHOT_ROWS = [
    {"hyusd_spent": 30131.233824, "xsol_bought": 498493.006733},
    {"hyusd_spent": 11552.792571, "xsol_bought": 190916.507256},
    {"hyusd_spent": 23479.769439, "xsol_bought": 386742.798409},
    {"hyusd_spent": 21061.983677, "xsol_bought": 344971.328588},
]
EPSILON = 1e-6


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_ohlcv(path):
    raw = json.load(open(path, "r", encoding="utf-8"))
    bars = [
        {"ts": int(row[0]), "close": float(row[4])}
        for row in raw["data"]["attributes"]["ohlcv_list"]
    ]
    bars.sort(key=lambda row: row["ts"])
    return bars


def last_at_or_before(timestamps, bars, ts):
    idx = bisect_right(timestamps, ts) - 1
    if idx < 0:
        return None
    return bars[idx]


def pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def is_match(event, target):
    return (
        abs(event["hyusd_spent"] - target["hyusd_spent"]) <= EPSILON
        and abs(event["xsol_bought"] - target["xsol_bought"]) <= EPSILON
    )


def summarize(backfill_rows, bars):
    buys = []
    timestamps = [bar["ts"] for bar in bars]
    last_bar_ts = timestamps[-1]
    first_event = backfill_rows[0]
    last_event = backfill_rows[-1]
    for row in backfill_rows:
        if row["action"] != "buy_xsol":
            continue
        event_ts = int(row["block_time"])
        entry = last_at_or_before(timestamps, bars, event_ts)
        event = {
            "utc": row["utc"],
            "local": row["local"],
            "signature": row["signature"],
            "solscan_url": row["solscan_url"],
            "hyusd_spent": -row["hyusd_pool"]["delta"],
            "xsol_bought": row["xsol_pool"]["delta"],
            "implied_hyusd_per_xsol": row["estimated_hyusd_per_xsol"],
            "entry_close": entry["close"] if entry else None,
            "matches_screenshot_row": any(
                is_match(
                    {
                        "hyusd_spent": -row["hyusd_pool"]["delta"],
                        "xsol_bought": row["xsol_pool"]["delta"],
                    },
                    target,
                )
                for target in SCREENSHOT_ROWS
            ),
        }
        for label, seconds in (("1h", 3600), ("6h", 21600), ("24h", 86400)):
            if event_ts + seconds > last_bar_ts:
                event[f"{label}_return_pct"] = None
            else:
                future = last_at_or_before(timestamps, bars, event_ts + seconds)
                event[f"{label}_return_pct"] = pct(
                    event["entry_close"],
                    future["close"] if future else None,
                )
        buys.append(event)

    buys.sort(key=lambda row: row["utc"])
    return {
        "current_deployment_window": {
            "oldest_utc": first_event["utc"],
            "newest_utc": last_event["utc"],
            "oldest_local": first_event["local"],
            "newest_local": last_event["local"],
        },
        "buy_xsol_event_count": len(buys),
        "buy_xsol_total_hyusd_spent": sum(row["hyusd_spent"] for row in buys),
        "buy_xsol_total_xsol_bought": sum(row["xsol_bought"] for row in buys),
        "events": buys,
        "notes": [
            "These are all clean buy_xsol rows recovered from the current Stability Pool deployment's pool-account deltas.",
            "The current pool auth and pool token accounts only begin on March 27, 2026, so any earlier January-to-March history would require an earlier deployment with different addresses.",
        ],
    }


def fmt_num(value, digits=6):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_pct(value):
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def render_html(summary):
    rows = []
    for row in summary["events"]:
        match = "Yes" if row["matches_screenshot_row"] else ""
        rows.append(
            f"""
            <tr>
              <td>{html.escape(row['local'])}</td>
              <td class="num">{fmt_num(row['hyusd_spent'])}</td>
              <td class="num">{fmt_num(row['xsol_bought'])}</td>
              <td class="num">{fmt_num(row['implied_hyusd_per_xsol'], 9)}</td>
              <td class="num">{fmt_pct(row['1h_return_pct'])}</td>
              <td class="num">{fmt_pct(row['6h_return_pct'])}</td>
              <td class="num">{fmt_pct(row['24h_return_pct'])}</td>
              <td>{match}</td>
              <td><a href="{html.escape(row['solscan_url'])}">{html.escape(row['signature'][:10])}...</a></td>
            </tr>
            """
        )
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Current Hylo buy_xsol Events</title>
    <style>
      :root {{
        --bg: #11161b;
        --panel: #171f26;
        --border: #2d3944;
        --text: #eef4f7;
        --muted: #9eb0ba;
        --accent: #d9b369;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background:
          radial-gradient(circle at top right, rgba(217,179,105,0.15), transparent 28%),
          radial-gradient(circle at left center, rgba(78,122,153,0.12), transparent 32%),
          linear-gradient(180deg, #0f1418 0%, #0a0d10 100%);
        color: var(--text);
        font-family: "Iowan Old Style", Georgia, serif;
      }}
      .wrap {{ max-width: 1180px; margin: 0 auto; padding: 34px 22px 42px; }}
      h1 {{ margin: 0 0 10px; font-size: 2.15rem; }}
      .sub {{ color: var(--muted); line-height: 1.55; max-width: 900px; }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        margin: 22px 0;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
      }}
      .label {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
      .value {{ font-size: 1.55rem; }}
      .panel {{
        background: rgba(23,31,38,0.9);
        border: 1px solid var(--border);
        border-radius: 20px;
        padding: 20px;
      }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 11px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        text-align: left;
      }}
      th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
      td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
      a {{ color: #95d1f2; text-decoration: none; }}
      .foot {{ color: var(--muted); margin-top: 16px; line-height: 1.5; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Current Hylo buy_xsol Events</h1>
      <div class="sub">
        Exhaustive clean <code>buy_xsol</code> rows recovered from the current Stability Pool deployment by scanning the full
        public history of the derived pool accounts. Four of these rows exactly match the screenshot amounts.
      </div>
      <div class="grid">
        <div class="card">
          <div class="label">Current Deployment Window</div>
          <div class="value">{html.escape(summary['current_deployment_window']['oldest_local'][:10])} to {html.escape(summary['current_deployment_window']['newest_local'][:10])}</div>
        </div>
        <div class="card">
          <div class="label">buy_xsol Event Count</div>
          <div class="value">{summary['buy_xsol_event_count']}</div>
        </div>
        <div class="card">
          <div class="label">Total hyUSD Spent</div>
          <div class="value">{fmt_num(summary['buy_xsol_total_hyusd_spent'])}</div>
        </div>
        <div class="card">
          <div class="label">Total xSOL Bought</div>
          <div class="value">{fmt_num(summary['buy_xsol_total_xsol_bought'])}</div>
        </div>
      </div>
      <div class="panel">
        <table>
          <thead>
            <tr>
              <th>Local Time</th>
              <th>hyUSD Spent</th>
              <th>xSOL Bought</th>
              <th>Implied hyUSD/xSOL</th>
              <th>1h</th>
              <th>6h</th>
              <th>24h</th>
              <th>Screenshot Match</th>
              <th>Tx</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
        <div class="foot">
          24h returns are only shown when the cached 5-minute market file extends far enough into the future. This report does not yet prove whether Hylo had a separate pre-March 27 deployment with different mainnet addresses.
        </div>
      </div>
    </div>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Extract clean buy_xsol events from the current deployment.")
    parser.add_argument(
        "--backfill",
        default="data/stability_pool_balance_changes_full.jsonl",
        help="Full balance-change JSONL path.",
    )
    parser.add_argument(
        "--ohlcv",
        default="data/xsol_usdc_ohlcv_5m.json",
        help="OHLCV JSON path.",
    )
    parser.add_argument(
        "--json-out",
        default="data/current_buy_xsol_events.json",
        help="JSON output path.",
    )
    parser.add_argument(
        "--html-out",
        default="current_buy_xsol_events.html",
        help="HTML output path.",
    )
    args = parser.parse_args()

    summary = summarize(load_jsonl(args.backfill), load_ohlcv(args.ohlcv))
    Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.html_out).write_text(render_html(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
