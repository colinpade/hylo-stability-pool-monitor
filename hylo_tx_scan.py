#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


RPC_URL = os.environ.get("RPC_URL", "https://solana-rpc.publicnode.com")
EXCHANGE = "HYEXCHtHkBagdStcJCp3xbbb9B7sdMdWXFNj6mdsG4hn"
STABILITY_POOL = "HysTabVUfmQBFcmzu1ctRd1Y1fxd66RBpboy1bmtDSQQ"
HYUSD = "5YMkXAYccHSGnHn9nob9xEvv6Pvka9DZWH7nTbotTu9E"
XSOL = "4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs"
TARGETS = [
    (30131.233824, 498493.006733),
    (11552.792571, 190916.507256),
    (23479.769439, 386742.798409),
    (21061.983677, 344971.328588),
]
SWAP_STABLE_TO_LEVER_EVENT_V1 = bytes([184, 185, 154, 14, 36, 128, 241, 53])
REBALANCE_STABLE_TO_LEVER_EVENT = bytes([117, 99, 97, 34, 247, 186, 34, 198])
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {ch: i for i, ch in enumerate(BASE58_ALPHABET)}


def rpc(method, params):
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    )
    cmd = (
        "curl --http1.1 -s "
        + RPC_URL
        + " -H 'Content-Type: application/json' -d "
        + json.dumps(payload)
    )
    delay = 0.7
    for _ in range(8):
        out = subprocess.check_output(
            ["/bin/zsh", "-lc", cmd],
            text=True,
        )
        data = json.loads(out)
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


def get_tx(sig):
    return rpc(
        "getTransaction",
        [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )


def get_txs_batch(sigs):
    payload = []
    for i, sig in enumerate(sigs, start=1):
        payload.append(
            {
                "jsonrpc": "2.0",
                "id": i,
                "method": "getTransaction",
                "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            }
        )
    cmd = (
        "curl --http1.1 -s "
        + RPC_URL
        + " -H 'Content-Type: application/json' -d "
        + json.dumps(json.dumps(payload, separators=(",", ":")))
    )
    delay = 0.8
    for _ in range(8):
        out = subprocess.check_output(
            ["/bin/zsh", "-lc", cmd],
            text=True,
        )
        data = json.loads(out)
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            if error.get("code") != 429:
                raise RuntimeError(error)
            time.sleep(delay)
            delay *= 1.6
            continue
        if isinstance(data, list):
            by_id = {item["id"]: item.get("result") for item in data}
            return [by_id.get(i) for i in range(1, len(sigs) + 1)]
    raise RuntimeError("RPC rate limit retries exhausted for batch")


def extract_transfers(tx):
    transfers = []
    meta = tx.get("meta") or {}
    for group in meta.get("innerInstructions", []):
        for ins in group.get("instructions", []):
            parsed = ins.get("parsed")
            if not parsed or parsed.get("type") != "transferChecked":
                continue
            info = parsed.get("info", {})
            token_amount = info.get("tokenAmount") or {}
            transfers.append(
                {
                    "mint": info.get("mint"),
                    "amount": float(token_amount.get("uiAmount") or 0),
                    "source": info.get("source"),
                    "destination": info.get("destination"),
                    "authority": info.get("authority"),
                }
            )
    return transfers


def token_diffs(tx):
    diffs = []
    meta = tx.get("meta") or {}
    pre = {
        b["accountIndex"]: (
            b["mint"],
            int(b["uiTokenAmount"]["amount"]),
            b["uiTokenAmount"]["decimals"],
            b.get("owner"),
        )
        for b in meta.get("preTokenBalances", [])
    }
    post = {
        b["accountIndex"]: (
            b["mint"],
            int(b["uiTokenAmount"]["amount"]),
            b["uiTokenAmount"]["decimals"],
            b.get("owner"),
        )
        for b in meta.get("postTokenBalances", [])
    }
    for idx in sorted(set(pre) | set(post)):
        if idx in pre:
            mint, before, decimals, owner = pre[idx]
        else:
            mint, _, decimals, owner = post[idx]
            before = 0
        after = post.get(idx, (mint, 0, decimals, owner))[1]
        if before == after:
            continue
        diffs.append(
            {
                "account_index": idx,
                "mint": mint,
                "owner": owner,
                "diff": (after - before) / (10**decimals),
            }
        )
    return diffs


def decode_ufix64(buf, offset):
    bits = int.from_bytes(buf[offset : offset + 8], "little")
    exp = int.from_bytes(buf[offset + 8 : offset + 9], "little", signed=True)
    return bits * (10**exp), offset + 9


def b58decode(data):
    value = 0
    for ch in data:
        value = value * 58 + BASE58_INDEX[ch]
    out = bytearray()
    while value:
        value, rem = divmod(value, 256)
        out.append(rem)
    out.reverse()
    leading_zeros = 0
    for ch in data:
        if ch != "1":
            break
        leading_zeros += 1
    return bytes([0] * leading_zeros) + bytes(out)


def decode_event_payload(raw):
    out = []
    if raw.startswith(SWAP_STABLE_TO_LEVER_EVENT_V1):
        off = 8
        stablecoin_burned, off = decode_ufix64(raw, off)
        stablecoin_fees, off = decode_ufix64(raw, off)
        stablecoin_nav, off = decode_ufix64(raw, off)
        levercoin_minted, off = decode_ufix64(raw, off)
        levercoin_nav, off = decode_ufix64(raw, off)
        out.append(
            {
                "event": "SwapStableToLeverEventV1",
                "stablecoin_burned": stablecoin_burned,
                "stablecoin_fees": stablecoin_fees,
                "stablecoin_nav": stablecoin_nav,
                "levercoin_minted": levercoin_minted,
                "levercoin_nav": levercoin_nav,
                "source": "log_program_data",
            }
        )
    elif raw.startswith(REBALANCE_STABLE_TO_LEVER_EVENT):
        value, _ = decode_ufix64(raw, 8)
        out.append(
            {
                "event": "RebalanceStableToLeverEvent",
                "stablecoin_swapped": value,
                "source": "log_program_data",
            }
        )
    elif len(raw) >= 16 and raw[8:16] == SWAP_STABLE_TO_LEVER_EVENT_V1:
        off = 16
        stablecoin_burned, off = decode_ufix64(raw, off)
        stablecoin_fees, off = decode_ufix64(raw, off)
        stablecoin_nav, off = decode_ufix64(raw, off)
        levercoin_minted, off = decode_ufix64(raw, off)
        levercoin_nav, off = decode_ufix64(raw, off)
        out.append(
            {
                "event": "SwapStableToLeverEventV1",
                "stablecoin_burned": stablecoin_burned,
                "stablecoin_fees": stablecoin_fees,
                "stablecoin_nav": stablecoin_nav,
                "levercoin_minted": levercoin_minted,
                "levercoin_nav": levercoin_nav,
                "source": "inner_instruction_cpi",
            }
        )
    elif len(raw) >= 16 and raw[8:16] == REBALANCE_STABLE_TO_LEVER_EVENT:
        value, _ = decode_ufix64(raw, 16)
        out.append(
            {
                "event": "RebalanceStableToLeverEvent",
                "stablecoin_swapped": value,
                "source": "inner_instruction_cpi",
            }
        )
    return out


def decode_events(tx):
    out = []
    meta = tx.get("meta") or {}
    for line in meta.get("logMessages", []):
        prefix = "Program data: "
        if not line.startswith(prefix):
            continue
        raw = base64.b64decode(line[len(prefix) :])
        out.extend(decode_event_payload(raw))
    for group in meta.get("innerInstructions", []):
        for ins in group.get("instructions", []):
            data = ins.get("data")
            if not data:
                continue
            try:
                raw = b58decode(data)
            except Exception:
                continue
            out.extend(decode_event_payload(raw))
    return out


def maybe_match(tx, sig, account):
    transfers = extract_transfers(tx)
    diffs = token_diffs(tx)
    events = decode_events(tx)
    hyusd_amounts = [t["amount"] for t in transfers if t["mint"] == HYUSD and t["amount"] > 1000]
    xsol_amounts = [t["amount"] for t in transfers if t["mint"] == XSOL and t["amount"] > 10000]
    hyusd_amounts += [abs(d["diff"]) for d in diffs if d["mint"] == HYUSD and abs(d["diff"]) > 1000]
    xsol_amounts += [abs(d["diff"]) for d in diffs if d["mint"] == XSOL and abs(d["diff"]) > 10000]
    for e in events:
        if e["event"] == "SwapStableToLeverEventV1":
            hyusd_amounts.append(e["stablecoin_burned"])
            xsol_amounts.append(e["levercoin_minted"])
    matches = []
    for hy in hyusd_amounts:
        for xs in xsol_amounts:
            for target_hy, target_xs in TARGETS:
                if abs(hy - target_hy) < 0.001 and abs(xs - target_xs) < 0.001:
                    matches.append((hy, xs, target_hy, target_xs))
    if not matches:
        return None
    bt = tx.get("blockTime")
    return {
        "signature": sig,
        "account": account,
        "block_time": bt,
        "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
        "matches": matches,
        "transfers": transfers,
        "token_diffs": diffs,
        "events": events,
    }


def maybe_match_xsol_only(tx, sig, account):
    transfers = extract_transfers(tx)
    diffs = token_diffs(tx)
    events = decode_events(tx)
    xsol_amounts = [t["amount"] for t in transfers if t["mint"] == XSOL and t["amount"] > 10000]
    xsol_amounts += [abs(d["diff"]) for d in diffs if d["mint"] == XSOL and abs(d["diff"]) > 10000]
    xsol_amounts += [e["levercoin_minted"] for e in events if e["event"] == "SwapStableToLeverEventV1"]
    matched_targets = []
    for xs in xsol_amounts:
        for _, target_xs in TARGETS:
            if abs(xs - target_xs) < 0.001:
                matched_targets.append((xs, target_xs))
    if not matched_targets:
        return None
    bt = tx.get("blockTime")
    return {
        "signature": sig,
        "account": account,
        "block_time": bt,
        "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
        "xsol_matches": matched_targets,
        "transfers": transfers,
        "token_diffs": diffs,
        "events": events,
    }


def maybe_large(tx, sig, account):
    transfers = extract_transfers(tx)
    diffs = token_diffs(tx)
    events = decode_events(tx)
    hyusd_amounts = [t["amount"] for t in transfers if t["mint"] == HYUSD and t["amount"] > 10000]
    xsol_amounts = [t["amount"] for t in transfers if t["mint"] == XSOL and t["amount"] > 100000]
    hyusd_amounts += [abs(d["diff"]) for d in diffs if d["mint"] == HYUSD and abs(d["diff"]) > 10000]
    xsol_amounts += [abs(d["diff"]) for d in diffs if d["mint"] == XSOL and abs(d["diff"]) > 100000]
    for e in events:
        if e["event"] == "SwapStableToLeverEventV1":
            hyusd_amounts.append(e["stablecoin_burned"])
            xsol_amounts.append(e["levercoin_minted"])
        elif e["event"] == "RebalanceStableToLeverEvent":
            hyusd_amounts.append(e["stablecoin_swapped"])
    if not hyusd_amounts and not xsol_amounts:
        return None
    bt = tx.get("blockTime")
    return {
        "signature": sig,
        "account": account,
        "block_time": bt,
        "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
        "hyusd_amounts": hyusd_amounts,
        "xsol_amounts": xsol_amounts,
        "transfers": transfers,
        "token_diffs": diffs,
        "events": events,
    }


def maybe_any_stable_to_lever_event(tx, sig, account):
    events = [
        e
        for e in decode_events(tx)
        if e["event"] in ("SwapStableToLeverEventV1", "RebalanceStableToLeverEvent")
    ]
    if not events:
        return None
    bt = tx.get("blockTime")
    return {
        "signature": sig,
        "account": account,
        "block_time": bt,
        "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
        "events": events,
    }


def maybe_log_match(tx, sig, account, patterns):
    logs = tx.get("meta", {}).get("logMessages", [])
    hits = [line for line in logs if any(pattern in line for pattern in patterns)]
    if not hits:
        return None
    bt = tx.get("blockTime")
    return {
        "signature": sig,
        "account": account,
        "block_time": bt,
        "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
        "log_hits": hits,
        "transfers": [t for t in extract_transfers(tx) if t["mint"] in (HYUSD, XSOL)],
        "token_diffs": [d for d in token_diffs(tx) if d["mint"] in (HYUSD, XSOL)],
        "events": decode_events(tx),
    }


def scan(address, max_pages=25, page_size=100, sleep_s=0.7):
    before = None
    seen = 0
    for _ in range(max_pages):
        batch = get_sigs(address, limit=page_size, before=before)
        if not batch:
            break
        for row in batch:
            sig = row["signature"]
            seen += 1
            tx = get_tx(sig)
            hit = maybe_match(tx, sig, address)
            if hit:
                print(json.dumps(hit, indent=2))
            time.sleep(sleep_s)
        before = batch[-1]["signature"]
        sys.stderr.write(f"scanned {seen} signatures for {address}\n")
        sys.stderr.flush()
        time.sleep(sleep_s)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--scan-tsv-batch":
        path = sys.argv[2]
        account = sys.argv[3]
        with open(path, "r", encoding="utf-8") as f:
            sigs = [line.strip().split("\t")[-1] for line in f if line.strip()]
        batch_size = 20
        for start in range(0, len(sigs), batch_size):
            chunk = sigs[start : start + batch_size]
            txs = get_txs_batch(chunk)
            for sig, tx in zip(chunk, txs):
                if not tx:
                    continue
                hit = maybe_match(tx, sig, account)
                if hit:
                    print(json.dumps(hit, indent=2))
            time.sleep(0.9)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--scan-tsv-batch-xsol":
        path = sys.argv[2]
        account = sys.argv[3]
        with open(path, "r", encoding="utf-8") as f:
            sigs = [line.strip().split("\t")[-1] for line in f if line.strip()]
        batch_size = 20
        for start in range(0, len(sigs), batch_size):
            chunk = sigs[start : start + batch_size]
            txs = get_txs_batch(chunk)
            for sig, tx in zip(chunk, txs):
                if not tx:
                    continue
                hit = maybe_match_xsol_only(tx, sig, account)
                if hit:
                    print(json.dumps(hit, indent=2))
            time.sleep(0.9)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--scan-tsv-batch-large":
        path = sys.argv[2]
        account = sys.argv[3]
        with open(path, "r", encoding="utf-8") as f:
            sigs = [line.strip().split("\t")[-1] for line in f if line.strip()]
        batch_size = 20
        for start in range(0, len(sigs), batch_size):
            chunk = sigs[start : start + batch_size]
            txs = get_txs_batch(chunk)
            for sig, tx in zip(chunk, txs):
                if not tx:
                    continue
                hit = maybe_large(tx, sig, account)
                if hit:
                    print(json.dumps(hit, indent=2))
            time.sleep(0.9)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--scan-tsv-batch-events":
        path = sys.argv[2]
        account = sys.argv[3]
        with open(path, "r", encoding="utf-8") as f:
            sigs = [line.strip().split("\t")[-1] for line in f if line.strip()]
        batch_size = 20
        for start in range(0, len(sigs), batch_size):
            chunk = sigs[start : start + batch_size]
            txs = get_txs_batch(chunk)
            for sig, tx in zip(chunk, txs):
                if not tx:
                    continue
                hit = maybe_any_stable_to_lever_event(tx, sig, account)
                if hit:
                    print(json.dumps(hit, indent=2))
            time.sleep(0.9)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--scan-tsv-batch-logmatch":
        path = sys.argv[2]
        account = sys.argv[3]
        patterns = sys.argv[4:]
        with open(path, "r", encoding="utf-8") as f:
            sigs = [line.strip().split("\t")[-1] for line in f if line.strip()]
        batch_size = 20
        for start in range(0, len(sigs), batch_size):
            chunk = sigs[start : start + batch_size]
            txs = get_txs_batch(chunk)
            for sig, tx in zip(chunk, txs):
                if not tx:
                    continue
                hit = maybe_log_match(tx, sig, account, patterns)
                if hit:
                    print(json.dumps(hit, indent=2))
            time.sleep(0.9)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--analyze-tsv":
        path = sys.argv[2]
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                sig = parts[-1]
                tx = get_tx(sig)
                out = {
                    "signature": sig,
                    "block_time": tx.get("blockTime"),
                    "iso_utc": datetime.fromtimestamp(tx["blockTime"], timezone.utc).isoformat(),
                    "transfers": [
                        t for t in extract_transfers(tx) if t["mint"] in (HYUSD, XSOL)
                    ],
                    "token_diffs": [
                        d for d in token_diffs(tx) if d["mint"] in (HYUSD, XSOL)
                    ],
                }
                print(json.dumps(out, indent=2))
                time.sleep(0.7)
        return

    scan(EXCHANGE)
    scan(STABILITY_POOL)


if __name__ == "__main__":
    main()
