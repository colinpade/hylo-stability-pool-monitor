#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import hylo_tx_scan as h


SHYUSD = "HnnGv3HrSqjRpgdFmx7vQGjntNEoex1SU4e9Lxcxuihz"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
POOL_AUTH_SEED = b"pool_auth"
EPSILON = 1e-12
LOG_HINTS = (
    "SwapStableToLever",
    "RebalanceStableToLever",
    "SwapLeverToStable",
    "Swap",
    "Route",
    "SharedAccountsRoute",
    "UserWithdraw",
    "Burn",
)
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {ch: i for i, ch in enumerate(BASE58_ALPHABET)}
P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
I = pow(2, (P - 1) // 4, P)
RPC_URL = h.RPC_URL


def now_utc():
    return datetime.now(timezone.utc)


def iso_utc(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def iso_local(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat()


def fmt_now(dt):
    return dt.isoformat()


def b58encode(data):
    if not data:
        return ""
    value = int.from_bytes(data, "big")
    out = []
    while value:
        value, rem = divmod(value, 58)
        out.append(BASE58_ALPHABET[rem])
    out.reverse()
    pad = 0
    for byte in data:
        if byte != 0:
            break
        pad += 1
    return ("1" * pad) + "".join(out)


def is_on_curve(pubkey_bytes):
    if len(pubkey_bytes) != 32:
        return False
    compressed = int.from_bytes(pubkey_bytes, "little")
    y = compressed & ((1 << 255) - 1)
    sign = compressed >> 255
    if y >= P:
        return False
    y2 = (y * y) % P
    u = (y2 - 1) % P
    v = (D * y2 + 1) % P
    if v == 0:
        return False
    x2 = (u * pow(v, P - 2, P)) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = (x * I) % P
    if (x * x - x2) % P != 0:
        return False
    if (x & 1) != sign:
        x = (-x) % P
    return True


def create_program_address(seeds, program_id):
    import hashlib

    raw = b"".join(seeds) + program_id + b"ProgramDerivedAddress"
    digest = hashlib.sha256(raw).digest()
    if is_on_curve(digest):
        raise ValueError("derived address is on curve")
    return digest


def find_program_address(seeds, program_id):
    for bump in range(255, -1, -1):
        try:
            return create_program_address(seeds + [bytes([bump])], program_id), bump
        except ValueError:
            continue
    raise RuntimeError("unable to derive PDA")


def derive_addresses():
    program = h.b58decode(h.STABILITY_POOL)
    pool_auth_raw, pool_auth_bump = find_program_address([POOL_AUTH_SEED], program)
    hyusd_pool_raw, hyusd_pool_bump = find_program_address(
        [pool_auth_raw, h.b58decode(TOKEN_PROGRAM), h.b58decode(h.HYUSD)],
        h.b58decode(ASSOCIATED_TOKEN_PROGRAM),
    )
    xsol_pool_raw, xsol_pool_bump = find_program_address(
        [pool_auth_raw, h.b58decode(TOKEN_PROGRAM), h.b58decode(h.XSOL)],
        h.b58decode(ASSOCIATED_TOKEN_PROGRAM),
    )
    return {
        "stability_pool_program": h.STABILITY_POOL,
        "pool_auth": b58encode(pool_auth_raw),
        "pool_auth_bump": pool_auth_bump,
        "hyusd_pool": b58encode(hyusd_pool_raw),
        "hyusd_pool_bump": hyusd_pool_bump,
        "xsol_pool": b58encode(xsol_pool_raw),
        "xsol_pool_bump": xsol_pool_bump,
        "hyusd_mint": h.HYUSD,
        "xsol_mint": h.XSOL,
        "shyusd_mint": SHYUSD,
    }


def rpc(method, params):
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    )
    delay = 0.7
    for _ in range(8):
        raw = subprocess.check_output(
            [
                "curl",
                "--http1.1",
                "-s",
                RPC_URL,
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
            ],
            text=True,
        )
        data = json.loads(raw)
        error = data.get("error")
        if not error:
            return data["result"]
        if error.get("code") != 429:
            raise RuntimeError(error)
        time.sleep(delay)
        delay *= 1.6
    raise RuntimeError("RPC rate limit retries exhausted")


def get_sigs(address, limit=100, before=None):
    opts = {"limit": limit}
    if before:
        opts["before"] = before
    return rpc("getSignaturesForAddress", [address, opts])


def get_txs_batch(sigs):
    return [
        rpc(
            "getTransaction",
            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        for sig in sigs
    ]


def parse_token_account(account):
    info = account["data"]["parsed"]["info"]
    amount = info["tokenAmount"]
    return {
        "address": None,
        "mint": info["mint"],
        "owner": info["owner"],
        "amount_raw": int(amount["amount"]),
        "decimals": int(amount["decimals"]),
        "amount": float(amount["uiAmountString"]),
    }


def parse_mint_account(account):
    info = account["data"]["parsed"]["info"]
    return {
        "address": None,
        "supply_raw": int(info["supply"]),
        "decimals": int(info["decimals"]),
        "supply": int(info["supply"]) / (10 ** int(info["decimals"])),
        "mint_authority": info.get("mintAuthority"),
    }


def get_current_snapshot():
    addrs = derive_addresses()
    result = rpc(
        "getMultipleAccounts",
        [[addrs["hyusd_pool"], addrs["xsol_pool"], addrs["shyusd_mint"]], {"encoding": "jsonParsed"}],
    )
    slot = result["context"]["slot"]
    hyusd_pool = parse_token_account(result["value"][0])
    hyusd_pool["address"] = addrs["hyusd_pool"]
    xsol_pool = parse_token_account(result["value"][1])
    xsol_pool["address"] = addrs["xsol_pool"]
    shyusd = parse_mint_account(result["value"][2])
    shyusd["address"] = addrs["shyusd_mint"]
    stamp = now_utc()
    return {
        "captured_at_utc": fmt_now(stamp),
        "captured_at_local": stamp.astimezone().isoformat(),
        "slot": slot,
        "derived_accounts": addrs,
        "hyusd_pool": hyusd_pool,
        "xsol_pool": xsol_pool,
        "shyusd_mint": shyusd,
    }


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def classify_balance_change(hyusd_delta, xsol_delta):
    hyusd_changed = abs(hyusd_delta) > EPSILON
    xsol_changed = abs(xsol_delta) > EPSILON
    if not hyusd_changed and not xsol_changed:
        return "unchanged"
    if hyusd_delta < -EPSILON and xsol_delta > EPSILON:
        return "buy_xsol"
    if hyusd_delta > EPSILON and xsol_delta < -EPSILON:
        return "sell_xsol"
    if hyusd_delta > EPSILON and xsol_delta > EPSILON:
        return "pool_grew_both"
    if hyusd_delta < -EPSILON and xsol_delta < -EPSILON:
        return "pool_shrank_both"
    if hyusd_changed:
        return "hyusd_only"
    return "xsol_only"


def add_snapshot_delta(snapshot, previous):
    if not previous:
        snapshot["delta"] = None
        snapshot["action"] = "initial"
        snapshot["estimated_hyusd_per_xsol"] = None
        return snapshot

    hyusd_delta = snapshot["hyusd_pool"]["amount"] - previous["hyusd_pool"]["amount"]
    xsol_delta = snapshot["xsol_pool"]["amount"] - previous["xsol_pool"]["amount"]
    shyusd_delta = snapshot["shyusd_mint"]["supply"] - previous["shyusd_mint"]["supply"]
    snapshot["delta"] = {
        "hyusd_pool": hyusd_delta,
        "xsol_pool": xsol_delta,
        "shyusd_supply": shyusd_delta,
    }
    snapshot["action"] = classify_balance_change(hyusd_delta, xsol_delta)
    if snapshot["action"] in {"buy_xsol", "sell_xsol"} and abs(xsol_delta) > EPSILON:
        snapshot["estimated_hyusd_per_xsol"] = abs(hyusd_delta) / abs(xsol_delta)
    else:
        snapshot["estimated_hyusd_per_xsol"] = None
    return snapshot


def all_account_keys(tx):
    keys = []
    message = tx["transaction"]["message"]
    for entry in message.get("accountKeys", []):
        if isinstance(entry, str):
            keys.append(entry)
        else:
            keys.append(entry["pubkey"])
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable", []))
    keys.extend(loaded.get("readonly", []))
    return keys


def extract_pool_balance_change(tx, derived):
    keys = all_account_keys(tx)
    targets = {
        derived["hyusd_pool"]: {
            "label": "hyusd_pool",
            "mint": derived["hyusd_mint"],
        },
        derived["xsol_pool"]: {
            "label": "xsol_pool",
            "mint": derived["xsol_mint"],
        },
    }
    balances = {}
    meta = tx.get("meta") or {}
    for group_name, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for row in meta.get(group_name, []):
            idx = row["accountIndex"]
            if idx >= len(keys):
                continue
            address = keys[idx]
            if address not in targets:
                continue
            amount = int(row["uiTokenAmount"]["amount"])
            decimals = int(row["uiTokenAmount"]["decimals"])
            state = balances.setdefault(
                address,
                {
                    "label": targets[address]["label"],
                    "mint": row["mint"],
                    "owner": row.get("owner"),
                    "decimals": decimals,
                    "pre_raw": 0,
                    "post_raw": 0,
                },
            )
            if sign < 0:
                state["pre_raw"] = amount
            else:
                state["post_raw"] = amount

    out = {}
    for address, meta_row in targets.items():
        state = balances.get(
            address,
            {
                "label": meta_row["label"],
                "mint": meta_row["mint"],
                "owner": derived["pool_auth"],
                "decimals": 6,
                "pre_raw": 0,
                "post_raw": 0,
            },
        )
        scale = 10 ** state["decimals"]
        out[state["label"]] = {
            "address": address,
            "mint": state["mint"],
            "owner": state["owner"],
            "pre_raw": state["pre_raw"],
            "post_raw": state["post_raw"],
            "pre_amount": state["pre_raw"] / scale,
            "post_amount": state["post_raw"] / scale,
            "delta": (state["post_raw"] - state["pre_raw"]) / scale,
        }
    return out


def signature_union(addresses, max_pages, page_size):
    rows = {}
    for address in addresses:
        before = None
        for _ in range(max_pages):
            batch = get_sigs(address, limit=page_size, before=before)
            if not batch:
                break
            for item in batch:
                rows[item["signature"]] = item
            before = batch[-1]["signature"]
            if len(batch) < page_size:
                break
    ordered = sorted(
        rows.values(),
        key=lambda row: (
            row.get("slot") or 0,
            row.get("blockTime") or 0,
            row["signature"],
        ),
    )
    return ordered


def probe_address(address, max_pages, page_size):
    before = None
    total = 0
    pages = 0
    newest = None
    oldest = None
    while pages < max_pages:
        batch = get_sigs(address, limit=page_size, before=before)
        if not batch:
            break
        pages += 1
        total += len(batch)
        if newest is None:
            newest = batch[0]
        oldest = batch[-1]
        before = oldest["signature"]
        if len(batch) < page_size:
            break
    return {
        "address": address,
        "pages_scanned": pages,
        "signatures_scanned": total,
        "newest_signature": newest["signature"] if newest else None,
        "newest_block_time": newest.get("blockTime") if newest else None,
        "newest_utc": iso_utc(newest.get("blockTime")) if newest else None,
        "oldest_signature": oldest["signature"] if oldest else None,
        "oldest_block_time": oldest.get("blockTime") if oldest else None,
        "oldest_utc": iso_utc(oldest.get("blockTime")) if oldest else None,
        "reached_end": bool(oldest and pages < max_pages),
    }


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def log_hints(tx):
    hints = []
    logs = (tx.get("meta") or {}).get("logMessages") or []
    for needle in LOG_HINTS:
        if any(needle in line for line in logs):
            hints.append(needle)
    return hints


def build_recent_history(max_pages, page_size):
    derived = derive_addresses()
    sig_rows = signature_union(
        [derived["hyusd_pool"], derived["xsol_pool"]],
        max_pages=max_pages,
        page_size=page_size,
    )
    events = []
    for batch in chunked([row["signature"] for row in sig_rows], 40):
        txs = get_txs_batch(batch)
        for sig, tx in zip(batch, txs):
            if not tx:
                continue
            balances = extract_pool_balance_change(tx, derived)
            hyusd_delta = balances["hyusd_pool"]["delta"]
            xsol_delta = balances["xsol_pool"]["delta"]
            action = classify_balance_change(hyusd_delta, xsol_delta)
            if action == "unchanged":
                continue
            block_time = tx.get("blockTime")
            event = {
                "signature": sig,
                "solscan_url": f"https://solscan.io/tx/{sig}",
                "slot": tx.get("slot"),
                "block_time": block_time,
                "utc": iso_utc(block_time),
                "local": iso_local(block_time),
                "action": action,
                "hyusd_pool": balances["hyusd_pool"],
                "xsol_pool": balances["xsol_pool"],
                "estimated_hyusd_per_xsol": (
                    abs(hyusd_delta) / abs(xsol_delta)
                    if action in {"buy_xsol", "sell_xsol"} and abs(xsol_delta) > EPSILON
                    else None
                ),
                "log_hints": log_hints(tx),
            }
            events.append(event)
    events.sort(key=lambda row: (row["slot"] or 0, row["signature"]))
    return {
        "captured_at_utc": fmt_now(now_utc()),
        "derived_accounts": derived,
        "events": events,
    }


def write_history_jsonl(path, history):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in history["events"]:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def print_addresses():
    print(json.dumps(derive_addresses(), indent=2, sort_keys=True))


def run_snapshot(args):
    path = Path(args.out)
    existing = load_jsonl(path)
    previous = existing[-1] if existing else None
    for idx in range(args.iterations):
        snapshot = add_snapshot_delta(get_current_snapshot(), previous)
        append_jsonl(path, snapshot)
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        previous = snapshot
        if idx + 1 < args.iterations:
            time.sleep(args.interval)


def run_backfill(args):
    history = build_recent_history(max_pages=args.max_pages, page_size=args.page_size)
    path = Path(args.out)
    write_history_jsonl(path, history)
    print(json.dumps(history, indent=2, sort_keys=True))


def run_probe(args):
    derived = derive_addresses()
    targets = {
        "pool_auth": derived["pool_auth"],
        "hyusd_pool": derived["hyusd_pool"],
        "xsol_pool": derived["xsol_pool"],
    }
    out = {}
    for label, address in targets.items():
        out[label] = probe_address(address, max_pages=args.max_pages, page_size=args.page_size)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(
        description="Track Hylo Stability Pool balances directly from on-chain pool accounts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("addresses", help="Print derived Stability Pool addresses.")

    snapshot = subparsers.add_parser(
        "snapshot",
        help="Capture current on-chain balances and append a JSONL snapshot.",
    )
    snapshot.add_argument(
        "--out",
        default="data/stability_pool_balance_snapshots.jsonl",
        help="Path to JSONL snapshot log.",
    )
    snapshot.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of snapshots to capture.",
    )
    snapshot.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between snapshot captures when iterations > 1.",
    )

    backfill = subparsers.add_parser(
        "backfill",
        help="Reconstruct recent balance-changing txs from the pool token-account history.",
    )
    backfill.add_argument(
        "--out",
        default="data/stability_pool_balance_changes.jsonl",
        help="Path to JSONL output.",
    )
    backfill.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Pages of signatures to fetch per pool token account.",
    )
    backfill.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Signatures per page for each pool token account.",
    )

    probe = subparsers.add_parser(
        "probe",
        help="Measure public signature history depth for the derived pool addresses.",
    )
    probe.add_argument(
        "--out",
        default="data/stability_pool_account_probe.json",
        help="Optional JSON output path.",
    )
    probe.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum signature pages to scan per address.",
    )
    probe.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="Signatures per page.",
    )

    args = parser.parse_args()
    if args.command == "addresses":
        print_addresses()
    elif args.command == "snapshot":
        run_snapshot(args)
    elif args.command == "backfill":
        run_backfill(args)
    elif args.command == "probe":
        run_probe(args)


if __name__ == "__main__":
    main()
