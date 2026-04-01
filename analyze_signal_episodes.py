#!/usr/bin/env python3
import argparse
import html
import json
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


REQUIRED_BUY_HINTS = {"RebalanceStableToLever", "SwapStableToLever"}
HORIZONS = [
    ("15m", 900),
    ("1h", 3600),
    ("4h", 14400),
    ("24h", 86400),
    ("72h", 259200),
    ("7d", 604800),
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_ohlcv(path):
    raw = load_json(path)
    rows = raw["data"]["attributes"]["ohlcv_list"]
    bars = [
        {
            "ts": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]
    bars.sort(key=lambda row: row["ts"])
    return bars


def mean(values):
    return sum(values) / len(values) if values else None


def fmt_num(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_pct(value, digits=2):
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def pct_change(a, b):
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def has_required_hints(row):
    return REQUIRED_BUY_HINTS.issubset(set(row.get("log_hints") or []))


def confirmed_buy_rows(rows):
    out = []
    for row in rows:
        if row.get("action") != "buy_xsol":
            continue
        if not has_required_hints(row):
            continue
        out.append(row)
    out.sort(key=lambda row: row["block_time"])
    return out


def cluster_rows(rows, max_gap_seconds):
    clusters = []
    current = []
    for row in rows:
        if not current or row["block_time"] - current[-1]["block_time"] <= max_gap_seconds:
            current.append(row)
            continue
        clusters.append(current)
        current = [row]
    if current:
        clusters.append(current)
    return clusters


def last_at_or_before(timestamps, bars, ts):
    idx = bisect_right(timestamps, ts) - 1
    if idx < 0:
        return None, -1
    return bars[idx], idx


def first_at_or_after(timestamps, ts):
    idx = bisect_left(timestamps, ts)
    return idx


def runup_drawdown(entry_close, bars_slice):
    if not entry_close or not bars_slice:
        return None, None
    highest = max(bar["high"] for bar in bars_slice)
    lowest = min(bar["low"] for bar in bars_slice)
    return pct_change(entry_close, highest), pct_change(entry_close, lowest)


def size_bucket(value):
    if value is None:
        return "unknown"
    if value < 1.0:
        return "<1% of pool"
    if value < 3.0:
        return "1% to 3% of pool"
    return ">=3% of pool"


def drop_bucket(value):
    if value is None:
        return "unknown"
    if value > -5.0:
        return "shallow drop (<5%)"
    if value > -15.0:
        return "moderate drop (5% to 15%)"
    return "deep drop (15%+)"


def share_bucket(value):
    if value is None:
        return "unknown"
    if value < 10.0:
        return "xSOL share <10%"
    if value < 25.0:
        return "xSOL share 10% to 25%"
    return "xSOL share 25%+"


def episode_local_date(row, tz):
    stamp = datetime.fromtimestamp(int(row["block_time"]), timezone.utc)
    return stamp.astimezone(tz).date().isoformat()


def summarize_segment(rows):
    out = {
        "count": len(rows),
        "total_hyusd_spent": sum(row["hyusd_spent"] for row in rows),
        "total_xsol_bought": sum(row["xsol_bought"] for row in rows),
    }
    for label, _seconds in HORIZONS:
        values = [row.get(f"{label}_return_pct") for row in rows if row.get(f"{label}_return_pct") is not None]
        out[f"{label}_mean_return_pct"] = mean(values)
        out[f"{label}_median_return_pct"] = median(values) if values else None
        out[f"{label}_win_rate_pct"] = ((sum(1 for value in values if value > 0) / len(values)) * 100.0) if values else None
    for label in ("24h", "72h"):
        runups = [row.get(f"{label}_max_runup_pct") for row in rows if row.get(f"{label}_max_runup_pct") is not None]
        drawdowns = [row.get(f"{label}_max_drawdown_pct") for row in rows if row.get(f"{label}_max_drawdown_pct") is not None]
        out[f"{label}_median_max_runup_pct"] = median(runups) if runups else None
        out[f"{label}_median_max_drawdown_pct"] = median(drawdowns) if drawdowns else None
    return out


def build_regime_segments(episodes):
    regimes = {
        "session_type": {},
        "trigger_size_bucket": {},
        "pre_drop_bucket": {},
        "xsol_share_after_bucket": {},
    }
    mappings = {
        "session_type": lambda row: row["session_type"],
        "trigger_size_bucket": lambda row: row["trigger_size_bucket"],
        "pre_drop_bucket": lambda row: row["pre_drop_bucket"],
        "xsol_share_after_bucket": lambda row: row["xsol_share_after_bucket"],
    }
    for key, getter in mappings.items():
        groups = {}
        for row in episodes:
            groups.setdefault(getter(row), []).append(row)
        regimes[key] = {
            label: summarize_segment(items)
            for label, items in sorted(groups.items(), key=lambda item: item[0])
        }
    return regimes


def analyze(backfill_rows, bars, gap_seconds=600, tz_name="America/Los_Angeles"):
    tz = ZoneInfo(tz_name)
    buys = confirmed_buy_rows(backfill_rows)
    clusters = cluster_rows(buys, gap_seconds)
    timestamps = [bar["ts"] for bar in bars]
    last_bar_ts = timestamps[-1]
    episodes = []
    prior_episodes_by_day = {}

    for index, cluster in enumerate(clusters, start=1):
        first = cluster[0]
        last = cluster[-1]
        start_ts = int(first["block_time"])
        end_ts = int(last["block_time"])
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc)
        local_day = start_dt.astimezone(tz).date().isoformat()
        day_count = prior_episodes_by_day.get(local_day, 0)
        prior_episodes_by_day[local_day] = day_count + 1

        entry_bar, entry_idx = last_at_or_before(timestamps, bars, start_ts)
        if entry_bar is None:
            continue

        hyusd_spent = sum(-row["hyusd_pool"]["delta"] for row in cluster)
        xsol_bought = sum(row["xsol_pool"]["delta"] for row in cluster)
        weighted_market_entry_close = sum(
            (-row["hyusd_pool"]["delta"])
            * (last_at_or_before(timestamps, bars, int(row["block_time"]))[0]["close"])
            for row in cluster
        ) / hyusd_spent
        implied_price = hyusd_spent / xsol_bought

        pre_hyusd = float(first["hyusd_pool"]["pre_amount"])
        pre_xsol = float(first["xsol_pool"]["pre_amount"])
        post_hyusd = float(last["hyusd_pool"]["post_amount"])
        post_xsol = float(last["xsol_pool"]["post_amount"])
        entry_close = float(entry_bar["close"])
        pre_pool_value = pre_hyusd + (pre_xsol * entry_close)
        post_pool_value = post_hyusd + (post_xsol * entry_close)
        xsol_share_before = ((pre_xsol * entry_close) / pre_pool_value) * 100.0 if pre_pool_value else None
        xsol_share_after = ((post_xsol * entry_close) / post_pool_value) * 100.0 if post_pool_value else None

        episode = {
            "episode_id": f"episode-{index}",
            "start_utc": start_dt.isoformat(),
            "end_utc": end_dt.isoformat(),
            "start_local": start_dt.astimezone(tz).isoformat(),
            "end_local": end_dt.astimezone(tz).isoformat(),
            "local_day": local_day,
            "session_type": "first activation of day" if day_count == 0 else "follow-on activation",
            "episode_index_for_day": day_count + 1,
            "event_count": len(cluster),
            "hyusd_spent": hyusd_spent,
            "xsol_bought": xsol_bought,
            "implied_hyusd_per_xsol": implied_price,
            "market_entry_close": entry_close,
            "weighted_market_entry_close": weighted_market_entry_close,
            "execution_vs_market_pct": pct_change(weighted_market_entry_close, implied_price),
            "signal_start_bar_ts": entry_bar["ts"],
            "signal_start_gap_seconds": start_ts - entry_bar["ts"],
            "first_signature": first["signature"],
            "last_signature": last["signature"],
            "signatures": [row["signature"] for row in cluster],
            "pre_pool_hyusd": pre_hyusd,
            "pre_pool_xsol": pre_xsol,
            "post_pool_hyusd": post_hyusd,
            "post_pool_xsol": post_xsol,
            "trigger_size_pct_of_pool_hyusd": (hyusd_spent / pre_hyusd) * 100.0 if pre_hyusd else None,
            "trigger_size_pct_of_pool_value": (hyusd_spent / pre_pool_value) * 100.0 if pre_pool_value else None,
            "xsol_share_before_pct": xsol_share_before,
            "xsol_share_after_pct": xsol_share_after,
            "trigger_size_bucket": size_bucket((hyusd_spent / pre_pool_value) * 100.0 if pre_pool_value else None),
            "xsol_share_after_bucket": share_bucket(xsol_share_after),
        }

        for label, seconds in HORIZONS:
            pre_bar, _pre_idx = last_at_or_before(timestamps, bars, start_ts - seconds)
            target_ts = start_ts + seconds
            future_bar, future_idx = last_at_or_before(timestamps, bars, target_ts) if target_ts <= last_bar_ts else (None, -1)
            episode[f"pre_{label}_return_pct"] = pct_change(pre_bar["close"] if pre_bar else None, entry_close)
            episode[f"{label}_return_pct"] = pct_change(entry_close, future_bar["close"] if future_bar else None)
            if future_bar is not None and future_idx >= entry_idx:
                bars_slice = bars[entry_idx : future_idx + 1]
                max_runup, max_drawdown = runup_drawdown(entry_close, bars_slice)
            else:
                max_runup, max_drawdown = (None, None)
            episode[f"{label}_max_runup_pct"] = max_runup
            episode[f"{label}_max_drawdown_pct"] = max_drawdown

        start_24h_idx = first_at_or_after(timestamps, start_ts - 86400)
        prior_window = bars[start_24h_idx : entry_idx + 1]
        high_24h = max((bar["high"] for bar in prior_window), default=None)
        episode["drop_from_24h_high_pct"] = pct_change(high_24h, entry_close)
        episode["pre_drop_bucket"] = drop_bucket(episode["drop_from_24h_high_pct"])
        episodes.append(episode)

    summary = summarize_segment(episodes)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": tz_name,
        "gap_seconds": gap_seconds,
        "episode_count": len(episodes),
        "confirmed_buy_count": len(buys),
        "episodes": episodes,
        "overall": summary,
        "regimes": build_regime_segments(episodes),
        "notes": [
            "Episodes group confirmed buy_xsol transactions when consecutive buys are separated by 600 seconds or less.",
            "Forward returns are measured from the first confirmed buy in an episode against cached xSOL/USDC 5-minute market bars.",
            "7d metrics remain unavailable until the cached OHLC file extends far enough beyond an episode.",
            "Historical collateral ratio snapshots were not cached, so regime context uses public market drop, deployment size, pool composition shift, and whether the episode was the first activation of the day.",
        ],
    }


def summary_cards(report):
    overall = report["overall"]
    return [
        ("Confirmed Buys", str(report["confirmed_buy_count"]), "strictly confirmed buy_xsol rows"),
        ("Trigger Episodes", str(report["episode_count"]), f"gap <= {report['gap_seconds']}s"),
        ("1h Win Rate", fmt_pct(overall.get("1h_win_rate_pct")), "episodes with positive 1h return"),
        ("4h Median", fmt_pct(overall.get("4h_median_return_pct")), "median episode return"),
        ("24h Win Rate", fmt_pct(overall.get("24h_win_rate_pct")), "available windows only"),
        ("72h Median Run-up", fmt_pct(overall.get("72h_median_max_runup_pct")), "best move after trigger"),
    ]


def render_cards(report):
    rows = []
    for label, value, sub in summary_cards(report):
        rows.append(
            f"""
            <div class="card">
              <div class="label">{html.escape(label)}</div>
              <div class="value">{html.escape(value)}</div>
              <div class="subline">{html.escape(sub)}</div>
            </div>
            """
        )
    return "".join(rows)


def render_episode_rows(report):
    rows = []
    for row in report["episodes"]:
        rows.append(
            f"""
            <tr>
              <td>
                <div>{html.escape(row['start_local'][:19])}</div>
                <div class="subline">{html.escape(row['session_type'])}</div>
              </td>
              <td class="num">{row['event_count']}</td>
              <td class="num">{fmt_num(row['hyusd_spent'], 0)}</td>
              <td class="num">{fmt_num(row['xsol_bought'], 0)}</td>
              <td class="num">{fmt_num(row['trigger_size_pct_of_pool_value'])}%</td>
              <td class="num">{fmt_num(row['xsol_share_before_pct'])}% → {fmt_num(row['xsol_share_after_pct'])}%</td>
              <td class="num">{fmt_pct(row.get('pre_1h_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('drop_from_24h_high_pct'))}</td>
              <td class="num">{fmt_pct(row.get('15m_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('1h_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('4h_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('24h_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('24h_max_drawdown_pct'))}</td>
              <td class="num">{fmt_pct(row.get('24h_max_runup_pct'))}</td>
              <td><a href="https://solscan.io/tx/{html.escape(row['first_signature'])}">{html.escape(row['first_signature'][:10])}...</a></td>
            </tr>
            """
        )
    return "".join(rows)


def render_segment_table(title, segments):
    rows = []
    for label, info in segments.items():
        rows.append(
            f"""
            <tr>
              <td>{html.escape(label)}</td>
              <td class="num">{info['count']}</td>
              <td class="num">{fmt_num(info['total_hyusd_spent'], 0)}</td>
              <td class="num">{fmt_pct(info.get('1h_mean_return_pct'))}</td>
              <td class="num">{fmt_pct(info.get('4h_mean_return_pct'))}</td>
              <td class="num">{fmt_pct(info.get('24h_mean_return_pct'))}</td>
              <td class="num">{fmt_pct(info.get('1h_win_rate_pct'))}</td>
              <td class="num">{fmt_pct(info.get('24h_win_rate_pct'))}</td>
              <td class="num">{fmt_pct(info.get('24h_median_max_drawdown_pct'))}</td>
              <td class="num">{fmt_pct(info.get('24h_median_max_runup_pct'))}</td>
            </tr>
            """
        )
    return f"""
      <section class="panel">
        <h2>{html.escape(title)}</h2>
        <table>
          <thead>
            <tr>
              <th>Segment</th>
              <th>Episodes</th>
              <th>hyUSD Spent</th>
              <th>Mean 1h</th>
              <th>Mean 4h</th>
              <th>Mean 24h</th>
              <th>1h Win Rate</th>
              <th>24h Win Rate</th>
              <th>Median 24h Drawdown</th>
              <th>Median 24h Run-up</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </section>
    """


def render_html(report):
    segment_sections = [
        render_segment_table("Regime Segments: First Trigger Vs Follow-on", report["regimes"]["session_type"]),
        render_segment_table("Regime Segments: Trigger Size", report["regimes"]["trigger_size_bucket"]),
        render_segment_table("Regime Segments: Pre-trigger Drop", report["regimes"]["pre_drop_bucket"]),
        render_segment_table("Regime Segments: xSOL Share After Episode", report["regimes"]["xsol_share_after_bucket"]),
    ]
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in report["notes"])
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hylo Stability Pool Signal Report</title>
    <style>
      :root {{
        --bg: #0f1418;
        --panel: #171f26;
        --panel-alt: #1d2730;
        --border: #2f3b47;
        --text: #eef3f6;
        --muted: #98acb8;
        --accent: #d6b36e;
        --good: #4ed38a;
        --bad: #e07163;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--text);
        font-family: "Iowan Old Style", Georgia, serif;
        background:
          radial-gradient(circle at top right, rgba(214,179,110,0.14), transparent 28%),
          radial-gradient(circle at left center, rgba(78,211,138,0.08), transparent 34%),
          linear-gradient(180deg, #0d1215 0%, #090d10 100%);
      }}
      .wrap {{ max-width: 1320px; margin: 0 auto; padding: 34px 22px 44px; }}
      h1 {{ margin: 0 0 10px; font-size: 2.2rem; }}
      h2 {{ margin: 0 0 12px; font-size: 1.1rem; }}
      .sub {{ color: var(--muted); line-height: 1.55; max-width: 980px; }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
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
      .subline {{ color: var(--muted); font-size: 0.92rem; margin-top: 6px; }}
      .panel {{
        background: rgba(23,31,38,0.9);
        border: 1px solid var(--border);
        border-radius: 20px;
        padding: 20px;
        margin-bottom: 18px;
      }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 11px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        text-align: left;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
      a {{ color: #95d1f2; text-decoration: none; }}
      ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
      .foot {{ color: var(--muted); line-height: 1.5; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Hylo Stability Pool Signal Report</h1>
      <div class="sub">
        This report upgrades the monitor from raw lot tracking into a trigger study. Confirmed <code>buy_xsol</code> rows are grouped
        into activation episodes, then evaluated as tradable signals with forward return windows, drawdown/run-up context,
        and regime segmentation based on market drop, deployment size, and whether the episode was the first activation of the day.
      </div>

      <section class="grid">
        {render_cards(report)}
      </section>

      <section class="panel">
        <h2>Activation Episodes</h2>
        <table>
          <thead>
            <tr>
              <th>Episode Start</th>
              <th>Buys</th>
              <th>hyUSD Spent</th>
              <th>xSOL Bought</th>
              <th>% of Pool</th>
              <th>xSOL Share</th>
              <th>Pre 1h</th>
              <th>Drop From 24h High</th>
              <th>15m</th>
              <th>1h</th>
              <th>4h</th>
              <th>24h</th>
              <th>24h Max DD</th>
              <th>24h Max Run-up</th>
              <th>Tx</th>
            </tr>
          </thead>
          <tbody>{render_episode_rows(report)}</tbody>
        </table>
      </section>

      {''.join(segment_sections)}

      <section class="panel">
        <h2>Method Notes</h2>
        <ul>{notes}</ul>
      </section>
    </div>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build grouped trigger outcomes and regime segmentation for Stability Pool buys.")
    parser.add_argument(
        "--backfill",
        default="data/stability_pool_balance_changes_full.jsonl",
        help="Full stability-pool balance-change JSONL path.",
    )
    parser.add_argument(
        "--ohlcv",
        default="data/xsol_usdc_ohlcv_5m.json",
        help="xSOL/USDC OHLC JSON path.",
    )
    parser.add_argument(
        "--gap-seconds",
        default=600,
        type=int,
        help="Max seconds between buys to keep them in the same episode.",
    )
    parser.add_argument(
        "--timezone",
        default="America/Los_Angeles",
        help="Local timezone for display fields.",
    )
    parser.add_argument(
        "--json-out",
        default="data/stability_pool_signal_report.json",
        help="JSON output path.",
    )
    parser.add_argument(
        "--html-out",
        default="stability_pool_signal_report.html",
        help="HTML output path.",
    )
    args = parser.parse_args()

    report = analyze(
        load_jsonl(args.backfill),
        load_ohlcv(args.ohlcv),
        gap_seconds=args.gap_seconds,
        tz_name=args.timezone,
    )
    Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.html_out).write_text(render_html(report), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
