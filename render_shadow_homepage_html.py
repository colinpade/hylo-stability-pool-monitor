#!/usr/bin/env python3
import argparse
import html
import json
from datetime import datetime, timedelta
from pathlib import Path

from render_stability_pool_deployments_html import (
    build_shadow_replay,
    fmt_num,
    fmt_pct,
    format_pacific_date_parts,
    format_pacific_timestamp,
    json_for_script,
    load_json,
    load_jsonl,
    pnl_class,
)


BUY_HINTS = {"RebalanceStableToLever", "SwapStableToLever"}
SELL_HINTS = {"SwapLeverToStable"}


def parse_iso(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts)


def card(label, value, subtext="", tone="flat", value_id=None, subtext_id=None):
    value_attr = f' id="{html.escape(value_id)}"' if value_id else ""
    subtext_attr = f' id="{html.escape(subtext_id)}"' if subtext_id else ""
    return f"""
    <article class="metric-card">
      <div class="metric-label">{html.escape(label)}</div>
      <div class="metric-value {html.escape(tone)}"{value_attr}>{html.escape(value)}</div>
      <div class="metric-sub {html.escape(tone)}"{subtext_attr}>{html.escape(subtext)}</div>
    </article>
    """


def status_badge(label, tone="flat"):
    return f'<span class="status-badge {html.escape(tone)}">{html.escape(label)}</span>'


def load_confirmed_events(rows):
    confirmed = []
    for row in rows:
        action = row.get("action")
        hints = set(row.get("log_hints") or [])
        if action == "buy_xsol" and BUY_HINTS.issubset(hints):
            confirmed.append(row)
        elif action == "sell_xsol" and SELL_HINTS.issubset(hints):
            confirmed.append(row)
    confirmed.sort(
        key=lambda row: (
            row.get("slot") or 0,
            row.get("block_time") or 0,
            row.get("signature") or "",
        )
    )
    return confirmed


def build_sell_impact(shadow_replay, lots, sell_signature):
    lots_by_signature = {lot.get("signature"): lot for lot in lots if lot.get("signature")}
    impacted = []
    for entry in shadow_replay.get("entries") or []:
        for sig in entry.get("matched_signatures") or []:
            lot = lots_by_signature.get(sig)
            if not lot:
                continue
            if any(alloc.get("sell_signature") == sell_signature for alloc in (lot.get("sell_allocations") or [])):
                impacted.append(entry)
                break
    return impacted


def build_operator_state(signal_report, shadow_replay, confirmed_events, lots):
    now = parse_iso(signal_report.get("generated_at_utc"))
    delay_seconds = int((shadow_replay or {}).get("delay_seconds") or 0)
    pending = []
    for episode in signal_report.get("episodes") or []:
        start_dt = parse_iso(episode.get("start_utc"))
        if not start_dt or not now:
            continue
        entry_dt = start_dt + timedelta(seconds=delay_seconds)
        if entry_dt > now:
            pending.append(
                {
                    "episode": episode,
                    "entry_dt": entry_dt,
                    "seconds_remaining": int((entry_dt - now).total_seconds()),
                }
            )
    pending.sort(key=lambda row: row["entry_dt"])
    latest_event = confirmed_events[-1] if confirmed_events else None
    active_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") in {"open", "partial"}]
    closed_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") == "closed"]
    partial_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") == "partial"]

    if pending:
        soonest = pending[0]
        signal_day, signal_time = format_pacific_date_parts(soonest["episode"].get("start_utc"))
        entry_day, entry_time = format_pacific_date_parts(soonest["entry_dt"].isoformat())
        return {
            "tone": "flat",
            "eyebrow": "Timer Running",
            "headline": f"Next human entry opens in {soonest['seconds_remaining'] // 60}m",
            "detail": (
                f"Hylo confirmed a buy episode on {signal_day} at {signal_time}. "
                f"Earliest shadow entry is {entry_day} at {entry_time}."
            ),
            "bullets": [
                "Do not front-run the first buy.",
                "Buy one $1,000 xSOL tranche once the +10m minimum delay clears.",
                "Link the buy to the same activation episode, then hold until Hylo sells.",
            ],
        }

    if latest_event and latest_event.get("action") == "sell_xsol":
        impacted = build_sell_impact(shadow_replay, lots, latest_event.get("signature"))
        latest_time = format_pacific_timestamp(latest_event.get("utc"))
        closed_count = sum(1 for row in impacted if row.get("status") == "closed")
        partial_count = sum(1 for row in impacted if row.get("status") == "partial")
        return {
            "tone": "down",
            "eyebrow": "No Buy Right Now",
            "headline": "Hold the remaining shadow book and follow Hylo exits",
            "detail": (
                f"Latest confirmed Hylo action was a sell on {latest_time}. "
                f"{closed_count} shadow entries fully exited and {partial_count} were trimmed."
            ),
            "bullets": [
                f"{len(active_entries)} shadow entries are still live.",
                f"{len(closed_entries)} shadow entries are fully closed.",
                "Wait for a fresh confirmed Hylo buy before starting another +10m timer.",
            ],
        }

    latest_time = format_pacific_timestamp(latest_event.get("utc")) if latest_event else "n/a"
    return {
        "tone": "up" if active_entries else "flat",
        "eyebrow": "Operator State",
        "headline": (
            f"Hold {len(active_entries)} active shadow entries"
            if active_entries
            else "Watch only until Hylo buys again"
        ),
        "detail": (
            f"Most recent confirmed Hylo action was on {latest_time}. "
            "No fresh +10m buy timer is running right now."
        ),
        "bullets": [
            f"{len(active_entries)} active entries, {len(partial_entries)} partial, {len(closed_entries)} closed.",
            "The strategy is one $1,000 buy per episode, not per-transaction scaling.",
            "A new entry only starts after a new confirmed activation episode begins.",
        ],
    }


def build_primary_metrics(shadow_replay, latest_snapshot, current_buys):
    overall = shadow_replay.get("overall") or {}
    latest_mark_time = shadow_replay.get("mark_time_utc") or latest_snapshot.get("captured_at_utc")
    tranche_usd = shadow_replay.get("tranche_usd") or 0
    delay_minutes = int((shadow_replay.get("delay_seconds") or 0) / 60)
    cards = [
        card(
            "Shadow PnL",
            f"${fmt_num(overall.get('shadow_pnl_usd'))}",
            fmt_pct(overall.get("shadow_pnl_pct")),
            pnl_class(overall.get("shadow_pnl_usd")),
        ),
        card(
            "Shadow Capital",
            f"${fmt_num(overall.get('capital_deployed_usd'))}",
            f"${fmt_num(tranche_usd, 0)} per episode after +{delay_minutes}m",
        ),
        card(
            "Active Shadow Entries",
            str(overall.get("active_count", 0)),
            f"{overall.get('closed_count', 0)} closed • {overall.get('partial_count', 0)} partial",
            "up" if overall.get("active_count", 0) else "flat",
        ),
        card(
            "Shadow Equity",
            f"${fmt_num(overall.get('shadow_value_usd'))}",
            f"${fmt_num(overall.get('realized_value_usd'))} realized • ${fmt_num(overall.get('open_value_usd'))} still open",
        ),
        card(
            "Open Shadow xSOL",
            fmt_num(overall.get("remaining_xsol"), 2),
            "still live because Hylo still has inventory open",
        ),
        card(
            "Protocol xSOL Mark",
            fmt_num((shadow_replay or {}).get("mark_price"), 9),
            f"saved mark at {format_pacific_timestamp(latest_mark_time)}" if latest_mark_time else "saved mark",
            value_id="home-protocol-xsol",
        ),
        card(
            "Live xSOL Price",
            fmt_num((shadow_replay or {}).get("mark_price"), 9),
            "waiting for browser refresh",
            value_id="home-live-xsol",
            subtext_id="home-live-xsol-sub",
        ),
        card(
            "Latest SOL Price",
            "Loading...",
            "waiting for browser refresh",
            value_id="home-live-sol",
            subtext_id="home-live-sol-sub",
        ),
        card(
            "Hylo Buy Transactions",
            str(current_buys.get("buy_xsol_event_count", 0)),
            f"${fmt_num(current_buys.get('buy_xsol_total_hyusd_spent'))} deployed by Hylo in this tracked deployment",
        ),
    ]
    return "\n".join(cards)


def build_rules_panel():
    steps = [
        ("1", "Wait for a confirmed Hylo buy", "Only start a timer after the dashboard recognizes a confirmed activation episode."),
        ("2", "Respect the +10m minimum delay", "Your earliest entry is 10 minutes after the first buy in that episode. Later is acceptable if execution is slower."),
        ("3", "Buy exactly one $1,000 tranche", "Treat each episode as one fixed-size shadow position instead of scaling into every same-burst transaction."),
        ("4", "Exit only when Hylo exits", "Hold until Hylo sells the linked episode lots; partial sells mean partial shadow reductions."),
    ]
    items = []
    for num, title, copy in steps:
        items.append(
            f"""
            <div class="rule-step">
              <div class="rule-num">{num}</div>
              <div>
                <div class="rule-title">{html.escape(title)}</div>
                <div class="rule-copy">{html.escape(copy)}</div>
              </div>
            </div>
            """
        )
    return "\n".join(items)


def build_action_panel(operator_state, latest_event):
    latest_action = "No confirmed event yet"
    if latest_event:
        action_label = "BUY" if latest_event.get("action") == "buy_xsol" else "SELL"
        latest_action = f"{action_label} • {format_pacific_timestamp(latest_event.get('utc'))}"
    bullets = "".join(f"<li>{html.escape(line)}</li>" for line in operator_state.get("bullets") or [])
    return f"""
    <section class="action-panel {html.escape(operator_state.get('tone', 'flat'))}">
      <div class="action-eyebrow">{html.escape(operator_state.get('eyebrow', 'Operator State'))}</div>
      <h2>{html.escape(operator_state.get('headline', ''))}</h2>
      <p>{html.escape(operator_state.get('detail', ''))}</p>
      <div class="action-meta">
        <span>{status_badge(latest_action, operator_state.get('tone', 'flat'))}</span>
        <span>{status_badge("Shadow Hylo • $1,000 • 10m+ delay", "flat")}</span>
      </div>
      <ul class="action-list">{bullets}</ul>
    </section>
    """


def build_position_cards(entries, empty_copy):
    if not entries:
        return f'<div class="empty-state">{html.escape(empty_copy)}</div>'
    cards = []

    def order_key(row):
        entry_dt = parse_iso(row.get("entry_target_utc"))
        entry_ts = entry_dt.timestamp() if entry_dt else 0
        return (0 if row.get("status") == "partial" else 1, -entry_ts)

    ordered = sorted(
        entries,
        key=order_key,
    )
    for row in ordered:
        signal_day, signal_time = format_pacific_date_parts(row.get("start_utc"))
        entry_day, entry_time = format_pacific_date_parts(row.get("entry_target_utc"))
        tone = pnl_class(row.get("shadow_pnl_usd"))
        cards.append(
            f"""
            <article class="position-card">
              <div class="position-top">
                <div>
                  <div class="position-label">Signal</div>
                  <div class="position-main">{html.escape(signal_day)}</div>
                  <div class="position-sub">{html.escape(signal_time)}</div>
                </div>
                {status_badge(str(row.get('status', 'open')).title(), tone)}
              </div>
              <div class="position-grid">
                <div>
                  <div class="position-label">Earliest Human Entry</div>
                  <div class="position-main">{html.escape(entry_day)}</div>
                  <div class="position-sub">{html.escape(entry_time)}</div>
                </div>
                <div>
                  <div class="position-label">Shadow Equity</div>
                  <div class="position-main">${fmt_num(row.get('shadow_value_usd'))}</div>
                  <div class="position-sub">${fmt_num(row.get('realized_value_usd'))} realized</div>
                </div>
                <div>
                  <div class="position-label">Shadow PnL</div>
                  <div class="position-main {tone}">${fmt_num(row.get('shadow_pnl_usd'))}</div>
                  <div class="position-sub {tone}">{fmt_pct(row.get('shadow_pnl_pct'))}</div>
                </div>
                <div>
                  <div class="position-label">xSOL Still Live</div>
                  <div class="position-main">{fmt_num(row.get('remaining_xsol'), 2)}</div>
                  <div class="position-sub">{row.get('hylo_open_lot_count', 0)}/{row.get('hylo_lot_count', 0)} Hylo lots open</div>
                </div>
              </div>
              <div class="position-links">
                <a href="https://solscan.io/tx/{html.escape(row['first_signature'])}">Episode Tx</a>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def build_event_tape(events):
    if not events:
        return '<div class="empty-state">No confirmed Hylo buy or sell events are available yet.</div>'
    rows = []
    for row in reversed(events[-8:]):
        action = row.get("action")
        tone = "up" if action == "buy_xsol" else "down"
        amount = abs(float((row.get("xsol_pool") or {}).get("delta") or 0.0))
        hyusd = abs(float((row.get("hyusd_pool") or {}).get("delta") or 0.0))
        rows.append(
            f"""
            <article class="tape-row">
              <div class="tape-left">
                {status_badge('BUY' if action == 'buy_xsol' else 'SELL', tone)}
                <div>
                  <div class="position-main">{html.escape(format_pacific_timestamp(row.get('utc')))}</div>
                  <div class="position-sub">{html.escape(row.get('signature', '')[:14])}...</div>
                </div>
              </div>
              <div class="tape-right">
                <div><strong>{fmt_num(amount, 2)}</strong> xSOL</div>
                <div>${fmt_num(hyusd)}</div>
              </div>
            </article>
            """
        )
    return "\n".join(rows)


def render_html(lot_state, snapshots, signal_report, current_buys, event_rows):
    latest_snapshot = snapshots[-1] if snapshots else {}
    lots = latest_snapshot.get("lots") or lot_state.get("lots") or []
    shadow_replay = build_shadow_replay(lots, signal_report)
    confirmed_events = load_confirmed_events(event_rows)
    latest_event = confirmed_events[-1] if confirmed_events else None
    operator_state = build_operator_state(signal_report, shadow_replay, confirmed_events, lots)
    active_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") in {"open", "partial"}]
    reduced_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") in {"partial", "closed"}]
    live_payload = {
        "initial_xsol_price": latest_snapshot.get("xsol_price") or shadow_replay.get("mark_price"),
    }
    last_event_copy = "No confirmed Hylo buy or sell yet."
    if latest_event:
        event_side = "buy" if latest_event.get("action") == "buy_xsol" else "sell"
        last_event_copy = f"Latest confirmed Hylo {event_side}: {format_pacific_timestamp(latest_event.get('utc'))}"
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Shadow Hylo +10m</title>
    <style>
      :root {{
        --bg: #f3efe4;
        --ink: #162028;
        --muted: #5f6d72;
        --panel: #fffdf8;
        --panel-strong: #13232c;
        --border: #d9d0bf;
        --accent: #0f7a5a;
        --accent-soft: #d9efe5;
        --gold: #b88625;
        --red: #af4b3f;
        --shadow: 0 18px 40px rgba(20, 32, 40, 0.08);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(184,134,37,0.10), transparent 28%),
          radial-gradient(circle at right 20%, rgba(15,122,90,0.09), transparent 24%),
          linear-gradient(180deg, #f6f1e6 0%, #efe7d7 100%);
      }}
      .wrap {{ max-width: 1220px; margin: 0 auto; padding: 28px 18px 40px; }}
      .nav {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 20px;
      }}
      .brand {{
        font-family: "Iowan Old Style", Georgia, serif;
        font-size: 1.1rem;
        letter-spacing: 0.02em;
      }}
      .nav-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .nav-links a {{
        color: var(--ink);
        text-decoration: none;
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.6);
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 0.92rem;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.2fr 0.9fr;
        gap: 18px;
        margin-bottom: 20px;
      }}
      .hero-copy, .action-panel, .panel {{
        border: 1px solid var(--border);
        border-radius: 24px;
        background: var(--panel);
        box-shadow: var(--shadow);
      }}
      .hero-copy {{
        padding: 26px;
        background:
          linear-gradient(135deg, rgba(255,255,255,0.72), rgba(255,255,255,0.92)),
          linear-gradient(135deg, rgba(15,122,90,0.10), rgba(184,134,37,0.08));
      }}
      .eyebrow {{
        color: var(--accent);
        text-transform: uppercase;
        letter-spacing: 0.14em;
        font-size: 0.76rem;
        margin-bottom: 12px;
        font-weight: 700;
      }}
      h1, h2, h3 {{
        font-family: "Iowan Old Style", Georgia, serif;
        margin: 0;
      }}
      h1 {{
        font-size: clamp(2rem, 4vw, 3.5rem);
        line-height: 0.98;
        margin-bottom: 14px;
        max-width: 9.5em;
      }}
      .hero-copy p {{
        margin: 0;
        max-width: 56rem;
        line-height: 1.65;
        color: var(--muted);
        font-size: 1rem;
      }}
      .hero-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
      }}
      .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 0.88rem;
        border: 1px solid transparent;
        background: #ece6d7;
        color: var(--ink);
      }}
      .status-badge.up {{
        background: #ddf2e8;
        color: var(--accent);
        border-color: #bfdccc;
      }}
      .status-badge.down {{
        background: #f6dfda;
        color: var(--red);
        border-color: #e9c4bc;
      }}
      .status-badge.flat {{
        background: #efe8d8;
        color: #7b6125;
        border-color: #ddcfab;
      }}
      .action-panel {{
        padding: 24px;
        background: var(--panel-strong);
        color: #f5f1e8;
      }}
      .action-panel p,
      .action-panel .action-list,
      .action-panel .action-meta {{
        color: #d7e2e6;
      }}
      .action-panel.up .action-eyebrow {{ color: #90ddb9; }}
      .action-panel.down .action-eyebrow {{ color: #f1b7af; }}
      .action-panel.flat .action-eyebrow {{ color: #f2da9a; }}
      .action-eyebrow {{
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 12px;
        font-weight: 700;
      }}
      .action-panel h2 {{
        font-size: 1.8rem;
        line-height: 1.05;
        margin-bottom: 12px;
      }}
      .action-panel p {{
        line-height: 1.6;
        margin-bottom: 14px;
      }}
      .action-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 14px;
      }}
      .action-list {{
        margin: 0;
        padding-left: 18px;
        line-height: 1.55;
      }}
      .metric-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 0 0 20px;
      }}
      .metric-card {{
        border: 1px solid var(--border);
        border-radius: 18px;
        background: rgba(255,255,255,0.75);
        padding: 16px;
        box-shadow: var(--shadow);
      }}
      .metric-label {{
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        margin-bottom: 8px;
      }}
      .metric-value {{
        font-size: 1.55rem;
      }}
      .metric-sub {{
        margin-top: 6px;
        color: var(--muted);
        font-size: 0.92rem;
        line-height: 1.4;
      }}
      .up {{ color: var(--accent); }}
      .down {{ color: var(--red); }}
      .flat {{ color: inherit; }}
      .grid-two {{
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 18px;
        margin-bottom: 20px;
      }}
      .panel {{
        padding: 22px;
      }}
      .panel h3 {{
        font-size: 1.45rem;
        margin-bottom: 8px;
      }}
      .panel-copy {{
        color: var(--muted);
        line-height: 1.6;
        margin-bottom: 16px;
      }}
      .rule-list {{
        display: grid;
        gap: 14px;
      }}
      .rule-step {{
        display: grid;
        grid-template-columns: 42px 1fr;
        gap: 12px;
        align-items: start;
      }}
      .rule-num {{
        width: 42px;
        height: 42px;
        border-radius: 14px;
        background: var(--accent-soft);
        color: var(--accent);
        display: grid;
        place-items: center;
        font-weight: 700;
      }}
      .rule-title {{
        font-weight: 700;
        margin-bottom: 4px;
      }}
      .rule-copy {{
        color: var(--muted);
        line-height: 1.5;
      }}
      .section-head {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: end;
        margin-bottom: 16px;
      }}
      .section-note {{
        color: var(--muted);
        font-size: 0.95rem;
        line-height: 1.5;
      }}
      .positions-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 14px;
      }}
      .position-card {{
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
        background: rgba(255,255,255,0.72);
      }}
      .position-top {{
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: start;
        margin-bottom: 14px;
      }}
      .position-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px 12px;
      }}
      .position-label {{
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        margin-bottom: 4px;
      }}
      .position-main {{
        font-size: 1rem;
      }}
      .position-sub {{
        font-size: 0.9rem;
        color: var(--muted);
        margin-top: 4px;
      }}
      .position-links {{
        margin-top: 14px;
      }}
      .position-links a,
      .footer-links a {{
        color: var(--accent);
        text-decoration: none;
      }}
      .tape-list {{
        display: grid;
        gap: 10px;
      }}
      .tape-row {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid rgba(22,32,40,0.08);
      }}
      .tape-left {{
        display: flex;
        align-items: center;
        gap: 12px;
      }}
      .tape-right {{
        text-align: right;
        font-variant-numeric: tabular-nums;
      }}
      .empty-state {{
        border: 1px dashed var(--border);
        border-radius: 18px;
        padding: 18px;
        color: var(--muted);
        background: rgba(255,255,255,0.55);
      }}
      .footer-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px 16px;
        margin-top: 18px;
      }}
      .live-note {{
        color: var(--muted);
        font-size: 0.92rem;
        margin-top: 10px;
      }}
      @media (max-width: 920px) {{
        .hero,
        .grid-two {{
          grid-template-columns: 1fr;
        }}
      }}
      @media (max-width: 700px) {{
        .wrap {{ padding: 18px 12px 30px; }}
        .nav {{ align-items: flex-start; flex-direction: column; }}
        .position-grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <nav class="nav">
        <div class="brand">Shadow Hylo +10m</div>
        <div class="nav-links">
          <a href="v1.html">v1</a>
          <a href="stability_pool_signal_report.html">Research</a>
          <a href="current_buy_xsol_events.html">Current Buys</a>
          <a href="stability_pool_onchain_tracker.html">On-chain Tracker</a>
        </div>
      </nav>

      <section class="hero">
        <div class="hero-copy">
          <div class="eyebrow">Human Operator View</div>
          <h1>Shadow Hylo with one $1,000 buy after 10m+ delay.</h1>
          <p>
            This homepage is the human-execution version of the strategy. Wait at least 10 minutes after the first confirmed
            Hylo <code>buy_xsol</code> in an activation episode, buy one <strong>$1,000</strong> xSOL tranche, then stay in until
            Hylo sells that episode inventory. The old dense dashboard is still available as <a href="v1.html">v1</a>.
          </p>
          <div class="hero-meta">
            {status_badge(f"{shadow_replay.get('entry_count', 0)} shadow entries tracked", 'up' if shadow_replay.get('entry_count', 0) else 'flat')}
            {status_badge(last_event_copy, operator_state.get('tone', 'flat'))}
          </div>
          <div class="live-note" id="home-live-note">Waiting for live DexScreener pricing.</div>
        </div>
        {build_action_panel(operator_state, latest_event)}
      </section>

      <section class="metric-grid">
        {build_primary_metrics(shadow_replay, latest_snapshot, current_buys)}
      </section>

      <section class="grid-two">
        <section class="panel">
          <div class="section-head">
            <div>
              <h3>Current Shadow Book</h3>
              <div class="section-note">
                Active entries are the positions a human would still be carrying because Hylo has not fully sold the linked episode lots.
              </div>
            </div>
          </div>
          <div class="positions-grid">
            {build_position_cards(active_entries, "No active shadow entries right now.")}
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3>Execution Rules</h3>
              <div class="section-note">
                The homepage is meant to reduce the strategy to a few repeated operating rules instead of forcing you to parse the full research layout.
              </div>
            </div>
          </div>
          <div class="rule-list">
            {build_rules_panel()}
          </div>
        </section>
      </section>

      <section class="grid-two">
        <section class="panel">
          <div class="section-head">
            <div>
              <h3>Recently Closed Or Trimmed</h3>
              <div class="section-note">
                These are the shadow entries that Hylo has already reduced or fully exited.
              </div>
            </div>
          </div>
          <div class="positions-grid">
            {build_position_cards(reduced_entries, "Nothing has been trimmed or closed yet.")}
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3>Latest Hylo Tape</h3>
              <div class="section-note">
                Confirmed Stability Pool buys and sells, newest first. This is the raw tape you are shadowing.
              </div>
            </div>
          </div>
          <div class="tape-list">
            {build_event_tape(confirmed_events)}
          </div>
        </section>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h3>Useful Links</h3>
            <div class="section-note">
              Keep the homepage for operator decisions. Use the links below when you need raw detail or the original dashboard.
            </div>
          </div>
        </div>
        <div class="footer-links">
          <a href="v1.html">Open v1 dashboard</a>
          <a href="stability_pool_deployments.html">Raw deployment lots</a>
          <a href="stability_pool_signal_report.html">Signal research report</a>
          <a href="current_buy_xsol_events.html">Current buy event log</a>
          <a href="stability_pool_onchain_tracker.html">On-chain tracker</a>
        </div>
      </section>
    </div>
    <script id="shadow-home-live-state" type="application/json">{html.escape(json_for_script(live_payload), quote=False)}</script>
    <script>
      (() => {{
        const REFRESH_SECONDS = 60;
        const XSOL_TOKEN = "4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs";
        const SOL_TOKEN = "So11111111111111111111111111111111111111112";
        const payload = JSON.parse(document.getElementById("shadow-home-live-state").textContent);
        let countdown = REFRESH_SECONDS;
        let liveState = {{
          xsol: payload.initial_xsol_price,
          xsolSource: "saved mark",
          sol: null,
          solSource: "",
          lastUpdated: null,
          lastError: "",
        }};

        function formatNum(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          return Number(value).toLocaleString(undefined, {{
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
          }});
        }}

        function formatCurrency(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          return `$${{formatNum(value, digits)}}`;
        }}

        function setText(id, value) {{
          const el = document.getElementById(id);
          if (el) {{
            el.textContent = value;
          }}
        }}

        function bestPair(pairs, filterFn = null) {{
          const filtered = (pairs || []).filter((pair) => !filterFn || filterFn(pair));
          if (!filtered.length) {{
            return null;
          }}
          return filtered.sort((a, b) => Number(b?.liquidity?.usd || 0) - Number(a?.liquidity?.usd || 0))[0];
        }}

        async function fetchDexPrice(tokenMint, filterFn = null) {{
          const response = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${{tokenMint}}`, {{
            cache: "no-store",
          }});
          if (!response.ok) {{
            throw new Error(`DexScreener returned ${{response.status}}`);
          }}
          const data = await response.json();
          const pair = bestPair(data.pairs || [], filterFn);
          if (!pair || !pair.priceUsd) {{
            throw new Error("No liquid pair found");
          }}
          return {{
            price: Number(pair.priceUsd),
            dexId: pair.dexId || "dexscreener",
          }};
        }}

        function renderState() {{
          if (liveState.xsol) {{
            setText("home-live-xsol", formatNum(liveState.xsol, 9));
            setText("home-live-xsol-sub", `${{liveState.xsolSource}} • refresh in ${{countdown}}s`);
          }}
          if (liveState.sol) {{
            setText("home-live-sol", formatCurrency(liveState.sol));
            setText("home-live-sol-sub", `${{liveState.solSource}} • refresh in ${{countdown}}s`);
          }} else {{
            setText("home-live-sol", "Loading...");
            setText("home-live-sol-sub", `refresh in ${{countdown}}s`);
          }}
          if (liveState.lastUpdated) {{
            setText("home-live-note", `Live DexScreener prices updated. Next refresh in ${{countdown}}s.`);
          }} else if (liveState.lastError) {{
            setText("home-live-note", `Live refresh failed: ${{liveState.lastError}}. Retrying in ${{countdown}}s.`);
          }} else {{
            setText("home-live-note", `Waiting for live DexScreener pricing. Refresh every ${{REFRESH_SECONDS}}s.`);
          }}
        }}

        async function refreshPrices() {{
          try {{
            const [xsolResult, solResult] = await Promise.all([
              fetchDexPrice(XSOL_TOKEN),
              fetchDexPrice(
                SOL_TOKEN,
                (pair) => {{
                  const quote = pair?.quoteToken?.symbol;
                  return quote === "USDC" || quote === "USDT";
                }}
              ),
            ]);
            liveState = {{
              xsol: xsolResult.price,
              xsolSource: `DexScreener ${{xsolResult.dexId}}`,
              sol: solResult.price,
              solSource: `DexScreener ${{solResult.dexId}}`,
              lastUpdated: new Date(),
              lastError: "",
            }};
          }} catch (error) {{
            console.error(error);
            liveState.lastError = error?.message || "unknown error";
          }}
          countdown = REFRESH_SECONDS;
          renderState();
        }}

        renderState();
        refreshPrices();
        window.setInterval(() => {{
          countdown -= 1;
          if (countdown <= 0) {{
            refreshPrices();
            return;
          }}
          renderState();
        }}, 1000);
      }})();
    </script>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render the operator-focused Shadow Hylo homepage.")
    parser.add_argument("--lots", default="data/stability_pool_deployments.json", help="Deployment lot state JSON.")
    parser.add_argument("--marks", default="data/stability_pool_deployment_marks.jsonl", help="Deployment mark JSONL.")
    parser.add_argument("--signal-report", default="data/stability_pool_signal_report.json", help="Signal report JSON.")
    parser.add_argument("--current-buys", default="data/current_buy_xsol_events.json", help="Current buy summary JSON.")
    parser.add_argument("--events", default="data/stability_pool_balance_changes_full.jsonl", help="Backfill event JSONL.")
    parser.add_argument("--out", default="index.html", help="Output HTML path.")
    args = parser.parse_args()

    lot_state = load_json(args.lots)
    marks = load_jsonl(args.marks)
    signal_report = load_json(args.signal_report)
    current_buys = load_json(args.current_buys)
    event_rows = load_jsonl(args.events)
    Path(args.out).write_text(
        render_html(lot_state, marks, signal_report, current_buys, event_rows),
        encoding="utf-8",
    )
    print(args.out)


if __name__ == "__main__":
    main()
