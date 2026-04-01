#!/usr/bin/env python3
import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


EPSILON = 1e-12
REQUIRED_BUY_HINTS = {"RebalanceStableToLever", "SwapStableToLever"}
REQUIRED_SELL_HINTS = {"SwapLeverToStable"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def parse_iso(ts):
    return datetime.fromisoformat(ts)


def sort_events(events):
    return sorted(
        events,
        key=lambda row: (
            row.get("slot") or 0,
            row.get("block_time") or 0,
            row.get("signature") or "",
        ),
    )


def has_required_hints(event, required):
    hints = set(event.get("log_hints") or [])
    return required.issubset(hints)


def build_lots(events, strict=True):
    lots = []
    open_indices = []
    unmatched_sells = []
    ordered = sort_events(events)
    for event in ordered:
        action = event.get("action")
        if action == "buy_xsol":
            confirmed = has_required_hints(event, REQUIRED_BUY_HINTS)
            if strict and not confirmed:
                continue
            xsol_bought = float(event["xsol_pool"]["delta"])
            hyusd_spent = abs(float(event["hyusd_pool"]["delta"]))
            lot = {
                "lot_id": f"lot-{len(lots) + 1}",
                "status": "open",
                "signature": event["signature"],
                "solscan_url": event["solscan_url"],
                "slot": event.get("slot"),
                "block_time": event.get("block_time"),
                "utc": event.get("utc"),
                "local": event.get("local"),
                "log_hints": event.get("log_hints") or [],
                "strictly_confirmed": confirmed,
                "entry_price": hyusd_spent / xsol_bought if xsol_bought > EPSILON else None,
                "entry_value": hyusd_spent,
                "xsol_bought": xsol_bought,
                "remaining_xsol": xsol_bought,
                "remaining_entry_value": hyusd_spent,
                "realized_hyusd": 0.0,
                "realized_pnl": 0.0,
                "sell_allocations": [],
            }
            lots.append(lot)
            open_indices.append(len(lots) - 1)
        elif action == "sell_xsol":
            confirmed = has_required_hints(event, REQUIRED_SELL_HINTS)
            if strict and not confirmed:
                continue
            xsol_sold = abs(float(event["xsol_pool"]["delta"]))
            hyusd_received = float(event["hyusd_pool"]["delta"])
            sale_price = hyusd_received / xsol_sold if xsol_sold > EPSILON else None
            remaining_to_match = xsol_sold
            allocations = []
            for idx in list(open_indices):
                lot = lots[idx]
                if lot["remaining_xsol"] <= EPSILON:
                    continue
                taken = min(lot["remaining_xsol"], remaining_to_match)
                if taken <= EPSILON:
                    continue
                cost_piece = lot["entry_price"] * taken
                proceeds_piece = sale_price * taken if sale_price is not None else 0.0
                lot["remaining_xsol"] -= taken
                lot["remaining_entry_value"] -= cost_piece
                lot["realized_hyusd"] += proceeds_piece
                lot["realized_pnl"] += proceeds_piece - cost_piece
                if lot["remaining_xsol"] <= EPSILON:
                    lot["remaining_xsol"] = 0.0
                    lot["remaining_entry_value"] = 0.0
                    lot["status"] = "closed"
                    open_indices.remove(idx)
                else:
                    lot["status"] = "partial"
                allocation = {
                    "sell_signature": event["signature"],
                    "sell_utc": event.get("utc"),
                    "xsol_sold": taken,
                    "sale_price": sale_price,
                    "hyusd_received": proceeds_piece,
                    "cost_basis_released": cost_piece,
                    "realized_pnl": proceeds_piece - cost_piece,
                }
                lot["sell_allocations"].append(allocation)
                allocations.append({"lot_id": lot["lot_id"], **allocation})
                remaining_to_match -= taken
                if remaining_to_match <= EPSILON:
                    break
            if remaining_to_match > EPSILON:
                unmatched_sells.append(
                    {
                        "signature": event["signature"],
                        "utc": event.get("utc"),
                        "local": event.get("local"),
                        "xsol_sold_unmatched": remaining_to_match,
                        "hyusd_received_total": hyusd_received,
                        "sale_price": sale_price,
                        "log_hints": event.get("log_hints") or [],
                        "allocations": allocations,
                    }
                )
    buy_events = [row for row in ordered if row.get("action") == "buy_xsol"]
    sell_events = [row for row in ordered if row.get("action") == "sell_xsol"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strict_mode": strict,
        "source_event_count": len(events),
        "source_buy_event_count": len(buy_events),
        "source_sell_event_count": len(sell_events),
        "deployment_count": len(lots),
        "lots": lots,
        "unmatched_sells": unmatched_sells,
    }


def extract_price_from_hylo_stats(path):
    payload = load_json(path)
    exchange = payload.get("exchangeStats") or {}
    pool = payload.get("stabilityPoolStats") or {}
    exchange_nav = exchange.get("levercoinNav")
    pool_nav = pool.get("levercoinNav")
    if exchange_nav is not None:
        return {
            "xsol_price": float(exchange_nav),
            "price_source": "hylo_stats.exchangeStats.levercoinNav",
            "price_source_details": {
                "exchange_levercoin_nav": exchange_nav,
                "stability_pool_levercoin_nav": pool_nav,
                "stability_mode": exchange.get("stabilityMode"),
            },
        }
    if pool_nav is not None:
        return {
            "xsol_price": float(pool_nav),
            "price_source": "hylo_stats.stabilityPoolStats.levercoinNav",
            "price_source_details": {
                "exchange_levercoin_nav": exchange_nav,
                "stability_pool_levercoin_nav": pool_nav,
                "stability_mode": exchange.get("stabilityMode"),
            },
        }
    raise RuntimeError("No levercoinNav field found in Hylo stats JSON.")


def build_mark_snapshot(lot_state, xsol_price, price_source, price_source_details=None, captured_at=None):
    stamp = parse_iso(captured_at) if captured_at else datetime.now(timezone.utc)
    lots = []
    total_entry_value = 0.0
    total_remaining_entry_value = 0.0
    total_current_value = 0.0
    total_realized_pnl = 0.0
    total_net_pnl = 0.0
    total_remaining_xsol = 0.0
    for lot in lot_state["lots"]:
        row = deepcopy(lot)
        row["current_price"] = xsol_price
        row["current_value"] = row["remaining_xsol"] * xsol_price
        row["unrealized_pnl"] = row["current_value"] - row["remaining_entry_value"]
        row["net_pnl"] = row["realized_pnl"] + row["unrealized_pnl"]
        row["net_pnl_pct"] = (
            (row["net_pnl"] / row["entry_value"]) * 100.0
            if row["entry_value"] > EPSILON
            else None
        )
        held_days = (stamp - parse_iso(row["utc"])).total_seconds() / 86400.0
        row["days_held"] = held_days
        row["days_held_display"] = f"{int(held_days)}d"
        lots.append(row)
        total_entry_value += row["entry_value"]
        total_remaining_entry_value += row["remaining_entry_value"]
        total_current_value += row["current_value"]
        total_realized_pnl += row["realized_pnl"]
        total_net_pnl += row["net_pnl"]
        total_remaining_xsol += row["remaining_xsol"]
    open_lots = [row for row in lots if row["remaining_xsol"] > EPSILON]
    return {
        "captured_at_utc": stamp.isoformat(),
        "captured_at_local": stamp.astimezone().isoformat(),
        "xsol_price": xsol_price,
        "price_source": price_source,
        "price_source_details": price_source_details or {},
        "summary": {
            "deployment_count": len(lots),
            "open_deployment_count": len(open_lots),
            "total_entry_value": total_entry_value,
            "total_remaining_entry_value": total_remaining_entry_value,
            "total_remaining_xsol": total_remaining_xsol,
            "total_current_value": total_current_value,
            "total_realized_pnl": total_realized_pnl,
            "total_net_pnl": total_net_pnl,
            "total_net_pnl_pct": (
                (total_net_pnl / total_entry_value) * 100.0
                if total_entry_value > EPSILON
                else None
            ),
        },
        "lots": lots,
    }


def existing_snapshot_keys(path):
    keys = set()
    for row in load_jsonl(path):
        keys.add((row.get("captured_at_utc"), row.get("xsol_price"), row.get("price_source")))
    return keys


def rounded(value, digits=12):
    if value is None:
        return None
    return round(float(value), digits)


def snapshot_signature(snapshot):
    summary = snapshot.get("summary") or {}
    lots = []
    for lot in snapshot.get("lots") or []:
        lots.append(
            {
                "lot_id": lot.get("lot_id"),
                "status": lot.get("status"),
                "signature": lot.get("signature"),
                "remaining_xsol": rounded(lot.get("remaining_xsol")),
                "remaining_entry_value": rounded(lot.get("remaining_entry_value")),
                "realized_hyusd": rounded(lot.get("realized_hyusd")),
                "realized_pnl": rounded(lot.get("realized_pnl")),
            }
        )
    payload = {
        "xsol_price": rounded(snapshot.get("xsol_price")),
        "price_source": snapshot.get("price_source"),
        "summary": {
            "deployment_count": summary.get("deployment_count"),
            "open_deployment_count": summary.get("open_deployment_count"),
            "total_entry_value": rounded(summary.get("total_entry_value")),
            "total_remaining_entry_value": rounded(summary.get("total_remaining_entry_value")),
            "total_remaining_xsol": rounded(summary.get("total_remaining_xsol")),
            "total_current_value": rounded(summary.get("total_current_value")),
            "total_realized_pnl": rounded(summary.get("total_realized_pnl")),
            "total_net_pnl": rounded(summary.get("total_net_pnl")),
            "total_net_pnl_pct": rounded(summary.get("total_net_pnl_pct")),
        },
        "lots": lots,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def condense_snapshots(rows):
    condensed = []
    last_signature = None
    for row in rows:
        signature = snapshot_signature(row)
        if signature == last_signature:
            condensed[-1] = row
            continue
        condensed.append(row)
        last_signature = signature
    return condensed


def resolve_price(args):
    if args.xsol_price is not None:
        return {
            "xsol_price": float(args.xsol_price),
            "price_source": args.price_source or "manual",
            "price_source_details": {},
        }
    if args.hylo_stats_file:
        price_info = extract_price_from_hylo_stats(args.hylo_stats_file)
        if args.price_source:
            price_info["price_source"] = args.price_source
        return price_info
    return None


def run_update(args):
    events = load_jsonl(args.events)
    lot_state = build_lots(events, strict=not args.allow_unconfirmed)
    write_json(args.lots_out, lot_state)
    print(
        json.dumps(
            {
                "lots_out": args.lots_out,
                "deployment_count": lot_state["deployment_count"],
                "strict_mode": lot_state["strict_mode"],
            },
            indent=2,
        )
    )
    price_info = resolve_price(args)
    if not price_info or not args.marks_out:
        return
    snapshot = build_mark_snapshot(
        lot_state,
        xsol_price=price_info["xsol_price"],
        price_source=price_info["price_source"],
        price_source_details=price_info["price_source_details"],
        captured_at=args.captured_at,
    )
    existing_rows = load_jsonl(args.marks_out)
    before_count = len(existing_rows)
    condensed_before = condense_snapshots(existing_rows)
    before_condensed_count = len(condensed_before)
    candidate_rows = condensed_before + [snapshot]
    condensed_after = condense_snapshots(candidate_rows)
    appended = len(condensed_after) > before_condensed_count
    removed_duplicates = before_count - before_condensed_count
    if appended or removed_duplicates > 0 or before_count != len(condensed_after):
        write_jsonl(args.marks_out, condensed_after)
    print(
        json.dumps(
            {
                "marks_out": args.marks_out,
                "captured_at_utc": snapshot["captured_at_utc"],
                "xsol_price": snapshot["xsol_price"],
                "price_source": snapshot["price_source"],
                "total_current_value": snapshot["summary"]["total_current_value"],
                "total_net_pnl": snapshot["summary"]["total_net_pnl"],
                "appended_mark": appended,
                "existing_marks_before": before_count,
                "marks_after": len(condensed_after),
                "removed_duplicate_marks": removed_duplicates,
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Track Stability Pool deployment lots from on-chain buy_xsol events."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    update = sub.add_parser("update")
    update.add_argument(
        "--events",
        default="data/stability_pool_balance_changes_full.jsonl",
        help="JSONL file from stability_pool_onchain_tracker.py backfill.",
    )
    update.add_argument(
        "--lots-out",
        default="data/stability_pool_deployments.json",
        help="Deployment-lot state JSON output.",
    )
    update.add_argument(
        "--marks-out",
        default="data/stability_pool_deployment_marks.jsonl",
        help="Mark-to-market snapshot JSONL output.",
    )
    update.add_argument("--hylo-stats-file", help="Hylo /api/hylo-stats JSON file.")
    update.add_argument("--xsol-price", type=float, help="Manual xSOL price in hyUSD/USD terms.")
    update.add_argument("--price-source", help="Optional price-source label override.")
    update.add_argument("--captured-at", help="Optional ISO timestamp override for the mark snapshot.")
    update.add_argument(
        "--allow-unconfirmed",
        action="store_true",
        help="Allow buy_xsol events without the full RebalanceStableToLever + SwapStableToLever hints.",
    )
    update.set_defaults(func=run_update)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
