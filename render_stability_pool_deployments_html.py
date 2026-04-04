#!/usr/bin/env python3
import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_num(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_signed_num(value, digits=2):
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{digits}f}"


def fmt_pct(value, digits=2):
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def pct_change(a, b):
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def format_pacific_dt(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts).astimezone(PACIFIC_TZ)


def format_pacific_date_parts(ts):
    dt = format_pacific_dt(ts)
    if not dt:
        return "n/a", ""
    day_label = f"{dt.strftime('%b')} {dt.day}"
    time_label = f"{dt.strftime('%I:%M %p').lstrip('0')} {dt.tzname()}"
    return day_label, time_label


def format_pacific_timestamp(ts):
    dt = format_pacific_dt(ts)
    if not dt:
        return "n/a"
    return f"{dt.strftime('%b')} {dt.day}, {dt.strftime('%I:%M %p').lstrip('0')} {dt.tzname()}"


def day_key_for_ts(ts):
    dt = format_pacific_dt(ts)
    if not dt:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def day_label_for_ts(ts):
    dt = format_pacific_dt(ts)
    if not dt:
        return "Unknown Day"
    return f"{dt.strftime('%b')} {dt.day} {dt.tzname()}"


def pnl_class(value):
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def json_for_script(payload):
    return json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")


def card(label, value, subtext, tone="flat", card_id=None, value_id=None, subtext_id=None):
    card_attr = f' id="{html.escape(card_id)}"' if card_id else ""
    value_attr = f' id="{html.escape(value_id)}"' if value_id else ""
    subtext_attr = f' id="{html.escape(subtext_id)}"' if subtext_id else ""
    return f"""
    <div class="card"{card_attr}>
      <div class="card-label">{html.escape(label)}</div>
      <div class="card-value {html.escape(tone)}"{value_attr}>{html.escape(value)}</div>
      <div class="card-sub {html.escape(tone)}"{subtext_attr}>{html.escape(subtext)}</div>
    </div>
    """


def build_cards(lot_state, latest_snapshot):
    summary = latest_snapshot["summary"] if latest_snapshot else {}
    cards = [
        card(
            "Deployments",
            str(lot_state.get("deployment_count", 0)),
            "confirmed buy_xsol lots",
            card_id="card-deployments",
            value_id="summary-deployment-count",
        )
    ]
    if latest_snapshot:
        cards.extend(
            [
                card(
                    "Open Deployments",
                    str(summary["open_deployment_count"]),
                    format_pacific_timestamp(
                        latest_snapshot.get("captured_at_utc") or latest_snapshot.get("captured_at_local")
                    ),
                    card_id="card-open-deployments",
                    value_id="summary-open-deployment-count",
                    subtext_id="summary-open-deployment-sub",
                ),
                card(
                    "Protocol xSOL NAV",
                    fmt_num(latest_snapshot["xsol_price"], 9),
                    latest_snapshot["price_source"],
                    card_id="card-protocol-xsol-price",
                    value_id="summary-protocol-xsol-price",
                    subtext_id="summary-protocol-xsol-price-sub",
                ),
                card(
                    "Live xSOL Price",
                    fmt_num(latest_snapshot["xsol_price"], 9),
                    "waiting for browser market refresh",
                    card_id="card-live-xsol-price",
                    value_id="summary-live-xsol-price",
                    subtext_id="summary-live-xsol-price-sub",
                ),
                card(
                    "Remaining xSOL",
                    fmt_num(summary["total_remaining_xsol"], 6),
                    "open lot exposure",
                    card_id="card-remaining-xsol",
                    value_id="summary-remaining-xsol",
                    subtext_id="summary-remaining-xsol-sub",
                ),
                card(
                    "Entry Value",
                    f"${fmt_num(summary['total_entry_value'])}",
                    "total deployed hyUSD",
                    card_id="card-entry-value",
                    value_id="summary-entry-value",
                    subtext_id="summary-entry-value-sub",
                ),
                card(
                    "Protocol NAV Value",
                    f"${fmt_num(summary['total_current_value'])}",
                    "latest saved Hylo protocol mark",
                    card_id="card-protocol-nav-value",
                    value_id="summary-protocol-nav-value",
                    subtext_id="summary-protocol-nav-value-sub",
                ),
                card(
                    "Protocol NAV PnL",
                    f"${fmt_num(summary['total_net_pnl'])}",
                    fmt_pct(summary["total_net_pnl_pct"]),
                    pnl_class(summary["total_net_pnl"]),
                    card_id="card-protocol-nav-pnl",
                    value_id="summary-protocol-nav-pnl",
                    subtext_id="summary-protocol-nav-pnl-sub",
                ),
                card(
                    "Live Market Value",
                    f"${fmt_num(summary['total_current_value'])}",
                    "browser market mark",
                    card_id="card-live-market-value",
                    value_id="summary-live-market-value",
                    subtext_id="summary-live-market-value-sub",
                ),
                card(
                    "Live Market PnL",
                    f"${fmt_num(summary['total_net_pnl'])}",
                    fmt_pct(summary["total_net_pnl_pct"]),
                    pnl_class(summary["total_net_pnl"]),
                    card_id="card-live-market-pnl",
                    value_id="summary-live-market-pnl",
                    subtext_id="summary-live-market-pnl-sub",
                ),
                card(
                    "Latest SOL Price",
                    "Loading...",
                    "browser market refresh every 60s",
                    card_id="card-sol-price",
                    value_id="summary-sol-price",
                    subtext_id="summary-sol-price-sub",
                ),
            ]
        )
    return "\n".join(cards)


def build_lot_rows(lots):
    rows = []
    for lot in sorted(lots, key=lambda row: row["block_time"] or 0, reverse=True):
        day_label, time_label = format_pacific_date_parts(lot.get("utc") or lot.get("local"))
        current_price = lot.get("current_price")
        current_value = lot.get("current_value")
        net_pnl = lot.get("net_pnl")
        row_class = pnl_class(net_pnl)
        rows.append(
            f"""
            <tr data-lot-id="{html.escape(lot['lot_id'])}">
              <td>
                <div class="date-main">{html.escape(day_label)}</div>
                <div class="date-sub">{html.escape(time_label)}</div>
              </td>
              <td class="num">
                <div>{fmt_num(lot['xsol_bought'], 2)}</div>
                <div class="subline">{html.escape(lot['status'])}</div>
              </td>
              <td class="num">${fmt_num(lot['entry_price'], 6)}</td>
              <td class="num">${fmt_num(lot['entry_value'])}</td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-current-price">${fmt_num(current_price, 6) if current_price is not None else 'n/a'}</span></td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-current-value">${fmt_num(current_value)}</span></td>
              <td class="num">
                <div id="{html.escape(lot['lot_id'])}-net-pnl" class="{row_class}">${fmt_num(net_pnl)}</div>
                <div id="{html.escape(lot['lot_id'])}-net-pnl-pct" class="subline {row_class}">{fmt_pct(lot.get('net_pnl_pct'))}</div>
              </td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-days-held">{html.escape(lot.get('days_held_display', 'n/a'))}</span></td>
              <td><a href="{html.escape(lot['solscan_url'])}">{html.escape(lot['signature'][:10])}...</a></td>
            </tr>
            """
        )
    return "\n".join(rows)


def enrich_lots_for_display(lots):
    enriched = []
    for lot in lots:
        row = dict(lot)
        ts = row.get("utc") or row.get("local")
        row["day_key"] = day_key_for_ts(ts)
        row["day_label"] = day_label_for_ts(ts)
        enriched.append(row)
    return enriched


def build_lot_day_groups(lots):
    groups = []
    by_day = {}
    for lot in sorted(lots, key=lambda row: row["block_time"] or 0, reverse=True):
        day_key = lot["day_key"]
        bucket = by_day.setdefault(
            day_key,
            {
                "day_key": day_key,
                "day_label": lot["day_label"],
                "lots": [],
                "count": 0,
                "xsol_bought": 0.0,
                "entry_value": 0.0,
                "current_value": 0.0,
                "net_pnl": 0.0,
            },
        )
        if bucket["count"] == 0:
            groups.append(bucket)
        bucket["lots"].append(lot)
        bucket["count"] += 1
        bucket["xsol_bought"] += float(lot.get("xsol_bought") or 0.0)
        bucket["entry_value"] += float(lot.get("entry_value") or 0.0)
        bucket["current_value"] += float(lot.get("current_value") or 0.0)
        bucket["net_pnl"] += float(lot.get("net_pnl") or 0.0)

    sections = []
    for index, group in enumerate(groups):
        day_key = group["day_key"]
        pnl_pct = (
            (group["net_pnl"] / group["entry_value"]) * 100.0
            if group["entry_value"] > 0
            else None
        )
        sections.append(
            f"""
            <details class="day-group" data-day-key="{html.escape(day_key)}" {"open" if index == 0 else ""}>
              <summary>
                <div class="day-summary-heading">{html.escape(group['day_label'])}</div>
                <div class="day-summary-metrics">
                  <span><strong id="day-{html.escape(day_key)}-count">{group['count']}</strong> lots</span>
                  <span><strong id="day-{html.escape(day_key)}-xsol">{fmt_num(group['xsol_bought'], 2)}</strong> xSOL</span>
                  <span><strong id="day-{html.escape(day_key)}-entry">${fmt_num(group['entry_value'])}</strong> entry</span>
                  <span><strong id="day-{html.escape(day_key)}-current">${fmt_num(group['current_value'])}</strong> live</span>
                  <span class="{pnl_class(group['net_pnl'])}">
                    <strong id="day-{html.escape(day_key)}-pnl">${fmt_num(group['net_pnl'])}</strong>
                    <span id="day-{html.escape(day_key)}-pnl-pct">{fmt_pct(pnl_pct)}</span>
                  </span>
                </div>
              </summary>
              <div class="day-group-table">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Amount</th>
                      <th>Entry Price</th>
                      <th>Entry Value</th>
                      <th>Live Price</th>
                      <th>Live Value</th>
                      <th>Live PnL</th>
                      <th>Days Held</th>
                      <th>Tx</th>
                    </tr>
                  </thead>
                  <tbody>
                    {build_lot_rows(group['lots'])}
                  </tbody>
                </table>
              </div>
            </details>
            """
        )
    return "\n".join(sections)


def build_strategy_cards(signal_report):
    replay = (signal_report or {}).get("tranche_replay") or {}
    overall = replay.get("overall") or {}
    if not replay:
        return ""
    cards = [
        card(
            "Replay Signals",
            str(replay.get("entry_count", 0)),
            f"${fmt_num(replay.get('tranche_usd', 0), 0)} xSOL buys at +{int((replay.get('delay_seconds') or 0) / 60)}m",
        ),
        card(
            "Replay Capital",
            f"${fmt_num(overall.get('capital_deployed_usd'))}",
            "fixed notional deployed",
        ),
        card(
            "Replay Marked Value",
            f"${fmt_num(overall.get('marked_value_usd'))}",
            "latest cached xSOL close",
        ),
        card(
            "Replay Marked PnL",
            f"${fmt_num(overall.get('marked_pnl_usd'))}",
            fmt_pct(overall.get("marked_pnl_pct")),
            pnl_class(overall.get("marked_pnl_usd")),
        ),
        card(
            "Replay 24h Mean",
            fmt_pct(overall.get("24h_mean_return_pct")),
            "from delayed entry",
        ),
        card(
            "Replay 24h Win Rate",
            fmt_pct(overall.get("24h_win_rate_pct")),
            "available windows only",
        ),
    ]
    return "\n".join(cards)


def build_strategy_rows(entries):
    rows = []
    for row in sorted(entries, key=lambda item: item.get("entry_target_utc") or "", reverse=True):
        signal_day, signal_time = format_pacific_date_parts(row.get("start_utc") or row.get("start_local"))
        entry_day, entry_time = format_pacific_date_parts(row.get("entry_target_utc") or row.get("entry_target_local"))
        marked_pnl = row.get("marked_pnl_usd")
        tone = pnl_class(marked_pnl)
        rows.append(
            f"""
            <tr>
              <td>
                <div class="date-main">{html.escape(signal_day)}</div>
                <div class="date-sub">{html.escape(signal_time)}</div>
              </td>
              <td>
                <div class="date-main">{html.escape(entry_day)}</div>
                <div class="date-sub">{html.escape(entry_time)}</div>
              </td>
              <td class="num">${fmt_num(row.get('tranche_usd'), 0)}</td>
              <td class="num">{fmt_num(row.get('xsol_acquired'), 2)}</td>
              <td class="num">${fmt_num(row.get('entry_price'), 6)}</td>
              <td class="num">${fmt_num(row.get('marked_value_usd'))}</td>
              <td class="num">
                <div class="{tone}">${fmt_num(marked_pnl)}</div>
                <div class="subline {tone}">{fmt_pct(row.get('marked_pnl_pct'))}</div>
              </td>
              <td class="num">{fmt_pct(row.get('24h_return_pct'))}</td>
              <td><a href="https://solscan.io/tx/{html.escape(row['first_signature'])}">{html.escape(row['first_signature'][:10])}...</a></td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_strategy_day_groups(signal_report):
    replay = (signal_report or {}).get("tranche_replay") or {}
    entries = replay.get("entries") or []
    if not entries:
        return '<div class="foot">No confirmed signal-replay entries have been generated yet.</div>'

    groups = []
    by_day = {}
    for row in sorted(entries, key=lambda item: item.get("entry_target_utc") or "", reverse=True):
        day_key = day_key_for_ts(row.get("entry_target_utc") or row.get("entry_target_local"))
        bucket = by_day.setdefault(
            day_key,
            {
                "day_key": day_key,
                "day_label": day_label_for_ts(row.get("entry_target_utc") or row.get("entry_target_local")),
                "entries": [],
                "count": 0,
                "capital": 0.0,
                "xsol": 0.0,
                "marked_value": 0.0,
                "marked_pnl": 0.0,
            },
        )
        if bucket["count"] == 0:
            groups.append(bucket)
        bucket["entries"].append(row)
        bucket["count"] += 1
        bucket["capital"] += float(row.get("tranche_usd") or 0.0)
        bucket["xsol"] += float(row.get("xsol_acquired") or 0.0)
        bucket["marked_value"] += float(row.get("marked_value_usd") or 0.0)
        bucket["marked_pnl"] += float(row.get("marked_pnl_usd") or 0.0)

    sections = []
    for index, group in enumerate(groups):
        pnl_pct = ((group["marked_pnl"] / group["capital"]) * 100.0) if group["capital"] else None
        sections.append(
            f"""
            <details class="day-group" data-strategy-day-key="{html.escape(group['day_key'])}" {"open" if index == 0 else ""}>
              <summary>
                <div class="day-summary-heading">{html.escape(group['day_label'])}</div>
                <div class="day-summary-metrics">
                  <span><strong>{group['count']}</strong> buys</span>
                  <span><strong>${fmt_num(group['capital'])}</strong> deployed</span>
                  <span><strong>{fmt_num(group['xsol'], 2)}</strong> xSOL</span>
                  <span><strong>${fmt_num(group['marked_value'])}</strong> marked</span>
                  <span class="{pnl_class(group['marked_pnl'])}">
                    <strong>${fmt_num(group['marked_pnl'])}</strong>
                    <span>{fmt_pct(pnl_pct)}</span>
                  </span>
                </div>
              </summary>
              <div class="day-group-table">
                <table>
                  <thead>
                    <tr>
                      <th>Signal Start</th>
                      <th>Hyp Entry</th>
                      <th>Tranche</th>
                      <th>xSOL Bought</th>
                      <th>Entry Price</th>
                      <th>Marked Value</th>
                      <th>Marked PnL</th>
                      <th>24h</th>
                      <th>Tx</th>
                    </tr>
                  </thead>
                  <tbody>
                    {build_strategy_rows(group['entries'])}
                  </tbody>
                </table>
              </div>
            </details>
            """
        )
    return "\n".join(sections)


def build_signal_setup_cards(signal_report):
    live = (signal_report or {}).get("live_setup_summary") or {}
    top = live.get("top_active_setup")
    policy = live.get("alert_policy") or {}
    min_score = policy.get("min_setup_score", 52.0)
    min_confidence = policy.get("min_confidence_score", 45.0)
    if not top:
        return (
            "\n".join(
                [
                    card("Active Setups", "0", "no unresolved ranked episodes"),
                    card(
                        "Eligible Alerts",
                        "0",
                        f"score >= {fmt_num(min_score, 0)} and confidence >= {fmt_num(min_confidence, 0)}",
                    ),
                ]
            ),
            [],
        )
    cards = [
        card(
            "Active Setups",
            str(live.get("active_count", 0)),
            "unresolved episodes still in play",
        ),
        card(
            "Eligible Alerts",
            str(live.get("alert_eligible_count", 0)),
            f"score >= {fmt_num(min_score, 0)} and confidence >= {fmt_num(min_confidence, 0)}",
            tone=("up" if live.get("alert_eligible_count", 0) > 0 else "flat"),
        ),
        card(
            "Top Setup Grade",
            str(top.get("setup_grade", "Unscored")),
            top.get("setup_headline", "n/a"),
            tone=("up" if top.get("setup_grade") in {"A", "B"} else "flat"),
        ),
        card(
            "Top Setup Score",
            fmt_num(top.get("setup_score")),
            top.get("setup_confidence_bucket", "n/a"),
        ),
        card(
            "Expected 24h",
            fmt_pct(top.get("setup_expected_24h_return_pct")),
            top.get("alert_status", "n/a"),
            tone=("up" if top.get("alert_eligible") else pnl_class(top.get("setup_expected_24h_return_pct"))),
        ),
    ]
    return "\n".join(cards), live.get("active_setups", [])


def build_live_setup_rows(signal_report):
    _cards_html, rows = build_signal_setup_cards(signal_report)
    if not rows:
        return '<div class="foot">No unresolved ranked setups right now.</div>'
    body = []
    for row in rows:
        tone = "up" if row.get("alert_eligible") else ("flat" if row.get("setup_score") is not None else "down")
        day_label, time_label = format_pacific_date_parts(row.get("start_utc") or row.get("start_local"))
        body.append(
            f"""
            <tr>
              <td>
                <div class="date-main">{html.escape(day_label)}</div>
                <div class="date-sub">{html.escape(time_label)}</div>
              </td>
              <td class="num"><span class="{tone}">{html.escape(str(row.get('setup_grade', 'Unscored')))}</span></td>
              <td class="num">{fmt_num(row.get('setup_score')) if row.get('setup_score') is not None else 'n/a'}</td>
              <td class="num">{fmt_pct(row.get('setup_expected_24h_return_pct'))}</td>
              <td class="num">{fmt_pct(row.get('setup_expected_24h_win_rate_pct'))}</td>
              <td>
                <div class="{tone}">{html.escape(str(row.get('alert_status', 'n/a')))}</div>
                <div class="subline">{html.escape(str(row.get('alert_reason', '')))}</div>
              </td>
              <td class="num">{html.escape(str(row.get('setup_training_episode_count', 0)))}</td>
              <td><a href="https://solscan.io/tx/{html.escape(row['first_signature'])}">{html.escape(row['first_signature'][:10])}...</a></td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>Signal Start</th>
          <th>Grade</th>
          <th>Score</th>
          <th>Expected 24h</th>
          <th>Expected Win Rate</th>
          <th>Alert Status</th>
          <th>Training Episodes</th>
          <th>Tx</th>
        </tr>
      </thead>
      <tbody>
        {''.join(body)}
      </tbody>
    </table>
    """


def build_mark_rows(snapshots):
    rows = []
    for row in reversed(snapshots[-40:]):
        summary = row["summary"]
        rows.append(
            f"""
            <tr>
              <td>{html.escape(format_pacific_timestamp(row.get('captured_at_utc') or row.get('captured_at_local')))}</td>
              <td class="num">{fmt_num(row['xsol_price'], 9)}</td>
              <td>{html.escape(row['price_source'])}</td>
              <td class="num">{summary['open_deployment_count']}</td>
              <td class="num">${fmt_num(summary['total_current_value'])}</td>
              <td class="num {pnl_class(summary['total_net_pnl'])}">${fmt_num(summary['total_net_pnl'])}</td>
              <td class="num {pnl_class(summary['total_net_pnl'])}">{fmt_pct(summary['total_net_pnl_pct'])}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_snapshot_delta_rows(snapshots):
    rows = []
    if len(snapshots) < 2:
        return rows
    for previous, current in zip(snapshots, snapshots[1:]):
        prev_summary = previous["summary"]
        curr_summary = current["summary"]
        prev_lots = {lot["lot_id"]: lot for lot in previous.get("lots", [])}
        curr_lots = {lot["lot_id"]: lot for lot in current.get("lots", [])}
        new_lot_ids = [lot_id for lot_id in curr_lots.keys() if lot_id not in prev_lots]
        new_lots = [curr_lots[lot_id] for lot_id in new_lot_ids]

        new_lot_count = len(new_lots)
        new_hyusd_deployed = sum(float(lot.get("entry_value") or 0.0) for lot in new_lots)
        new_xsol_acquired = sum(float(lot.get("xsol_bought") or 0.0) for lot in new_lots)
        open_lot_delta = int(curr_summary.get("open_deployment_count") or 0) - int(prev_summary.get("open_deployment_count") or 0)
        nav_delta_pct = pct_change(previous.get("xsol_price"), current.get("xsol_price"))
        value_delta = float(curr_summary.get("total_current_value") or 0.0) - float(prev_summary.get("total_current_value") or 0.0)
        pnl_delta = float(curr_summary.get("total_net_pnl") or 0.0) - float(prev_summary.get("total_net_pnl") or 0.0)
        rows.append(
            f"""
            <tr>
              <td>
                <div>{html.escape(format_pacific_timestamp(current.get('captured_at_utc') or current.get('captured_at_local')))}</div>
                <div class="subline">vs {html.escape(format_pacific_timestamp(previous.get('captured_at_utc') or previous.get('captured_at_local')))}</div>
              </td>
              <td class="num">
                <div>{int(curr_summary.get('open_deployment_count') or 0)}</div>
                <div class="subline {pnl_class(open_lot_delta)}">{fmt_signed_num(open_lot_delta, 0)}</div>
              </td>
              <td class="num">{fmt_signed_num(new_lot_count, 0)}</td>
              <td class="num">${fmt_signed_num(new_hyusd_deployed)}</td>
              <td class="num">{fmt_signed_num(new_xsol_acquired, 2)}</td>
              <td class="num">{fmt_pct(nav_delta_pct, 3)}</td>
              <td class="num {pnl_class(value_delta)}">${fmt_signed_num(value_delta)}</td>
              <td class="num {pnl_class(pnl_delta)}">${fmt_signed_num(pnl_delta)}</td>
            </tr>
            """
        )
    rows.reverse()
    return rows


def render_html(lot_state, snapshots, signal_report=None):
    latest_snapshot = snapshots[-1] if snapshots else None
    lots = latest_snapshot["lots"] if latest_snapshot else lot_state.get("lots", [])
    display_lots = enrich_lots_for_display(lots)
    price_details = latest_snapshot.get("price_source_details") if latest_snapshot else None
    live_payload = {
        "generated_at_utc": lot_state.get("generated_at_utc"),
        "initial_xsol_price": latest_snapshot.get("xsol_price") if latest_snapshot else None,
        "initial_price_source": latest_snapshot.get("price_source") if latest_snapshot else None,
        "lots": display_lots,
    }
    details_html = ""
    if price_details:
        details_html = f"""
        <div class="details-grid">
          <div><strong>Exchange NAV</strong><br><code>{html.escape(str(price_details.get('exchange_levercoin_nav')))}</code></div>
          <div><strong>Pool NAV</strong><br><code>{html.escape(str(price_details.get('stability_pool_levercoin_nav')))}</code></div>
          <div><strong>Mode</strong><br><code>{html.escape(json.dumps(price_details.get('stability_mode')))}</code></div>
        </div>
        """
    signal_cards_html, _live_setups = build_signal_setup_cards(signal_report)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hylo Stability Pool Deployments</title>
    <style>
      :root {{
        --bg: #0c0f11;
        --panel: #14181b;
        --panel-2: #1a1f23;
        --border: #2b3338;
        --text: #eef2f4;
        --muted: #9baab3;
        --up: #4ed38a;
        --down: #e07163;
        --flat: #d9b86b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--text);
        font-family: "Iowan Old Style", Georgia, serif;
        background:
          radial-gradient(circle at top right, rgba(96, 145, 255, 0.08), transparent 24%),
          radial-gradient(circle at left top, rgba(217, 184, 107, 0.10), transparent 30%),
          linear-gradient(180deg, #0b0e10 0%, #090b0d 100%);
      }}
      .wrap {{ max-width: 1240px; margin: 0 auto; padding: 32px 22px 44px; }}
      h1 {{ margin: 0 0 10px; font-size: 2.2rem; }}
      .sub {{ color: var(--muted); line-height: 1.55; max-width: 900px; }}
      .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 14px;
        margin: 24px 0;
      }}
      .card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00)), var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
      }}
      .card-label {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
      .card-value {{ font-size: 1.5rem; }}
      .card-sub {{ color: var(--muted); font-size: 0.92rem; margin-top: 6px; }}
      .card-value.flat,
      .card-sub.flat {{ color: inherit; }}
      .panel {{
        background: rgba(20,24,27,0.90);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 20px;
        margin-bottom: 18px;
      }}
      h2 {{ margin: 0 0 12px; font-size: 1.1rem; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 12px 10px;
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
      .date-main {{ font-size: 1rem; }}
      .date-sub, .subline {{ color: var(--muted); font-size: 0.92rem; margin-top: 4px; }}
      .up {{ color: var(--up); }}
      .down {{ color: var(--down); }}
      .flat {{ color: var(--flat); }}
      a {{ color: #91d4f1; text-decoration: none; }}
      code {{ color: #f4d48f; word-break: break-all; }}
      .details-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
      }}
      .day-group {{
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 16px;
        margin-top: 12px;
        background: rgba(255,255,255,0.02);
        overflow: hidden;
      }}
      .day-group summary {{
        list-style: none;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: center;
        padding: 16px 18px;
      }}
      .day-group summary::-webkit-details-marker {{ display: none; }}
      .day-summary-heading {{
        font-size: 1rem;
        font-weight: 600;
        min-width: 110px;
      }}
      .day-summary-metrics {{
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 14px;
        color: var(--muted);
        font-size: 0.92rem;
        font-variant-numeric: tabular-nums;
      }}
      .day-summary-metrics strong {{
        color: var(--text);
        font-weight: 600;
      }}
      .day-group-table {{
        padding: 0 12px 12px;
      }}
      .foot {{
        color: var(--muted);
        line-height: 1.5;
        font-size: 0.92rem;
      }}
      .live-note {{
        margin-top: 10px;
        color: var(--muted);
        font-size: 0.9rem;
      }}
      @media (max-width: 760px) {{
        .wrap {{ padding: 20px 12px 30px; }}
        h1 {{ font-size: 1.75rem; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Hylo Stability Pool Deployments</h1>
      <div class="sub">
        Persistent lot tracker built from confirmed on-chain <code>buy_xsol</code> events. A new deployment is created
        when the Stability Pool spends <code>hyUSD</code>, receives <code>xSOL</code>, and the transaction logs include the
        expected rebalance hints. Mark snapshots let you monitor these lots over time instead of only seeing a single screenshot.
      </div>
      <div class="live-note" id="live-refresh-status">
        Waiting for live DexScreener pricing. Live market cards and lot rows refresh in-browser every 60 seconds.
      </div>

      <section class="cards">
        {build_cards(lot_state, latest_snapshot)}
      </section>

      <section class="panel">
        <h2>Open And Historical Deployment Lots</h2>
        <div class="foot">
          Row-level <strong>Live Market</strong> columns are browser-side marks from DexScreener. Entry values remain fixed on-chain lot cost basis.
        </div>
        {build_lot_day_groups(display_lots)}
      </section>

      <section class="panel">
        <h2>Ranked Live Setups</h2>
        <div class="foot">
          Filter layer for profit-focused monitoring. Grades use only earlier resolved episodes, so the current unresolved activations get a forward-looking quality rank instead of being treated as equal alerts. Alerts are only eligible once the setup clears the current score and confidence bar.
        </div>
        <section class="cards">
          {signal_cards_html}
        </section>
        {build_live_setup_rows(signal_report)}
      </section>

      <section class="panel">
        <h2>Hypothetical $1,000 xSOL Buys 10 Minutes After Signal</h2>
        <div class="foot">
          One fixed-size xSOL buy per confirmed activation episode, entered 10 minutes after the first buy in that episode.
          These are <strong>signal replays</strong>, not Stability Pool lots. Marked values below use the latest cached xSOL close from the signal study.
        </div>
        <section class="cards">
          {build_strategy_cards(signal_report)}
        </section>
        {build_strategy_day_groups(signal_report)}
      </section>

      <section class="panel">
        <h2>Snapshot Deltas</h2>
        <div class="foot">
          Higher-signal change log between saved protocol snapshots. Instead of repeating raw NAV marks, this shows what changed since the prior saved snapshot:
          new lots, new hyUSD deployed, new xSOL acquired, and the change in protocol-marked value and PnL.
        </div>
        {
            (
                f"""
        <table>
          <thead>
            <tr>
              <th>Captured</th>
              <th>Open Lots</th>
              <th>New Lots</th>
              <th>hyUSD Deployed</th>
              <th>xSOL Acquired</th>
              <th>Protocol NAV Δ</th>
              <th>Protocol Value Δ</th>
              <th>Protocol PnL Δ</th>
            </tr>
          </thead>
          <tbody>
            {''.join(build_snapshot_delta_rows(snapshots))}
          </tbody>
        </table>
                """
                if len(snapshots) >= 2
                else '<div class="foot">Need at least two saved snapshots before snapshot deltas are available.</div>'
            )
        }
      </section>

      <section class="panel">
        <h2>Price Mark Context</h2>
        <div class="foot">
          <strong>Protocol NAV</strong> comes from Hylo stats and is used for the saved mark history.
          <strong>Live Market</strong> comes from browser-side DexScreener fetches and is used for the live cards and lot rows.
        </div>
        {details_html or '<div class="foot">No structured price-source details were stored for the latest mark.</div>'}
      </section>

      <section class="panel">
        <h2>Signal Research</h2>
        <div class="foot">
          Trigger-level episode outcomes and regime segmentation live in
          <a href="stability_pool_signal_report.html">stability_pool_signal_report.html</a>.
          Use that page to judge whether confirmed Stability Pool activations are acting like a tradable signal instead of just a profitable open inventory mark.
        </div>
      </section>

      <section class="foot">
        <p>
          This tracker treats confirmed <code>buy_xsol</code> events as deployment lots and carries them forward across repeated marks.
          If future confirmed <code>sell_xsol</code> events appear, the monitor applies them FIFO against the open lots.
        </p>
        <p>
          Source repo used for the on-chain event and instruction mapping:
          <a href="https://github.com/hylo-so/sdk">hylo-so/sdk</a>.
        </p>
      </section>
    </div>
    <script id="live-lot-state" type="application/json">{html.escape(json_for_script(live_payload), quote=False)}</script>
    <script>
      (() => {{
        const REFRESH_SECONDS = 60;
        const XSOL_TOKEN = "4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs";
        const SOL_TOKEN = "So11111111111111111111111111111111111111112";
        const PACIFIC_FORMATTER = new Intl.DateTimeFormat("en-US", {{
          timeZone: "America/Los_Angeles",
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
          timeZoneName: "short",
        }});
        const payload = JSON.parse(document.getElementById("live-lot-state").textContent);
        const lotRows = payload.lots || [];
        let countdown = REFRESH_SECONDS;
        let livePriceState = {{
          xsol: payload.initial_xsol_price,
          xsolSource: payload.initial_price_source || "saved mark",
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

        function formatPct(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          const sign = value > 0 ? "+" : "";
          return `${{sign}}${{Number(value).toFixed(digits)}}%`;
        }}

        function pnlClass(value) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "flat";
          }}
          if (value > 0) {{
            return "up";
          }}
          if (value < 0) {{
            return "down";
          }}
          return "flat";
        }}

        function setTone(element, value) {{
          if (!element) {{
            return;
          }}
          element.classList.remove("up", "down", "flat");
          element.classList.add(pnlClass(value));
        }}

        function setText(id, value) {{
          const el = document.getElementById(id);
          if (el) {{
            el.textContent = value;
          }}
        }}

        function formatDaysHeld(utc) {{
          if (!utc) {{
            return "n/a";
          }}
          const ms = Date.now() - Date.parse(utc);
          const days = Math.max(0, Math.floor(ms / 86400000));
          return `${{days}}d`;
        }}

        function formatPacificTimestamp(date) {{
          return PACIFIC_FORMATTER.format(date);
        }}

        function bestPair(pairs, filterFn = null) {{
          const filtered = (pairs || []).filter((pair) => {{
            if (!filterFn) {{
              return true;
            }}
            return filterFn(pair);
          }});
          if (!filtered.length) {{
            return null;
          }}
          return filtered.sort((a, b) => (Number(b?.liquidity?.usd || 0) - Number(a?.liquidity?.usd || 0)))[0];
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
            pairAddress: pair.pairAddress || "",
            liquidityUsd: Number(pair?.liquidity?.usd || 0),
            quoteSymbol: pair?.quoteToken?.symbol || "",
          }};
        }}

        function recomputeView() {{
          const xsolPrice = Number(livePriceState.xsol);
          if (!xsolPrice) {{
            return;
          }}
          let totalEntryValue = 0;
          let totalCurrentValue = 0;
          let totalNetPnl = 0;
          let totalRemainingXsol = 0;
          let openDeploymentCount = 0;
          const dayTotals = new Map();

          for (const lot of lotRows) {{
            const remainingXsol = Number(lot.remaining_xsol || 0);
            const remainingEntryValue = Number(lot.remaining_entry_value || 0);
            const realizedPnl = Number(lot.realized_pnl || 0);
            const currentValue = remainingXsol * xsolPrice;
            const unrealizedPnl = currentValue - remainingEntryValue;
            const netPnl = realizedPnl + unrealizedPnl;
            const netPnlPct = Number(lot.entry_value || 0) > 0 ? (netPnl / Number(lot.entry_value)) * 100 : null;
            const dayKey = lot.day_key || "unknown";

            totalEntryValue += Number(lot.entry_value || 0);
            totalCurrentValue += currentValue;
            totalNetPnl += netPnl;
            totalRemainingXsol += remainingXsol;
            if (remainingXsol > 0) {{
              openDeploymentCount += 1;
            }}
            if (!dayTotals.has(dayKey)) {{
              dayTotals.set(dayKey, {{
                count: 0,
                xsol: 0,
                entry: 0,
                current: 0,
                pnl: 0,
              }});
            }}
            const bucket = dayTotals.get(dayKey);
            bucket.count += 1;
            bucket.xsol += Number(lot.xsol_bought || 0);
            bucket.entry += Number(lot.entry_value || 0);
            bucket.current += currentValue;
            bucket.pnl += netPnl;

            setText(`${{lot.lot_id}}-current-price`, formatCurrency(xsolPrice, 6));
            setText(`${{lot.lot_id}}-current-value`, formatCurrency(currentValue));
            setText(`${{lot.lot_id}}-net-pnl`, formatCurrency(netPnl));
            setText(`${{lot.lot_id}}-net-pnl-pct`, formatPct(netPnlPct));
            setText(`${{lot.lot_id}}-days-held`, formatDaysHeld(lot.utc));
            setTone(document.getElementById(`${{lot.lot_id}}-net-pnl`), netPnl);
            setTone(document.getElementById(`${{lot.lot_id}}-net-pnl-pct`), netPnl);
          }}

          const totalNetPnlPct = totalEntryValue > 0 ? (totalNetPnl / totalEntryValue) * 100 : null;
          setText("summary-open-deployment-count", String(openDeploymentCount));
          setText("summary-remaining-xsol", formatNum(totalRemainingXsol, 6));
          setText("summary-entry-value", formatCurrency(totalEntryValue));
          setText("summary-live-market-value", formatCurrency(totalCurrentValue));
          setText("summary-live-market-pnl", formatCurrency(totalNetPnl));
          setText("summary-live-market-pnl-sub", formatPct(totalNetPnlPct));
          setText("summary-live-market-value-sub", "browser market mark");
          setText("summary-live-xsol-price", formatNum(xsolPrice, 9));
          setTone(document.getElementById("summary-live-market-pnl"), totalNetPnl);
          setTone(document.getElementById("summary-live-market-pnl-sub"), totalNetPnl);

          for (const [dayKey, totals] of dayTotals.entries()) {{
            const dayPnlPct = totals.entry > 0 ? (totals.pnl / totals.entry) * 100 : null;
            setText(`day-${{dayKey}}-count`, String(totals.count));
            setText(`day-${{dayKey}}-xsol`, formatNum(totals.xsol, 2));
            setText(`day-${{dayKey}}-entry`, formatCurrency(totals.entry));
            setText(`day-${{dayKey}}-current`, formatCurrency(totals.current));
            setText(`day-${{dayKey}}-pnl`, formatCurrency(totals.pnl));
            setText(`day-${{dayKey}}-pnl-pct`, formatPct(dayPnlPct));
            const pnlEl = document.getElementById(`day-${{dayKey}}-pnl`);
            const pctEl = document.getElementById(`day-${{dayKey}}-pnl-pct`);
            setTone(pnlEl, totals.pnl);
            setTone(pctEl, totals.pnl);
          }}
        }}

        function renderLiveState() {{
          if (livePriceState.xsol) {{
            setText(
              "summary-live-xsol-price-sub",
              `${{livePriceState.xsolSource}} • refresh in ${{countdown}}s`
            );
          }}
          if (livePriceState.sol) {{
            setText("summary-sol-price", formatCurrency(livePriceState.sol));
            setText(
              "summary-sol-price-sub",
              `${{livePriceState.solSource}} • refresh in ${{countdown}}s`
            );
          }} else {{
            setText("summary-sol-price", "Loading...");
            setText("summary-sol-price-sub", `refresh in ${{countdown}}s`);
          }}
          if (livePriceState.lastUpdated) {{
            const pacificTime = formatPacificTimestamp(livePriceState.lastUpdated);
            setText("live-refresh-status", `Live market prices updated ${{pacificTime}}. Next refresh in ${{countdown}}s.`);
          }} else if (livePriceState.lastError) {{
            setText("live-refresh-status", `Live market refresh failed: ${{livePriceState.lastError}}. Retrying in ${{countdown}}s.`);
          }} else {{
            setText("live-refresh-status", `Waiting for live DexScreener pricing. Live market cards and lot rows refresh in-browser every ${{REFRESH_SECONDS}} seconds.`);
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
            livePriceState = {{
              xsol: xsolResult.price,
              xsolSource: `DexScreener ${{xsolResult.dexId}}`,
              sol: solResult.price,
              solSource: `DexScreener ${{solResult.dexId}}`,
              lastUpdated: new Date(),
              lastError: "",
            }};
            recomputeView();
          }} catch (error) {{
            console.error(error);
            livePriceState.lastError = error?.message || "unknown error";
          }}
          countdown = REFRESH_SECONDS;
          renderLiveState();
        }}

        recomputeView();
        renderLiveState();
        refreshPrices();
        window.setInterval(() => {{
          countdown -= 1;
          if (countdown <= 0) {{
            refreshPrices();
            return;
          }}
          renderLiveState();
        }}, 1000);
      }})();
    </script>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render Stability Pool deployment-lot HTML.")
    parser.add_argument(
        "--lots",
        default="data/stability_pool_deployments.json",
        help="Deployment lot state JSON path.",
    )
    parser.add_argument(
        "--marks",
        default="data/stability_pool_deployment_marks.jsonl",
        help="Mark-to-market snapshot JSONL path.",
    )
    parser.add_argument(
        "--out",
        default="stability_pool_deployments.html",
        help="Output HTML path.",
    )
    parser.add_argument(
        "--signal-report",
        default="data/stability_pool_signal_report.json",
        help="Signal report JSON path.",
    )
    args = parser.parse_args()
    lot_state = load_json(args.lots)
    marks = load_jsonl(args.marks)
    signal_path = Path(args.signal_report)
    signal_report = load_json(signal_path) if signal_path.exists() else None
    Path(args.out).write_text(render_html(lot_state, marks, signal_report=signal_report), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
