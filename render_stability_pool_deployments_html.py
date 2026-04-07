#!/usr/bin/env python3
import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
EPSILON = 1e-12


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


def build_cards(lot_state, latest_snapshot, shadow_replay=None):
    summary = latest_snapshot["summary"] if latest_snapshot else {}
    cards = []
    shadow_overall = (shadow_replay or {}).get("overall") or {}
    shadow_delay_mins = int(((shadow_replay or {}).get("delay_seconds") or 0) / 60)
    shadow_tranche = (shadow_replay or {}).get("tranche_usd")
    if shadow_replay:
        shadow_subtext = (
            f"Shadow ${fmt_num(shadow_tranche, 0)} buys at +{shadow_delay_mins}m"
            if shadow_tranche is not None
            else "Shadow Hylo lifecycle"
        )
        cards.extend(
            [
                card(
                    "Shadow PnL",
                    f"${fmt_num(shadow_overall.get('shadow_pnl_usd'))}",
                    shadow_subtext,
                    pnl_class(shadow_overall.get("shadow_pnl_usd")),
                ),
                card(
                    "Shadow Equity",
                    f"${fmt_num(shadow_overall.get('shadow_value_usd'))}",
                    "realized exits + latest cached xSOL close",
                ),
                card(
                    "Active Shadow Entries",
                    str(shadow_overall.get("active_count", 0)),
                    "open until Hylo closes the episode lots",
                    tone=("up" if shadow_overall.get("active_count", 0) > 0 else "flat"),
                ),
            ]
        )
    cards.append(
        card(
            "Deployments",
            str(lot_state.get("deployment_count", 0)),
            "confirmed buy_xsol lots",
            card_id="card-deployments",
            value_id="summary-deployment-count",
        )
    )
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
                    fmt_num(summary["total_remaining_xsol"], 1),
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


def build_shadow_replay(lots, signal_report):
    replay = (signal_report or {}).get("tranche_replay") or {}
    if not replay:
        return {}
    episodes = (signal_report or {}).get("episodes") or []
    episodes_by_id = {row.get("episode_id"): row for row in episodes if row.get("episode_id")}
    lots_by_signature = {row.get("signature"): row for row in lots if row.get("signature")}
    mark_price = replay.get("mark_price")
    shadow_entries = []

    for entry in replay.get("entries") or []:
        row = dict(entry)
        episode = episodes_by_id.get(entry.get("episode_id")) or {}
        signatures = episode.get("signatures") or ([entry.get("first_signature")] if entry.get("first_signature") else [])
        matched_lots = [lots_by_signature[sig] for sig in signatures if sig in lots_by_signature]
        total_hylo_xsol = sum(float(lot.get("xsol_bought") or 0.0) for lot in matched_lots)
        shadow_start_xsol = float(entry.get("xsol_acquired") or 0.0)
        shadow_sold_xsol = 0.0
        realized_value_usd = 0.0
        closed_at_utc = None

        if total_hylo_xsol > EPSILON:
            for lot in matched_lots:
                lot_xsol = float(lot.get("xsol_bought") or 0.0)
                if lot_xsol <= EPSILON:
                    continue
                shadow_lot_xsol = shadow_start_xsol * (lot_xsol / total_hylo_xsol)
                lot_shadow_sold = 0.0
                for alloc in lot.get("sell_allocations") or []:
                    sold_fraction = min(max(float(alloc.get("xsol_sold") or 0.0) / lot_xsol, 0.0), 1.0)
                    shadow_alloc_xsol = shadow_lot_xsol * sold_fraction
                    sale_price = alloc.get("sale_price")
                    if sale_price is not None:
                        realized_value_usd += shadow_alloc_xsol * float(sale_price)
                    lot_shadow_sold += shadow_alloc_xsol
                    sell_utc = alloc.get("sell_utc")
                    if sell_utc and (closed_at_utc is None or sell_utc > closed_at_utc):
                        closed_at_utc = sell_utc
                shadow_sold_xsol += min(lot_shadow_sold, shadow_lot_xsol)

        remaining_xsol = max(shadow_start_xsol - shadow_sold_xsol, 0.0)
        open_value_usd = None
        if mark_price is not None:
            open_value_usd = remaining_xsol * float(mark_price)
        elif remaining_xsol <= EPSILON:
            open_value_usd = 0.0

        shadow_value_usd = None
        if open_value_usd is not None:
            shadow_value_usd = realized_value_usd + open_value_usd
        elif shadow_sold_xsol > EPSILON and remaining_xsol <= EPSILON:
            shadow_value_usd = realized_value_usd
        elif entry.get("marked_value_usd") is not None:
            shadow_value_usd = float(entry.get("marked_value_usd"))

        if matched_lots:
            if remaining_xsol <= EPSILON:
                status = "closed"
            elif shadow_sold_xsol > EPSILON:
                status = "partial"
            else:
                status = "open"
        else:
            status = "unlinked"

        hylo_remaining_xsol = sum(float(lot.get("remaining_xsol") or 0.0) for lot in matched_lots)
        row.update(
            {
                "status": status,
                "matched_signatures": signatures,
                "hylo_lot_count": len(matched_lots),
                "hylo_open_lot_count": sum(
                    1 for lot in matched_lots if float(lot.get("remaining_xsol") or 0.0) > EPSILON
                ),
                "hylo_remaining_xsol": hylo_remaining_xsol,
                "remaining_xsol": remaining_xsol,
                "remaining_pct": ((remaining_xsol / shadow_start_xsol) * 100.0) if shadow_start_xsol > EPSILON else None,
                "realized_xsol": shadow_sold_xsol,
                "realized_value_usd": realized_value_usd,
                "open_value_usd": open_value_usd,
                "shadow_value_usd": shadow_value_usd,
                "shadow_pnl_usd": (
                    shadow_value_usd - float(entry.get("tranche_usd") or 0.0)
                    if shadow_value_usd is not None
                    else None
                ),
                "shadow_pnl_pct": pct_change(entry.get("tranche_usd"), shadow_value_usd),
                "closed_at_utc": closed_at_utc if status == "closed" else None,
            }
        )
        shadow_entries.append(row)

    capital_deployed = sum(float(row.get("tranche_usd") or 0.0) for row in shadow_entries)
    total_shadow_value = sum(float(row.get("shadow_value_usd") or 0.0) for row in shadow_entries)
    total_remaining_xsol = sum(float(row.get("remaining_xsol") or 0.0) for row in shadow_entries)
    total_realized_value = sum(float(row.get("realized_value_usd") or 0.0) for row in shadow_entries)
    total_open_value = sum(float(row.get("open_value_usd") or 0.0) for row in shadow_entries)
    total_shadow_pnl = total_shadow_value - capital_deployed if shadow_entries else 0.0
    research_overall = replay.get("overall") or {}
    return {
        "delay_seconds": replay.get("delay_seconds"),
        "delay_label": replay.get("delay_label"),
        "tranche_usd": replay.get("tranche_usd"),
        "entry_count": len(shadow_entries),
        "entries": shadow_entries,
        "mark_price": mark_price,
        "mark_time_utc": replay.get("mark_time_utc"),
        "mark_time_local": replay.get("mark_time_local"),
        "research_overall": research_overall,
        "overall": {
            "count": len(shadow_entries),
            "active_count": sum(1 for row in shadow_entries if row.get("status") in {"open", "partial", "unlinked"}),
            "open_count": sum(1 for row in shadow_entries if row.get("status") == "open"),
            "partial_count": sum(1 for row in shadow_entries if row.get("status") == "partial"),
            "closed_count": sum(1 for row in shadow_entries if row.get("status") == "closed"),
            "unlinked_count": sum(1 for row in shadow_entries if row.get("status") == "unlinked"),
            "capital_deployed_usd": capital_deployed,
            "shadow_value_usd": total_shadow_value,
            "shadow_pnl_usd": total_shadow_pnl,
            "shadow_pnl_pct": pct_change(capital_deployed, total_shadow_value),
            "remaining_xsol": total_remaining_xsol,
            "realized_value_usd": total_realized_value,
            "open_value_usd": total_open_value,
            "24h_mean_return_pct": research_overall.get("24h_mean_return_pct"),
            "24h_win_rate_pct": research_overall.get("24h_win_rate_pct"),
        },
    }


def build_strategy_cards(shadow_replay):
    overall = (shadow_replay or {}).get("overall") or {}
    if not shadow_replay:
        return ""
    cards = [
        card(
            "Shadow Signals",
            str(shadow_replay.get("entry_count", 0)),
            f"${fmt_num(shadow_replay.get('tranche_usd', 0), 0)} xSOL buys at +{int((shadow_replay.get('delay_seconds') or 0) / 60)}m",
        ),
        card(
            "Active Shadow Entries",
            str(overall.get("active_count", 0)),
            "stay open until Hylo closes the episode lots",
            tone=("up" if overall.get("active_count", 0) > 0 else "flat"),
        ),
        card(
            "Shadow Capital",
            f"${fmt_num(overall.get('capital_deployed_usd'))}",
            "fixed notional deployed",
        ),
        card(
            "Shadow Equity",
            f"${fmt_num(overall.get('shadow_value_usd'))}",
            "realized exits + latest cached xSOL close",
        ),
        card(
            "Shadow PnL",
            f"${fmt_num(overall.get('shadow_pnl_usd'))}",
            fmt_pct(overall.get("shadow_pnl_pct")),
            pnl_class(overall.get("shadow_pnl_usd")),
        ),
        card(
            "Open Shadow xSOL",
            fmt_num(overall.get("remaining_xsol"), 2),
            "still open because Hylo inventory is still open",
        ),
        card(
            "Replay 24h Mean",
            fmt_pct(overall.get("24h_mean_return_pct")),
            "research stat from delayed entry",
        ),
    ]
    return "\n".join(cards)


def build_strategy_rows(entries):
    rows = []
    for row in sorted(entries, key=lambda item: item.get("entry_target_utc") or "", reverse=True):
        signal_day, signal_time = format_pacific_date_parts(row.get("start_utc") or row.get("start_local"))
        entry_day, entry_time = format_pacific_date_parts(row.get("entry_target_utc") or row.get("entry_target_local"))
        shadow_pnl = row.get("shadow_pnl_usd")
        tone = pnl_class(shadow_pnl)
        if row.get("status") == "closed" and row.get("closed_at_utc"):
            status_subline = f"closed {format_pacific_timestamp(row.get('closed_at_utc'))}"
        elif row.get("hylo_lot_count"):
            status_subline = (
                f"{row.get('hylo_open_lot_count', 0)}/{row.get('hylo_lot_count', 0)} Hylo lots open"
            )
        else:
            status_subline = "no matching Hylo lots"
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
              <td>
                <div class="date-main">{html.escape(str(row.get('status', 'open')).title())}</div>
                <div class="date-sub">{html.escape(status_subline)}</div>
              </td>
              <td class="num">${fmt_num(row.get('tranche_usd'), 0)}</td>
              <td class="num">
                <div>{fmt_num(row.get('remaining_xsol'), 2)}</div>
                <div class="subline">{fmt_pct(row.get('remaining_pct'))} of {fmt_num(row.get('xsol_acquired'), 2)} start</div>
              </td>
              <td class="num">
                <div>${fmt_num(row.get('shadow_value_usd'))}</div>
                <div class="subline">${fmt_num(row.get('realized_value_usd'))} realized</div>
              </td>
              <td class="num">
                <div class="{tone}">${fmt_num(shadow_pnl)}</div>
                <div class="subline {tone}">{fmt_pct(row.get('shadow_pnl_pct'))}</div>
              </td>
              <td class="num">{fmt_pct(row.get('24h_return_pct'))}</td>
              <td><a href="https://solscan.io/tx/{html.escape(row['first_signature'])}">{html.escape(row['first_signature'][:10])}...</a></td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_strategy_day_groups(shadow_replay):
    entries = (shadow_replay or {}).get("entries") or []
    if not entries:
        return '<div class="foot">No confirmed shadow entries have been generated yet.</div>'

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
                "active_count": 0,
                "capital": 0.0,
                "remaining_xsol": 0.0,
                "shadow_value": 0.0,
                "shadow_pnl": 0.0,
            },
        )
        if bucket["count"] == 0:
            groups.append(bucket)
        bucket["entries"].append(row)
        bucket["count"] += 1
        if row.get("status") in {"open", "partial", "unlinked"}:
            bucket["active_count"] += 1
        bucket["capital"] += float(row.get("tranche_usd") or 0.0)
        bucket["remaining_xsol"] += float(row.get("remaining_xsol") or 0.0)
        bucket["shadow_value"] += float(row.get("shadow_value_usd") or 0.0)
        bucket["shadow_pnl"] += float(row.get("shadow_pnl_usd") or 0.0)

    sections = []
    for index, group in enumerate(groups):
        pnl_pct = ((group["shadow_pnl"] / group["capital"]) * 100.0) if group["capital"] else None
        sections.append(
            f"""
            <details class="day-group" data-strategy-day-key="{html.escape(group['day_key'])}" {"open" if index == 0 else ""}>
              <summary>
                <div class="day-summary-heading">{html.escape(group['day_label'])}</div>
                <div class="day-summary-metrics">
                  <span><strong>{group['count']}</strong> shadow entries</span>
                  <span><strong>{group['active_count']}</strong> active</span>
                  <span><strong>${fmt_num(group['capital'])}</strong> deployed</span>
                  <span><strong>{fmt_num(group['remaining_xsol'], 2)}</strong> xSOL live</span>
                  <span><strong>${fmt_num(group['shadow_value'])}</strong> equity</span>
                  <span class="{pnl_class(group['shadow_pnl'])}">
                    <strong>${fmt_num(group['shadow_pnl'])}</strong>
                    <span>{fmt_pct(pnl_pct)}</span>
                  </span>
                </div>
              </summary>
              <div class="day-group-table">
                <table>
                  <thead>
                    <tr>
                      <th>Signal Start</th>
                      <th>Shadow Entry</th>
                      <th>Status</th>
                      <th>Tranche</th>
                      <th>xSOL Live</th>
                      <th>Shadow Equity</th>
                      <th>Shadow PnL</th>
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
    shadow_replay = build_shadow_replay(lots, signal_report)
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
          {build_cards(lot_state, latest_snapshot, shadow_replay=shadow_replay)}
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
        <h2>Shadow $1,000 xSOL Buys 10 Minutes After Signal</h2>
        <div class="foot">
          One fixed-size xSOL buy per confirmed activation episode, entered 10 minutes after the first buy in that episode.
          These are <strong>shadow entries</strong>, not Stability Pool lots. Each shadow entry stays open until Hylo closes the
          corresponding episode inventory, so partial and closed rows follow Hylo's real lot lifecycle instead of expiring after the research window.
        </div>
        <section class="cards">
          {build_strategy_cards(shadow_replay)}
        </section>
        {build_strategy_day_groups(shadow_replay)}
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

      <section class="panel">
        <h2>Open And Historical Deployment Lots</h2>
        <div class="foot">
          Row-level <strong>Live Market</strong> columns are browser-side marks from DexScreener. Entry values remain fixed on-chain lot cost basis.
        </div>
        {build_lot_day_groups(display_lots)}
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
          setText("summary-remaining-xsol", formatNum(totalRemainingXsol, 1));
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
