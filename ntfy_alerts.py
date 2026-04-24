#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable
import urllib.request
from zoneinfo import ZoneInfo


NTFY_BASE_URL = "https://ntfy.sh"
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
REQUIRED_BUY_HINTS = {"RebalanceStableToLever", "SwapStableToLever"}
REQUIRED_SELL_HINTS = {"SwapLeverToStable"}
INITIAL_MODEL_HYUSD = Decimal("10000")


@dataclass(frozen=True)
class NtfyAlert:
    title: str
    body: str


def is_present(value):
    return value not in (None, "")


def parse_auth_header(header):
    if not is_present(header):
        return None
    name, separator, value = str(header).partition(":")
    if not separator or not name.strip() or not value.strip():
        raise ValueError("auth header must use 'Name: value' format")
    return name.strip(), value.lstrip()


def round_to_whole(value):
    if not is_present(value):
        return value
    try:
        return str(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return str(value)


def format_decimal_places(value, places):
    if not is_present(value):
        return value
    quantum = Decimal("1").scaleb(-places)
    try:
        return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return str(value)


def to_decimal(value, default=None):
    if not is_present(value):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def quantize(value, quantum):
    if value is None:
        return None
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def percent_of(part, whole):
    part_decimal = to_decimal(part)
    whole_decimal = to_decimal(whole)
    if part_decimal is None or whole_decimal in (None, Decimal("0")):
        return None
    return (part_decimal / whole_decimal) * Decimal("100")


def format_percent(value, digits=1):
    decimal_value = to_decimal(value)
    if decimal_value is None:
        return ""
    quantum = Decimal("1").scaleb(-digits)
    return f"{quantize(decimal_value, quantum)}%"


def format_whole_percent(value):
    decimal_value = to_decimal(value)
    if decimal_value is None:
        return ""
    return f"{quantize(decimal_value, Decimal('1'))}%"


def format_usd_whole(value):
    decimal_value = to_decimal(value)
    if decimal_value is None:
        return ""
    rounded_value = int(quantize(decimal_value, Decimal("1")))
    return f"${rounded_value:,}"


def format_pt_time(timestamp):
    if not is_present(timestamp):
        return ""
    dt = datetime.fromisoformat(str(timestamp))
    local_dt = dt.astimezone(LOS_ANGELES)
    return local_dt.strftime("%I:%M %p PT").lstrip("0")


def required_hints_for_action(action):
    if action == "buy_xsol":
        return REQUIRED_BUY_HINTS
    if action == "sell_xsol":
        return REQUIRED_SELL_HINTS
    return set()


def is_confirmed_trade_event(event, action=None):
    event_action = event.get("action")
    if action and event_action != action:
        return False
    required_hints = required_hints_for_action(event_action)
    if not required_hints:
        return False
    hints = set(event.get("log_hints") or [])
    return required_hints.issubset(hints)


def sort_trade_events(events):
    return sorted(
        events,
        key=lambda row: (
            row.get("slot") or 0,
            row.get("block_time") or 0,
            row.get("signature") or "",
        ),
    )


def confirmed_trade_events(events, action=None):
    return [
        row
        for row in sort_trade_events(events)
        if is_confirmed_trade_event(row, action=action)
    ]


def new_trade_events(events, action, prev_signature=""):
    filtered = confirmed_trade_events(events, action=action)
    if not prev_signature:
        return filtered
    matches = [idx for idx, row in enumerate(filtered) if row.get("signature") == prev_signature]
    if not matches:
        return filtered
    return filtered[matches[-1] + 1 :]


def compute_mirror_action_percent(events, action):
    if not events:
        return None
    if action == "buy_xsol":
        total_amount = sum(abs(to_decimal((row.get("hyusd_pool") or {}).get("delta"), Decimal("0"))) for row in events)
        denominator = to_decimal((events[0].get("hyusd_pool") or {}).get("pre_amount"))
    elif action == "sell_xsol":
        total_amount = sum(abs(to_decimal((row.get("xsol_pool") or {}).get("delta"), Decimal("0"))) for row in events)
        denominator = to_decimal((events[0].get("xsol_pool") or {}).get("pre_amount"))
    else:
        return None
    if denominator in (None, Decimal("0")):
        return None
    return (total_amount / denominator) * Decimal("100")


def compute_target_allocation(post_hyusd, post_xsol, price):
    hyusd_value = to_decimal(post_hyusd)
    xsol_amount = to_decimal(post_xsol)
    price_decimal = to_decimal(price)
    if hyusd_value is None or xsol_amount is None or price_decimal is None:
        return None, None
    xsol_value = xsol_amount * price_decimal
    total_value = hyusd_value + xsol_value
    if total_value == 0:
        return None, None
    xsol_pct = (xsol_value / total_value) * Decimal("100")
    hyusd_pct = (hyusd_value / total_value) * Decimal("100")
    return xsol_pct, hyusd_pct


def compute_target_allocation_from_event(event):
    hyusd_pool = event.get("hyusd_pool") or {}
    xsol_pool = event.get("xsol_pool") or {}
    return compute_target_allocation(
        hyusd_pool.get("post_amount"),
        xsol_pool.get("post_amount"),
        event.get("estimated_hyusd_per_xsol"),
    )


def build_model_snapshots(events, initial_hyusd=INITIAL_MODEL_HYUSD):
    cash = to_decimal(initial_hyusd, INITIAL_MODEL_HYUSD)
    xsol_units = Decimal("0")
    snapshots = {}
    for row in confirmed_trade_events(events):
        action = row.get("action")
        price = to_decimal(row.get("estimated_hyusd_per_xsol"))
        if price in (None, Decimal("0")):
            continue
        if action == "buy_xsol":
            trade_pct = percent_of(
                abs(to_decimal((row.get("hyusd_pool") or {}).get("delta"), Decimal("0"))),
                (row.get("hyusd_pool") or {}).get("pre_amount"),
            )
            if trade_pct is None:
                continue
            spend = cash * (trade_pct / Decimal("100"))
            xsol_units += spend / price
            cash -= spend
            action_value = spend
        elif action == "sell_xsol":
            trade_pct = percent_of(
                abs(to_decimal((row.get("xsol_pool") or {}).get("delta"), Decimal("0"))),
                (row.get("xsol_pool") or {}).get("pre_amount"),
            )
            if trade_pct is None:
                continue
            units_sold = xsol_units * (trade_pct / Decimal("100"))
            proceeds = units_sold * price
            xsol_units -= units_sold
            cash += proceeds
            action_value = proceeds
        else:
            continue
        xsol_value = xsol_units * price
        total_value = cash + xsol_value
        xsol_pct = (xsol_value / total_value) * Decimal("100") if total_value else None
        hyusd_pct = (cash / total_value) * Decimal("100") if total_value else None
        snapshots[row.get("signature")] = {
            "action": action,
            "action_value": action_value,
            "cash": cash,
            "xsol_units": xsol_units,
            "xsol_value": xsol_value,
            "total_value": total_value,
            "xsol_pct": xsol_pct,
            "hyusd_pct": hyusd_pct,
            "price": price,
            "utc": row.get("utc") or "",
        }
    return snapshots


def sum_model_action_value(snapshots, signatures):
    total = Decimal("0")
    for signature in signatures:
        snapshot = snapshots.get(signature)
        if snapshot:
            total += snapshot["action_value"]
    return total


def build_mirror_buy_alert(
    *,
    mirror_percent,
    target_xsol_pct,
    target_hyusd_pct,
    buy_time_utc,
    entry_price,
    tx,
):
    return NtfyAlert(
        title=f"Hylo Mirror: Buy {format_percent(mirror_percent, 1)} of cash",
        body=(
            f"Target allocation: {format_whole_percent(target_xsol_pct)} xSOL / {format_whole_percent(target_hyusd_pct)} hyUSD\n"
            f"Buy time: {format_pt_time(buy_time_utc)}\n"
            f"Entry price: {format_decimal_places(entry_price, 5)}\n"
            f"Tx: https://solscan.io/tx/{tx}"
        ),
    )


def build_mirror_sell_alert(
    *,
    mirror_percent,
    target_xsol_pct,
    target_hyusd_pct,
    sell_time_utc,
    sale_price,
    tx,
):
    return NtfyAlert(
        title=f"Hylo Mirror: Sell {format_percent(mirror_percent, 1)} of xSOL",
        body=(
            f"Target allocation: {format_whole_percent(target_xsol_pct)} xSOL / {format_whole_percent(target_hyusd_pct)} hyUSD\n"
            f"Sell time: {format_pt_time(sell_time_utc)}\n"
            f"Sale price: {format_decimal_places(sale_price, 5)}\n"
            f"Tx: https://solscan.io/tx/{tx}"
        ),
    )


def build_model_buy_alert(
    *,
    action_usd,
    after_xsol_usd,
    after_hyusd_usd,
    after_xsol_pct,
    after_hyusd_pct,
    target_xsol_pct,
    target_hyusd_pct,
    buy_time_utc,
    entry_price,
):
    return NtfyAlert(
        title=f"Hylo $10k Model: Buy {format_usd_whole(action_usd)} of xSOL",
        body=(
            f"After trade: {format_usd_whole(after_xsol_usd)} xSOL / {format_usd_whole(after_hyusd_usd)} hyUSD "
            f"({format_whole_percent(after_xsol_pct)} / {format_whole_percent(after_hyusd_pct)})\n"
            f"Target allocation: {format_whole_percent(target_xsol_pct)} xSOL / {format_whole_percent(target_hyusd_pct)} hyUSD\n"
            f"Buy time: {format_pt_time(buy_time_utc)}\n"
            f"Entry price: {format_decimal_places(entry_price, 5)}"
        ),
    )


def build_model_sell_alert(
    *,
    action_usd,
    after_xsol_usd,
    after_hyusd_usd,
    after_xsol_pct,
    after_hyusd_pct,
    target_xsol_pct,
    target_hyusd_pct,
    sell_time_utc,
    sale_price,
):
    return NtfyAlert(
        title=f"Hylo $10k Model: Sell {format_usd_whole(action_usd)} of xSOL",
        body=(
            f"After trade: {format_usd_whole(after_xsol_usd)} xSOL / {format_usd_whole(after_hyusd_usd)} hyUSD "
            f"({format_whole_percent(after_xsol_pct)} / {format_whole_percent(after_hyusd_pct)})\n"
            f"Target allocation: {format_whole_percent(target_xsol_pct)} xSOL / {format_whole_percent(target_hyusd_pct)} hyUSD\n"
            f"Sell time: {format_pt_time(sell_time_utc)}\n"
            f"Sale price: {format_decimal_places(sale_price, 5)}"
        ),
    )


def build_buy_alert(
    *,
    local_time,
    amount,
    spent,
    tx,
    pages_url,
    setup_grade,
    setup_score="",
    setup_expected_24h="",
    setup_confidence="",
    setup_reason="",
):
    title = "Hylo Stability Pool setup cleared alert bar"
    body = (
        f"New confirmed deployment at {local_time}\n"
        f"xSOL: {amount}\n"
        f"hyUSD spent: {spent}\n"
        f"Setup: {setup_grade}"
    )
    if is_present(setup_score):
        body = f"{body} • score {setup_score}"
    if is_present(setup_expected_24h):
        body = f"{body} • exp 24h {setup_expected_24h}%"
    body = (
        f"{body}\n"
        f"Confidence: {setup_confidence}\n"
        f"Why: {setup_reason}\n"
        f"Dashboard: {pages_url}\n"
        f"Tx: https://solscan.io/tx/{tx}"
    )
    return NtfyAlert(title=title, body=body)


def resolve_sell_time(local_time="", utc_time=""):
    if is_present(local_time):
        return local_time
    return utc_time


def build_sell_alert(
    *,
    sell_count,
    sell_time,
    sold,
    received,
    total_sold,
    total_received,
    sale_price,
    affected_lots,
    closed_lots,
    partial_lots,
    tx,
    pages_url,
):
    title = "Hylo Stability Pool sold xSOL"
    body = (
        f"Confirmed xSOL sale at {sell_time}\n"
        f"xSOL sold: {sold}\n"
        f"hyUSD received: {received}"
    )
    if is_present(sell_count) and sell_count != "1":
        title = f"Hylo Stability Pool recorded {sell_count} xSOL sells"
        body = (
            f"New confirmed xSOL sells: {sell_count}\n"
            f"Total xSOL sold: {round_to_whole(total_sold)}\n"
            f"Latest sell at {sell_time}\n"
            f"Latest xSOL sold: {sold}"
        )
    if is_present(sale_price):
        body = f"{body}\nSale price: {format_decimal_places(sale_price, 5)}"
    if is_present(closed_lots) and closed_lots != "0":
        body = f"{body}\nClosed lots: {closed_lots}"
    body = f"{body}\nTx: https://solscan.io/tx/{tx}"
    return NtfyAlert(title=title, body=body)


def publish_alert(
    topic,
    alert,
    auth_header="",
    opener: Callable = urllib.request.urlopen,
    timeout=30,
):
    request = urllib.request.Request(
        f"{NTFY_BASE_URL}/{topic}",
        data=alert.body.encode("utf-8"),
        method="POST",
        headers={"Title": alert.title},
    )
    parsed_header = parse_auth_header(auth_header)
    if parsed_header:
        name, value = parsed_header
        request.add_header(name, value)
    with opener(request, timeout=timeout) as response:
        response.read()


def build_parser():
    parser = argparse.ArgumentParser(description="Send Stability Pool ntfy.sh alerts.")
    parser.add_argument("--topic", required=True, help="ntfy.sh topic name.")
    parser.add_argument("--auth-header", default="", help="Optional auth header in 'Name: value' format.")
    subparsers = parser.add_subparsers(dest="kind", required=True)

    buy = subparsers.add_parser("buy", help="Send a deployment/setup alert.")
    buy.add_argument("--local-time", required=True)
    buy.add_argument("--amount", required=True)
    buy.add_argument("--spent", required=True)
    buy.add_argument("--tx", required=True)
    buy.add_argument("--pages-url", required=True)
    buy.add_argument("--setup-grade", required=True)
    buy.add_argument("--setup-score", default="")
    buy.add_argument("--setup-expected-24h", default="")
    buy.add_argument("--setup-confidence", default="")
    buy.add_argument("--setup-reason", default="")

    sell = subparsers.add_parser("sell", help="Send a sell alert.")
    sell.add_argument("--sell-count", default="")
    sell.add_argument("--sell-local-time", default="")
    sell.add_argument("--sell-utc-time", default="")
    sell.add_argument("--sold", required=True)
    sell.add_argument("--received", required=True)
    sell.add_argument("--total-sold", default="")
    sell.add_argument("--total-received", default="")
    sell.add_argument("--sale-price", default="")
    sell.add_argument("--affected-lots", default="")
    sell.add_argument("--closed-lots", default="")
    sell.add_argument("--partial-lots", default="")
    sell.add_argument("--tx", required=True)
    sell.add_argument("--pages-url", required=True)

    mirror_buy = subparsers.add_parser("mirror-buy", help="Send a mirror buy alert.")
    mirror_buy.add_argument("--mirror-percent", required=True)
    mirror_buy.add_argument("--target-xsol-pct", required=True)
    mirror_buy.add_argument("--target-hyusd-pct", required=True)
    mirror_buy.add_argument("--buy-time-utc", required=True)
    mirror_buy.add_argument("--entry-price", required=True)
    mirror_buy.add_argument("--tx", required=True)

    mirror_sell = subparsers.add_parser("mirror-sell", help="Send a mirror sell alert.")
    mirror_sell.add_argument("--mirror-percent", required=True)
    mirror_sell.add_argument("--target-xsol-pct", required=True)
    mirror_sell.add_argument("--target-hyusd-pct", required=True)
    mirror_sell.add_argument("--sell-time-utc", required=True)
    mirror_sell.add_argument("--sale-price", required=True)
    mirror_sell.add_argument("--tx", required=True)

    model_buy = subparsers.add_parser("model-buy", help="Send a $10k model buy alert.")
    model_buy.add_argument("--action-usd", required=True)
    model_buy.add_argument("--after-xsol-usd", required=True)
    model_buy.add_argument("--after-hyusd-usd", required=True)
    model_buy.add_argument("--after-xsol-pct", required=True)
    model_buy.add_argument("--after-hyusd-pct", required=True)
    model_buy.add_argument("--target-xsol-pct", required=True)
    model_buy.add_argument("--target-hyusd-pct", required=True)
    model_buy.add_argument("--buy-time-utc", required=True)
    model_buy.add_argument("--entry-price", required=True)

    model_sell = subparsers.add_parser("model-sell", help="Send a $10k model sell alert.")
    model_sell.add_argument("--action-usd", required=True)
    model_sell.add_argument("--after-xsol-usd", required=True)
    model_sell.add_argument("--after-hyusd-usd", required=True)
    model_sell.add_argument("--after-xsol-pct", required=True)
    model_sell.add_argument("--after-hyusd-pct", required=True)
    model_sell.add_argument("--target-xsol-pct", required=True)
    model_sell.add_argument("--target-hyusd-pct", required=True)
    model_sell.add_argument("--sell-time-utc", required=True)
    model_sell.add_argument("--sale-price", required=True)

    return parser


def main(argv=None, opener: Callable = urllib.request.urlopen):
    args = build_parser().parse_args(argv)
    if args.kind == "buy":
        alert = build_buy_alert(
            local_time=args.local_time,
            amount=args.amount,
            spent=args.spent,
            tx=args.tx,
            pages_url=args.pages_url,
            setup_grade=args.setup_grade,
            setup_score=args.setup_score,
            setup_expected_24h=args.setup_expected_24h,
            setup_confidence=args.setup_confidence,
            setup_reason=args.setup_reason,
        )
    elif args.kind == "sell":
        alert = build_sell_alert(
            sell_count=args.sell_count,
            sell_time=resolve_sell_time(args.sell_local_time, args.sell_utc_time),
            sold=args.sold,
            received=args.received,
            total_sold=args.total_sold,
            total_received=args.total_received,
            sale_price=args.sale_price,
            affected_lots=args.affected_lots,
            closed_lots=args.closed_lots,
            partial_lots=args.partial_lots,
            tx=args.tx,
            pages_url=args.pages_url,
        )
    elif args.kind == "mirror-buy":
        alert = build_mirror_buy_alert(
            mirror_percent=args.mirror_percent,
            target_xsol_pct=args.target_xsol_pct,
            target_hyusd_pct=args.target_hyusd_pct,
            buy_time_utc=args.buy_time_utc,
            entry_price=args.entry_price,
            tx=args.tx,
        )
    elif args.kind == "mirror-sell":
        alert = build_mirror_sell_alert(
            mirror_percent=args.mirror_percent,
            target_xsol_pct=args.target_xsol_pct,
            target_hyusd_pct=args.target_hyusd_pct,
            sell_time_utc=args.sell_time_utc,
            sale_price=args.sale_price,
            tx=args.tx,
        )
    elif args.kind == "model-buy":
        alert = build_model_buy_alert(
            action_usd=args.action_usd,
            after_xsol_usd=args.after_xsol_usd,
            after_hyusd_usd=args.after_hyusd_usd,
            after_xsol_pct=args.after_xsol_pct,
            after_hyusd_pct=args.after_hyusd_pct,
            target_xsol_pct=args.target_xsol_pct,
            target_hyusd_pct=args.target_hyusd_pct,
            buy_time_utc=args.buy_time_utc,
            entry_price=args.entry_price,
        )
    elif args.kind == "model-sell":
        alert = build_model_sell_alert(
            action_usd=args.action_usd,
            after_xsol_usd=args.after_xsol_usd,
            after_hyusd_usd=args.after_hyusd_usd,
            after_xsol_pct=args.after_xsol_pct,
            after_hyusd_pct=args.after_hyusd_pct,
            target_xsol_pct=args.target_xsol_pct,
            target_hyusd_pct=args.target_hyusd_pct,
            sell_time_utc=args.sell_time_utc,
            sale_price=args.sale_price,
        )
    else:
        raise ValueError(f"unsupported alert kind: {args.kind}")
    publish_alert(args.topic, alert, auth_header=args.auth_header, opener=opener)


if __name__ == "__main__":
    main()
