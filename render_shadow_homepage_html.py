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


def short_signature(signature, chars=12):
    if not signature:
        return "n/a"
    if len(signature) <= chars:
        return signature
    return f"{signature[:chars]}..."


def pluralize(count, singular, plural=None):
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def build_entry_last_sell_utc(entry, lots_by_signature):
    latest = None
    for signature in entry.get("matched_signatures") or []:
        lot = lots_by_signature.get(signature) or {}
        for allocation in lot.get("sell_allocations") or []:
            sell_utc = allocation.get("sell_utc")
            if not sell_utc:
                continue
            if latest is None or parse_iso(sell_utc) > parse_iso(latest):
                latest = sell_utc
    return latest


def build_current_command(signal_report, shadow_replay, confirmed_events, lots):
    now = parse_iso(signal_report.get("generated_at_utc"))
    overall = shadow_replay.get("overall") or {}
    tranche_usd = shadow_replay.get("tranche_usd") or 0
    delay_minutes = int((shadow_replay.get("delay_seconds") or 0) / 60)
    entries = shadow_replay.get("entries") or []
    active_entries = [row for row in entries if row.get("status") in {"open", "partial"}]
    latest_event = confirmed_events[-1] if confirmed_events else None

    pending_entries = []
    if now:
        for row in entries:
            entry_dt = parse_iso(row.get("entry_target_utc"))
            if entry_dt and entry_dt > now:
                pending_entries.append((entry_dt, row))
    pending_entries.sort(key=lambda item: item[0])

    if pending_entries:
        entry_dt, row = pending_entries[0]
        signal_time = format_pacific_timestamp(row.get("start_utc"))
        entry_time = format_pacific_timestamp(entry_dt.isoformat())
        return {
            "tone": "flat",
            "status_label": "WAIT",
            "headline": f"Wait until {entry_time}.",
            "summary": f"Then buy ${fmt_num(tranche_usd, 0)} once.",
            "steps": [
                f"Set one timer for {entry_time}.",
                f"Buy ${fmt_num(tranche_usd, 0)} once.",
                "Hold until Hylo sells.",
            ],
            "facts": [
                f"{signal_time} trigger",
                f"${fmt_num(tranche_usd, 0)} size",
                f"{overall.get('active_count', 0)} still open",
            ],
            "phone_title": "Shadow buy timer running",
            "phone_body": f"Wait until {entry_time}. Then buy one ${fmt_num(tranche_usd, 0)} tranche.",
            "phone_timestamp": entry_time,
            "ack_label": "Mark timer set",
        }

    if latest_event and latest_event.get("action") == "sell_xsol":
        impacted = build_sell_impact(shadow_replay, lots, latest_event.get("signature"))
        latest_time = format_pacific_timestamp(latest_event.get("utc"))
        sold_xsol = abs(float((latest_event.get("xsol_pool") or {}).get("delta") or 0.0))
        hylo_remaining_xsol = sum(float(lot.get("remaining_xsol") or 0.0) for lot in lots)
        hylo_pre_sell_xsol = hylo_remaining_xsol + sold_xsol
        sold_pct_of_book = ((sold_xsol / hylo_pre_sell_xsol) * 100.0) if hylo_pre_sell_xsol > 0 else None
        closed_count = sum(1 for row in impacted if row.get("status") == "closed")
        partial_count = sum(1 for row in impacted if row.get("status") == "partial")
        sell_actions = []
        if closed_count:
            sell_actions.append(f"close {pluralize(closed_count, 'shadow entry', 'shadow entries')}")
        if partial_count:
            sell_actions.append(f"trim {pluralize(partial_count, 'shadow entry', 'shadow entries')}")
        sell_instruction = " and ".join(sell_actions) if sell_actions else "review the linked shadow entries"
        sell_brief_parts = []
        if closed_count:
            sell_brief_parts.append(f"close {closed_count}")
        if partial_count:
            sell_brief_parts.append(f"trim {partial_count}")
        sell_brief = ", ".join(sell_brief_parts).capitalize() if sell_brief_parts else "Review linked entries"
        return {
            "tone": "down",
            "status_label": "SELL",
            "headline": f"Sell now. {sell_brief}.",
            "summary": (
                f"Match Hylo's sell. No new buy. "
                f"{fmt_num(sold_pct_of_book, 2)}% of Hylo's tracked xSOL book."
                if sold_pct_of_book is not None
                else "Match Hylo's sell. No new buy."
            ),
            "steps": [
                f"{sell_brief}.",
                f"Keep {len(active_entries)} open.",
                "Wait for next buy.",
            ],
            "facts": [
                latest_time,
                f"{fmt_num(sold_xsol, 2)} xSOL sold",
                (
                    f"{fmt_num(sold_pct_of_book, 2)}% of Hylo xSOL book"
                    if sold_pct_of_book is not None
                    else "Sell size percentage unavailable"
                ),
                f"{overall.get('active_count', 0)} left open",
            ],
            "phone_title": "Hylo sold xSOL",
            "phone_body": (
                f"Sell now. {sell_brief}. {fmt_num(sold_pct_of_book, 2)}% of Hylo's tracked xSOL book."
                if sold_pct_of_book is not None
                else f"Sell now. {sell_brief}."
            ),
            "phone_timestamp": latest_time,
            "ack_label": "Mark sell done",
        }

    latest_time = format_pacific_timestamp(latest_event.get("utc")) if latest_event else "n/a"
    if active_entries:
        return {
            "tone": "up",
            "status_label": "HOLD",
            "headline": "Hold. No trade right now.",
            "summary": f"Keep {pluralize(len(active_entries), 'shadow entry', 'shadow entries')} open.",
            "steps": [
                "Do not add again.",
                "Sell only when Hylo sells.",
            ],
            "facts": [
                latest_time,
                f"{overall.get('active_count', 0)} active",
                f"Shadow PnL ${fmt_num(overall.get('shadow_pnl_usd'))}",
            ],
            "phone_title": "Hold the shadow book",
            "phone_body": f"Hold {pluralize(len(active_entries), 'shadow entry', 'shadow entries')}. No new trade.",
            "phone_timestamp": latest_time,
            "ack_label": "Mark reviewed",
        }

    return {
        "tone": "flat",
        "status_label": "WATCH",
        "headline": "Wait for the next Hylo buy.",
        "summary": "Nothing is live right now.",
        "steps": [
            f"Start a +{delay_minutes}m timer on the next buy.",
            f"Buy ${fmt_num(tranche_usd, 0)} once when it clears.",
        ],
        "facts": [
            "No timer",
            "No open shadow book",
            f"Buy size ${fmt_num(tranche_usd, 0)}",
        ],
        "phone_title": "Watch only",
        "phone_body": "No shadow action right now.",
        "phone_timestamp": "Waiting for trigger",
        "ack_label": "Mark checked",
    }


def build_command_center(command):
    facts_html = "".join(status_badge(item, "flat") for item in command.get("facts") or [])
    steps_html = "".join(f"<li>{html.escape(step)}</li>" for step in command.get("steps") or [])
    tone = command.get("tone", "flat")
    command_key = "|".join(
        [
            str(command.get("status_label") or ""),
            str(command.get("phone_timestamp") or ""),
            str(command.get("headline") or ""),
        ]
    )
    return f"""
    <section class="command-deck {html.escape(tone)}" id="command-deck">
      <div class="command-main">
        <div
          class="command-label"
          id="command-label"
          data-default-label="Do This Now"
          data-done-label="Handled Here"
        >Do This Now</div>
        <h1>{html.escape(command.get('headline', ''))}</h1>
        <p class="command-summary">{html.escape(command.get('summary', ''))}</p>
        <div class="command-facts">
          {status_badge(command.get('status_label', 'WATCH'), tone)}
          {facts_html}
        </div>
        <div class="command-checklist-shell">
          <div class="command-checklist-label">Next</div>
          <ul class="command-checklist">{steps_html}</ul>
        </div>
        <div class="command-ack-shell">
          <div class="command-ack-state" id="command-ack-state">Not marked done on this browser.</div>
          <div class="command-ack-actions">
            <button
              class="action-button primary"
              type="button"
              id="command-ack-button"
              data-command-key="{html.escape(command_key)}"
              data-ack-label="{html.escape(command.get('ack_label', 'Mark done'))}"
            >{html.escape(command.get('ack_label', 'Mark done'))}</button>
            <button class="action-button" type="button" id="command-ack-reset" hidden>Clear</button>
          </div>
        </div>
      </div>
      <aside class="alert-card" id="command-alert-card">
        <div
          class="alert-card-label"
          id="command-alert-label"
          data-default-label="Latest Actionable Alert"
          data-done-label="Latest Alert"
        >Latest Actionable Alert</div>
        <div class="phone-card {html.escape(tone)}" id="command-phone-card">
          <div class="phone-card-top">
            {status_badge(command.get('status_label', 'WATCH'), tone)}
            <span>{html.escape(command.get('phone_timestamp', ''))}</span>
          </div>
          <div class="phone-title">{html.escape(command.get('phone_title', ''))}</div>
          <div class="phone-body">{html.escape(command.get('phone_body', ''))}</div>
          <div
            class="phone-note"
            id="command-phone-note"
            data-default-note="Phone wording."
            data-done-note="Already handled on this browser."
          >Phone wording.</div>
        </div>
      </aside>
    </section>
    """


def build_active_table(entries):
    if not entries:
        return '<div class="empty-state">No active shadow entries right now.</div>'
    ordered = sorted(entries, key=lambda row: row.get("entry_target_utc") or "", reverse=True)
    rows = []
    for row in ordered:
        signal_day, signal_time = format_pacific_date_parts(row.get("start_utc"))
        entry_day, entry_time = format_pacific_date_parts(row.get("entry_target_utc"))
        pnl_tone = pnl_class(row.get("shadow_pnl_usd"))
        row_status = str(row.get("status") or "open").lower()
        status_tone = "down" if row_status == "partial" else "up"
        signal_ts = int(parse_iso(row.get("start_utc")).timestamp()) if parse_iso(row.get("start_utc")) else 0
        entry_ts = int(parse_iso(row.get("entry_target_utc")).timestamp()) if parse_iso(row.get("entry_target_utc")) else 0
        search_blob = " ".join(
            part
            for part in [
                signal_day,
                signal_time,
                entry_day,
                entry_time,
                row_status,
                row.get("first_signature") or "",
                short_signature(row.get("first_signature", ""), 10),
            ]
            if part
        ).lower()
        rows.append(
            f"""
            <tr
              data-signal-ts="{signal_ts}"
              data-status-rank="{0 if row_status == 'partial' else 1}"
              data-status="{html.escape(row_status)}"
              data-entry-ts="{entry_ts}"
              data-pnl="{float(row.get('shadow_pnl_usd') or 0.0)}"
              data-equity="{float(row.get('shadow_value_usd') or 0.0)}"
              data-remaining="{float(row.get('remaining_xsol') or 0.0)}"
              data-search="{html.escape(search_blob)}"
            >
              <td>
                <div class="cell-main">{html.escape(signal_day)}</div>
                <div class="cell-sub">{html.escape(signal_time)}</div>
              </td>
              <td>{status_badge(row_status.title(), status_tone)}</td>
              <td>
                <div class="cell-main">{html.escape(entry_day)}</div>
                <div class="cell-sub">{html.escape(entry_time)}</div>
              </td>
              <td class="num">
                <div class="cell-main {pnl_tone}">${fmt_num(row.get('shadow_pnl_usd'))}</div>
                <div class="cell-sub {pnl_tone}">{fmt_pct(row.get('shadow_pnl_pct'))}</div>
              </td>
              <td class="num">
                <div class="cell-main">${fmt_num(row.get('shadow_value_usd'))}</div>
                <div class="cell-sub">${fmt_num(row.get('realized_value_usd'))} realized</div>
              </td>
              <td class="num">
                <div class="cell-main">{fmt_num(row.get('remaining_xsol'), 2)}</div>
                <div class="cell-sub">xSOL still live</div>
              </td>
              <td class="num">
                <div class="cell-main">{row.get('hylo_open_lot_count', 0)}/{row.get('hylo_lot_count', 0)}</div>
                <div class="cell-sub">Hylo lots open</div>
              </td>
              <td>
                <a href="https://solscan.io/tx/{html.escape(row.get('first_signature', ''))}">{html.escape(short_signature(row.get('first_signature', ''), 10))}</a>
              </td>
            </tr>
            """
        )
    open_count = sum(1 for row in entries if str(row.get("status") or "").lower() == "open")
    partial_count = sum(1 for row in entries if str(row.get("status") or "").lower() == "partial")
    return f"""
    <div class="table-toolbar">
      <div class="filter-group" role="tablist" aria-label="Filter active shadow entries">
        <button class="filter-chip active" type="button" data-filter-status="all">All ({len(entries)})</button>
        <button class="filter-chip" type="button" data-filter-status="open">Open ({open_count})</button>
        <button class="filter-chip" type="button" data-filter-status="partial">Partial ({partial_count})</button>
      </div>
      <div class="toolbar-right">
        <label class="table-search">
          <span>Filter</span>
          <input id="active-shadow-search" type="search" placeholder="date, status, or tx">
        </label>
        <div class="table-count" id="active-filter-count">Showing {len(entries)} entries</div>
      </div>
    </div>
    <div class="table-wrap">
      <table class="operator-table" id="active-shadow-table">
        <thead>
          <tr>
            <th><button class="sort-button" type="button" data-sort-key="signal-ts" data-sort-type="number">Signal</button></th>
            <th><button class="sort-button" type="button" data-sort-key="status-rank" data-sort-type="number">Status</button></th>
            <th><button class="sort-button" type="button" data-sort-key="entry-ts" data-sort-type="number">Earliest Buy</button></th>
            <th class="num"><button class="sort-button" type="button" data-sort-key="pnl" data-sort-type="number">Shadow PnL</button></th>
            <th class="num"><button class="sort-button" type="button" data-sort-key="equity" data-sort-type="number">Shadow Equity</button></th>
            <th class="num"><button class="sort-button" type="button" data-sort-key="remaining" data-sort-type="number">xSOL Live</button></th>
            <th class="num">Hylo Lots</th>
            <th>Tx</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def build_recent_exits_table(entries, lots):
    if not entries:
        return '<div class="empty-state">No shadow entries have been trimmed or closed yet.</div>'
    lots_by_signature = {lot.get("signature"): lot for lot in lots if lot.get("signature")}
    ordered = sorted(
        entries,
        key=lambda row: build_entry_last_sell_utc(row, lots_by_signature) or row.get("closed_at_utc") or "",
        reverse=True,
    )
    rows = []
    for row in ordered:
        event_utc = row.get("closed_at_utc") or build_entry_last_sell_utc(row, lots_by_signature)
        event_day, event_time = format_pacific_date_parts(event_utc)
        status_tone = "down"
        pnl_tone = pnl_class(row.get("shadow_pnl_usd"))
        signal_day, signal_time = format_pacific_date_parts(row.get("start_utc"))
        rows.append(
            f"""
            <tr>
              <td>
                <div class="cell-main">{html.escape(signal_day)}</div>
                <div class="cell-sub">{html.escape(signal_time)}</div>
              </td>
              <td>{status_badge(str(row.get('status', 'closed')).title(), status_tone)}</td>
              <td>
                <div class="cell-main">{html.escape(event_day)}</div>
                <div class="cell-sub">{html.escape(event_time)}</div>
              </td>
              <td class="num">
                <div class="cell-main {pnl_tone}">${fmt_num(row.get('shadow_pnl_usd'))}</div>
                <div class="cell-sub {pnl_tone}">{fmt_pct(row.get('shadow_pnl_pct'))}</div>
              </td>
              <td class="num">
                <div class="cell-main">{fmt_num(row.get('remaining_xsol'), 2)}</div>
                <div class="cell-sub">xSOL still live</div>
              </td>
              <td>
                <a href="https://solscan.io/tx/{html.escape(row.get('first_signature', ''))}">{html.escape(short_signature(row.get('first_signature', ''), 10))}</a>
              </td>
            </tr>
            """
        )
    return f"""
    <div class="table-wrap">
      <table class="operator-table">
        <thead>
          <tr>
            <th>Signal</th>
            <th>Status</th>
            <th>Latest Sell</th>
            <th class="num">Shadow PnL</th>
            <th class="num">xSOL Live</th>
            <th>Tx</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def build_alert_log(shadow_replay, confirmed_events, lots):
    alerts = []
    tranche_usd = shadow_replay.get("tranche_usd") or 0
    for row in shadow_replay.get("entries") or []:
        signal_time = format_pacific_timestamp(row.get("start_utc"))
        entry_time = format_pacific_timestamp(row.get("entry_target_utc"))
        alerts.append(
            {
                "ts": row.get("start_utc"),
                "tone": "flat",
                "label": "WAIT",
                "title": "Wait for the +10m delay",
                "instruction": f"Hylo started a new buy episode. Do nothing until {entry_time}.",
                "detail": f"Signal began at {signal_time}.",
                "signature": row.get("first_signature"),
            }
        )
        alerts.append(
            {
                "ts": row.get("entry_target_utc"),
                "tone": "up",
                "label": "BUY",
                "title": f"Buy ${fmt_num(tranche_usd, 0)} xSOL",
                "instruction": f"The delay cleared. Buy one ${fmt_num(tranche_usd, 0)} shadow tranche and hold until Hylo sells.",
                "detail": f"{row.get('hylo_lot_count', 0)} linked Hylo lots in this episode.",
                "signature": row.get("first_signature"),
            }
        )

    for event in confirmed_events:
        if event.get("action") != "sell_xsol":
            continue
        impacted = build_sell_impact(shadow_replay, lots, event.get("signature"))
        if not impacted:
            continue
        sold_xsol = abs(float((event.get("xsol_pool") or {}).get("delta") or 0.0))
        received = float((event.get("hyusd_pool") or {}).get("delta") or 0.0)
        closed_count = sum(1 for row in impacted if row.get("status") == "closed")
        partial_count = sum(1 for row in impacted if row.get("status") == "partial")
        base_detail = f"{fmt_num(sold_xsol, 2)} xSOL sold • ${fmt_num(received)} hyUSD received"
        if partial_count:
            alerts.append(
                {
                    "ts": event.get("utc"),
                    "tone": "down",
                    "label": "TRIM",
                    "title": f"Trim {pluralize(partial_count, 'shadow entry', 'shadow entries')}",
                    "instruction": f"Hylo reduced exposure. Trim {pluralize(partial_count, 'shadow entry', 'shadow entries')} to stay aligned.",
                    "detail": base_detail,
                    "signature": event.get("signature"),
                }
            )
        if closed_count:
            alerts.append(
                {
                    "ts": event.get("utc"),
                    "tone": "down",
                    "label": "CLOSE",
                    "title": f"Close {pluralize(closed_count, 'shadow entry', 'shadow entries')}",
                    "instruction": f"Hylo fully exited {pluralize(closed_count, 'shadow entry', 'shadow entries')}. Close them.",
                    "detail": base_detail,
                    "signature": event.get("signature"),
                }
            )
        if not partial_count and not closed_count:
            alerts.append(
                {
                    "ts": event.get("utc"),
                    "tone": "down",
                    "label": "TRIM",
                    "title": "Review the shadow book",
                    "instruction": "Hylo sold xSOL. Review linked shadow entries and keep the book aligned.",
                    "detail": base_detail,
                    "signature": event.get("signature"),
                }
            )

    alerts.sort(key=lambda row: parse_iso(row.get("ts")) or datetime.min, reverse=True)
    return alerts


def build_alert_log_table(alerts):
    if not alerts:
        return '<div class="empty-state">No actionable alert history is available yet.</div>'
    rows = []
    for alert in alerts[:24]:
        day, time = format_pacific_date_parts(alert.get("ts"))
        source_link = ""
        if alert.get("signature"):
            source_link = (
                f'<a href="https://solscan.io/tx/{html.escape(alert["signature"])}">'
                f'{html.escape(short_signature(alert["signature"], 12))}</a>'
            )
        rows.append(
            f"""
            <article class="log-row">
              <div class="log-time">
                <div class="cell-main">{html.escape(day)}</div>
                <div class="cell-sub">{html.escape(time)}</div>
              </div>
              <div class="log-content">
                <div class="log-top">
                  {status_badge(alert.get('label', 'LOG'), alert.get('tone', 'flat'))}
                  <div class="log-title">{html.escape(alert.get('title', ''))}</div>
                </div>
                <div class="log-instruction">{html.escape(alert.get('instruction', ''))}</div>
                <div class="log-detail">
                  {html.escape(alert.get('detail', ''))}
                  {f' • {source_link}' if source_link else ''}
                </div>
              </div>
            </article>
            """
        )
    return f'<div class="log-list">{"".join(rows)}</div>'


def render_html(lot_state, snapshots, signal_report, current_buys, event_rows):
    latest_snapshot = snapshots[-1] if snapshots else {}
    lots = latest_snapshot.get("lots") or lot_state.get("lots") or []
    shadow_replay = build_shadow_replay(lots, signal_report)
    confirmed_events = load_confirmed_events(event_rows)
    active_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") in {"open", "partial"}]
    reduced_entries = [row for row in (shadow_replay.get("entries") or []) if row.get("status") in {"partial", "closed"}]
    command = build_current_command(signal_report, shadow_replay, confirmed_events, lots)
    alert_log = build_alert_log(shadow_replay, confirmed_events, lots)
    live_payload = {
        "initial_xsol_price": latest_snapshot.get("xsol_price") or shadow_replay.get("mark_price"),
    }
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Shadow Hylo Operator Home</title>
    <style>
      :root {{
        --bg: #091015;
        --bg-soft: #0e171d;
        --ink: #edf4f6;
        --muted: #92a2aa;
        --panel: #10191f;
        --panel-2: #142027;
        --panel-strong: #0b1217;
        --border: #21333c;
        --accent: #45d6a7;
        --accent-soft: #102b24;
        --gold: #f0c266;
        --red: #ff8f84;
        --shadow: 0 22px 50px rgba(0, 0, 0, 0.36);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(240,194,102,0.14), transparent 26%),
          radial-gradient(circle at right 10%, rgba(69,214,167,0.14), transparent 22%),
          linear-gradient(180deg, #091015 0%, #0d1419 42%, #0b1115 100%);
      }}
      .wrap {{ max-width: 1240px; margin: 0 auto; padding: 28px 18px 40px; }}
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
        background: rgba(255,255,255,0.03);
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 0.92rem;
      }}
      .nav-links a:hover {{
        border-color: rgba(69,214,167,0.4);
        background: rgba(69,214,167,0.08);
      }}
      .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 0.88rem;
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.04);
        color: var(--ink);
      }}
      .status-badge.up {{
        background: rgba(69,214,167,0.12);
        color: var(--accent);
        border-color: rgba(69,214,167,0.28);
      }}
      .status-badge.down {{
        background: rgba(255,143,132,0.12);
        color: var(--red);
        border-color: rgba(255,143,132,0.25);
      }}
      .status-badge.flat {{
        background: rgba(240,194,102,0.10);
        color: var(--gold);
        border-color: rgba(240,194,102,0.24);
      }}
      .command-deck {{
        display: grid;
        grid-template-columns: 1.35fr 0.85fr;
        gap: 18px;
        margin-bottom: 22px;
        border: 1px solid var(--border);
        border-radius: 32px;
        padding: 24px;
        box-shadow: var(--shadow);
        background:
          linear-gradient(135deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
          linear-gradient(135deg, rgba(69,214,167,0.12), rgba(240,194,102,0.10)),
          var(--panel-strong);
      }}
      .command-deck.up {{
        background:
          linear-gradient(135deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
          linear-gradient(135deg, rgba(69,214,167,0.18), rgba(240,194,102,0.08)),
          var(--panel-strong);
      }}
      .command-deck.down {{
        background:
          linear-gradient(135deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
          linear-gradient(135deg, rgba(255,143,132,0.18), rgba(240,194,102,0.06)),
          var(--panel-strong);
      }}
      .command-main {{
        padding-right: 8px;
      }}
      .command-label {{
        text-transform: uppercase;
        letter-spacing: 0.14em;
        font-size: 0.78rem;
        margin-bottom: 12px;
        font-weight: 700;
        color: var(--accent);
      }}
      .command-deck.down .command-label {{
        color: var(--red);
      }}
      h1, h2, h3 {{
        font-family: "Iowan Old Style", Georgia, serif;
        margin: 0;
      }}
      .command-main h1 {{
        font-size: clamp(2.4rem, 4.7vw, 4.5rem);
        line-height: 0.98;
        margin-bottom: 14px;
        max-width: 14ch;
      }}
      .command-summary {{
        margin: 0;
        max-width: 28rem;
        line-height: 1.35;
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .command-facts {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
        margin-bottom: 14px;
      }}
      .command-checklist-shell {{
        border-top: 1px solid rgba(255,255,255,0.08);
        padding-top: 12px;
      }}
      .command-checklist-label {{
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-size: 0.72rem;
        color: var(--muted);
        margin-bottom: 10px;
        font-weight: 700;
      }}
      .command-checklist {{
        margin: 0;
        padding-left: 20px;
        display: grid;
        gap: 6px;
        line-height: 1.35;
        font-size: 0.9rem;
      }}
      .command-ack-shell {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid rgba(255,255,255,0.08);
      }}
      .command-ack-state {{
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .command-ack-state.done {{
        color: var(--accent);
      }}
      .command-ack-actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }}
      .command-deck.acknowledged {{
        background:
          linear-gradient(135deg, rgba(255,255,255,0.015), rgba(255,255,255,0.008)),
          linear-gradient(135deg, rgba(146,162,170,0.08), rgba(146,162,170,0.04)),
          var(--panel);
        border-color: rgba(255,255,255,0.05);
        box-shadow: 0 14px 30px rgba(0, 0, 0, 0.18);
      }}
      .command-deck.acknowledged .command-label {{
        color: var(--muted);
      }}
      .command-deck.acknowledged .command-main h1,
      .command-deck.acknowledged .command-summary,
      .command-deck.acknowledged .command-facts,
      .command-deck.acknowledged .command-checklist-shell {{
        opacity: 0.58;
      }}
      .command-deck.acknowledged .status-badge {{
        filter: saturate(0.5);
      }}
      .command-ack-shell.done {{
        border-top-color: rgba(69,214,167,0.16);
      }}
      .action-button {{
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.03);
        color: var(--ink);
        border-radius: 999px;
        padding: 10px 14px;
        font: inherit;
        cursor: pointer;
      }}
      .action-button:hover {{
        border-color: rgba(69,214,167,0.4);
        background: rgba(69,214,167,0.08);
      }}
      .action-button.primary {{
        border-color: rgba(69,214,167,0.32);
        background: rgba(69,214,167,0.14);
      }}
      .action-button.subtle {{
        color: var(--muted);
      }}
      .alert-card {{
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 24px;
        background: rgba(5, 10, 13, 0.78);
        padding: 18px;
        color: var(--ink);
      }}
      .alert-card.acknowledged {{
        background: rgba(5, 10, 13, 0.46);
        border-color: rgba(255,255,255,0.05);
      }}
      .alert-card-label {{
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.76rem;
        margin-bottom: 12px;
        color: var(--gold);
        font-weight: 700;
      }}
      .phone-card {{
        border-radius: 22px;
        padding: 18px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
      }}
      .phone-card.up {{
        background: rgba(69,214,167,0.14);
        border-color: rgba(69,214,167,0.26);
      }}
      .phone-card.down {{
        background: rgba(255,143,132,0.14);
        border-color: rgba(255,143,132,0.24);
      }}
      .phone-card.acknowledged {{
        background: rgba(255,255,255,0.025) !important;
        border-color: rgba(255,255,255,0.05) !important;
        opacity: 0.7;
      }}
      .phone-card.acknowledged .status-badge {{
        filter: saturate(0.45);
      }}
      .phone-card-top {{
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        margin-bottom: 14px;
        color: #d7e2e6;
        font-size: 0.9rem;
      }}
      .phone-title {{
        font-size: 1.28rem;
        font-family: "Iowan Old Style", Georgia, serif;
        margin-bottom: 10px;
      }}
      .phone-body {{
        line-height: 1.6;
        color: var(--ink);
      }}
      .phone-note {{
        margin-top: 12px;
        color: var(--muted);
        font-size: 0.82rem;
      }}
      .panel {{
        border: 1px solid var(--border);
        border-radius: 24px;
        background: var(--panel);
        box-shadow: var(--shadow);
        padding: 22px;
        margin-bottom: 20px;
      }}
      .panel-head {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: end;
        margin-bottom: 16px;
      }}
      .panel h2 {{
        font-size: 1.5rem;
      }}
      .section-note {{
        color: var(--muted);
        font-size: 0.95rem;
        line-height: 1.55;
        max-width: 58rem;
      }}
      .table-wrap {{
        overflow-x: auto;
      }}
      .table-toolbar {{
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: center;
        margin-bottom: 14px;
        flex-wrap: wrap;
      }}
      .filter-group {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .filter-chip {{
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.03);
        color: var(--muted);
        border-radius: 999px;
        padding: 8px 12px;
        font: inherit;
        cursor: pointer;
      }}
      .filter-chip.active,
      .filter-chip:hover {{
        color: var(--ink);
        border-color: rgba(69,214,167,0.4);
        background: rgba(69,214,167,0.08);
      }}
      .toolbar-right {{
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
      }}
      .table-search {{
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .table-search input {{
        width: 220px;
        max-width: 100%;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.03);
        color: var(--ink);
        padding: 9px 12px;
        font: inherit;
      }}
      .table-search input::placeholder {{
        color: #72828b;
      }}
      .table-count {{
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .operator-table {{
        width: 100%;
        border-collapse: collapse;
      }}
      .operator-table th,
      .operator-table td {{
        padding: 12px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        vertical-align: top;
        text-align: left;
      }}
      .operator-table th {{
        color: var(--muted);
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        white-space: nowrap;
      }}
      .operator-table td.num,
      .operator-table th.num {{
        text-align: right;
      }}
      .operator-table tbody tr:hover {{
        background: rgba(69,214,167,0.05);
      }}
      .sort-button {{
        border: 0;
        background: none;
        padding: 0;
        font: inherit;
        color: inherit;
        cursor: pointer;
        text-transform: inherit;
        letter-spacing: inherit;
      }}
      .sort-button:hover {{
        color: var(--ink);
      }}
      .sort-button[data-direction="asc"]::after {{
        content: " ↑";
      }}
      .sort-button[data-direction="desc"]::after {{
        content: " ↓";
      }}
      .cell-main {{
        font-size: 0.98rem;
      }}
      .cell-sub {{
        font-size: 0.88rem;
        color: var(--muted);
        margin-top: 4px;
      }}
      .operator-table a,
      .footer-links a {{
        color: var(--accent);
        text-decoration: none;
      }}
      .log-list {{
        display: grid;
        gap: 14px;
      }}
      .log-row {{
        display: grid;
        grid-template-columns: 170px 1fr;
        gap: 16px;
        padding-bottom: 14px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }}
      .log-row:last-child {{
        border-bottom: 0;
        padding-bottom: 0;
      }}
      .log-content {{
        min-width: 0;
      }}
      .log-top {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }}
      .log-title {{
        font-weight: 700;
      }}
      .log-instruction {{
        line-height: 1.55;
        margin-bottom: 8px;
      }}
      .log-detail {{
        color: var(--muted);
        font-size: 0.9rem;
        line-height: 1.45;
      }}
      .metric-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 0 0 18px;
      }}
      .metric-card {{
        border: 1px solid var(--border);
        border-radius: 18px;
        background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));
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
        grid-template-columns: 1.02fr 0.98fr;
        gap: 18px;
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
      .details-shell {{
        border: 1px solid var(--border);
        border-radius: 24px;
        background: rgba(16,25,31,0.88);
        box-shadow: var(--shadow);
        overflow: hidden;
      }}
      .details-shell summary {{
        cursor: pointer;
        padding: 20px 22px;
        list-style: none;
        font-family: "Iowan Old Style", Georgia, serif;
        font-size: 1.35rem;
      }}
      .details-shell summary::-webkit-details-marker {{
        display: none;
      }}
      .details-body {{
        padding: 0 22px 22px;
      }}
      .empty-state {{
        border: 1px dashed var(--border);
        border-radius: 18px;
        padding: 18px;
        color: var(--muted);
        background: rgba(255,255,255,0.03);
      }}
      .footer-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px 16px;
      }}
      .live-note {{
        color: var(--muted);
        font-size: 0.92rem;
        margin-bottom: 16px;
      }}
      @media (max-width: 920px) {{
        .command-deck,
        .grid-two,
        .log-row {{
          grid-template-columns: 1fr;
        }}
      }}
      @media (max-width: 700px) {{
        .wrap {{ padding: 18px 12px 30px; }}
        .nav {{ align-items: flex-start; flex-direction: column; }}
        .command-deck {{ padding: 18px; }}
        .command-ack-shell,
        .command-ack-actions {{
          align-items: stretch;
        }}
        .details-body {{ padding: 0 14px 14px; }}
        .details-shell summary {{ padding: 16px 14px; }}
        .table-toolbar,
        .toolbar-right {{
          align-items: stretch;
        }}
        .table-search {{
          width: 100%;
        }}
        .table-search input {{
          width: 100%;
        }}
        .operator-table th,
        .operator-table td {{ padding: 10px 8px; }}
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

      {build_command_center(command)}

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>Current Shadow Book</h2>
            <div class="section-note">
              This is the live book a human should still be carrying. Filter it first, then sort by signal time, buy time, PnL, equity, or remaining xSOL.
            </div>
          </div>
        </div>
        {build_active_table(active_entries)}
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>Alert Log Over Time</h2>
            <div class="section-note">
              Phone-style operator history. Every alert is classified as WAIT, BUY, TRIM, or CLOSE so you can scan the tape faster.
            </div>
          </div>
        </div>
        {build_alert_log_table(alert_log)}
      </section>

      <details class="details-shell">
        <summary>Stats, recent exits, rules, and source links</summary>
        <div class="details-body">
          <div class="live-note" id="home-live-note">Waiting for live DexScreener pricing.</div>
          <section class="metric-grid">
            {build_primary_metrics(shadow_replay, latest_snapshot, current_buys)}
          </section>
          <section class="grid-two">
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h2>Recently Closed Or Trimmed</h2>
                  <div class="section-note">
                    Shadow entries Hylo has already reduced or fully exited.
                  </div>
                </div>
              </div>
              {build_recent_exits_table(reduced_entries, lots)}
            </section>
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h2>Execution Rules</h2>
                  <div class="section-note">
                    Keep the operator model simple: one episode, one $1,000 buy, then wait for Hylo's exit.
                  </div>
                </div>
              </div>
              <div class="rule-list">
                {build_rules_panel()}
              </div>
            </section>
          </section>
          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>Useful Links</h2>
                <div class="section-note">
                  Use these when you need research detail or the older dashboard instead of the operator view.
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
      </details>
    </div>
    <script id="shadow-home-live-state" type="application/json">{html.escape(json_for_script(live_payload), quote=False)}</script>
    <script>
      (() => {{
        const REFRESH_SECONDS = 60;
        const ACK_PREFIX = "shadow-home:ack:";
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

        function readStoredAck(storageKey) {{
          try {{
            return JSON.parse(window.localStorage.getItem(storageKey) || "null");
          }} catch (error) {{
            return null;
          }}
        }}

        function writeStoredAck(storageKey, value) {{
          try {{
            window.localStorage.setItem(storageKey, JSON.stringify(value));
          }} catch (error) {{
            console.error(error);
          }}
        }}

        function clearStoredAck(storageKey) {{
          try {{
            window.localStorage.removeItem(storageKey);
          }} catch (error) {{
            console.error(error);
          }}
        }}

        function formatAckTime(value) {{
          try {{
            return new Date(value).toLocaleString(undefined, {{
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
            }});
          }} catch (error) {{
            return value;
          }}
        }}

        function renderCommandAck() {{
          const button = document.getElementById("command-ack-button");
          const reset = document.getElementById("command-ack-reset");
          const state = document.getElementById("command-ack-state");
          const deck = document.getElementById("command-deck");
          const ackShell = document.querySelector(".command-ack-shell");
          const commandLabel = document.getElementById("command-label");
          const alertCard = document.getElementById("command-alert-card");
          const alertLabel = document.getElementById("command-alert-label");
          const phoneCard = document.getElementById("command-phone-card");
          const phoneNote = document.getElementById("command-phone-note");
          if (!button || !reset || !state) {{
            return;
          }}
          const storageKey = `${{ACK_PREFIX}}${{button.dataset.commandKey || ""}}`;
          const stored = readStoredAck(storageKey);
          if (stored?.doneAt) {{
            state.textContent = `Marked done here at ${{formatAckTime(stored.doneAt)}}.`;
            state.classList.add("done");
            ackShell?.classList.add("done");
            deck?.classList.add("acknowledged");
            alertCard?.classList.add("acknowledged");
            phoneCard?.classList.add("acknowledged");
            if (commandLabel) {{
              commandLabel.textContent = commandLabel.dataset.doneLabel || "Handled Here";
            }}
            if (alertLabel) {{
              alertLabel.textContent = alertLabel.dataset.doneLabel || "Latest Alert";
            }}
            if (phoneNote) {{
              phoneNote.textContent = phoneNote.dataset.doneNote || "Already handled on this browser.";
            }}
            reset.hidden = false;
            button.hidden = true;
            button.classList.remove("primary");
            reset.textContent = "Mark not done";
            reset.classList.add("subtle");
          }} else {{
            state.textContent = "Not marked done on this browser.";
            state.classList.remove("done");
            ackShell?.classList.remove("done");
            deck?.classList.remove("acknowledged");
            alertCard?.classList.remove("acknowledged");
            phoneCard?.classList.remove("acknowledged");
            if (commandLabel) {{
              commandLabel.textContent = commandLabel.dataset.defaultLabel || "Do This Now";
            }}
            if (alertLabel) {{
              alertLabel.textContent = alertLabel.dataset.defaultLabel || "Latest Actionable Alert";
            }}
            if (phoneNote) {{
              phoneNote.textContent = phoneNote.dataset.defaultNote || "Phone wording.";
            }}
            reset.hidden = true;
            button.hidden = false;
            button.textContent = button.dataset.ackLabel || "Mark done";
            button.classList.add("primary");
            reset.textContent = "Clear";
            reset.classList.remove("subtle");
          }}
        }}

        function sortActiveTable(key, direction, type) {{
          const table = document.getElementById("active-shadow-table");
          if (!table) {{
            return;
          }}
          const tbody = table.querySelector("tbody");
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((left, right) => {{
            const leftRaw = left.getAttribute(`data-${{key}}`) || "";
            const rightRaw = right.getAttribute(`data-${{key}}`) || "";
            let comparison = 0;
            if (type === "number") {{
              comparison = Number(leftRaw) - Number(rightRaw);
            }} else {{
              comparison = leftRaw.localeCompare(rightRaw);
            }}
            return direction === "asc" ? comparison : -comparison;
          }});
          rows.forEach((row) => tbody.appendChild(row));
        }}

        function applyActiveFilters() {{
          const table = document.getElementById("active-shadow-table");
          if (!table) {{
            return;
          }}
          const activeFilter = document.querySelector(".filter-chip.active")?.dataset.filterStatus || "all";
          const query = (document.getElementById("active-shadow-search")?.value || "").trim().toLowerCase();
          const rows = Array.from(table.querySelectorAll("tbody tr"));
          let visible = 0;
          rows.forEach((row) => {{
            const rowStatus = row.getAttribute("data-status") || "";
            const rowSearch = row.getAttribute("data-search") || "";
            const matchesStatus = activeFilter === "all" || rowStatus === activeFilter;
            const matchesQuery = !query || rowSearch.includes(query);
            const show = matchesStatus && matchesQuery;
            row.hidden = !show;
            if (show) {{
              visible += 1;
            }}
          }});
          const count = document.getElementById("active-filter-count");
          if (count) {{
            count.textContent = `Showing ${{visible}} entr${{visible === 1 ? "y" : "ies"}}`;
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

        document.querySelectorAll(".sort-button").forEach((button) => {{
          button.addEventListener("click", () => {{
            const current = button.dataset.direction === "asc" ? "asc" : "desc";
            const next = current === "asc" ? "desc" : "asc";
            document.querySelectorAll(".sort-button").forEach((other) => {{
              if (other !== button) {{
                other.dataset.direction = "";
              }}
            }});
            button.dataset.direction = next;
            sortActiveTable(button.dataset.sortKey, next, button.dataset.sortType || "string");
            applyActiveFilters();
          }});
        }});

        document.querySelectorAll(".filter-chip").forEach((button) => {{
          button.addEventListener("click", () => {{
            document.querySelectorAll(".filter-chip").forEach((other) => other.classList.remove("active"));
            button.classList.add("active");
            applyActiveFilters();
          }});
        }});

        const searchInput = document.getElementById("active-shadow-search");
        if (searchInput) {{
          searchInput.addEventListener("input", applyActiveFilters);
        }}

        const ackButton = document.getElementById("command-ack-button");
        const ackReset = document.getElementById("command-ack-reset");
        if (ackButton) {{
          ackButton.addEventListener("click", () => {{
            const storageKey = `${{ACK_PREFIX}}${{ackButton.dataset.commandKey || ""}}`;
            writeStoredAck(storageKey, {{ doneAt: new Date().toISOString() }});
            renderCommandAck();
          }});
        }}
        if (ackReset) {{
          ackReset.addEventListener("click", () => {{
            const storageKey = `${{ACK_PREFIX}}${{ackButton?.dataset.commandKey || ""}}`;
            clearStoredAck(storageKey);
            renderCommandAck();
          }});
        }}

        const defaultSortButton = document.querySelector('.sort-button[data-sort-key="entry-ts"]');
        if (defaultSortButton) {{
          defaultSortButton.dataset.direction = "desc";
          sortActiveTable("entry-ts", "desc", "number");
        }}
        applyActiveFilters();
        renderCommandAck();

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
