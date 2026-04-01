#!/usr/bin/env python3
import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

RPC_URL = "https://api.mainnet-beta.solana.com"


def rpc_call(method, params, retries=8, base_sleep=1.5):
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries - 1:
                raise
            time.sleep(base_sleep * (attempt + 1))
        except urllib.error.URLError as exc:
            if attempt == retries - 1:
                raise
            time.sleep(base_sleep * (attempt + 1))
        except TimeoutError:
            if attempt == retries - 1:
                raise
            time.sleep(base_sleep * (attempt + 1))
        except socket.timeout:
            if attempt == retries - 1:
                raise
            time.sleep(base_sleep * (attempt + 1))
    raise RuntimeError("unreachable")


def iso_utc(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def backfill(args):
    min_ts = int(datetime.fromisoformat(args.min_date).replace(tzinfo=timezone.utc).timestamp())
    before = args.before
    all_rows = []
    pages = []

    for page in range(1, args.max_pages + 1):
        params = [args.address, {"limit": args.limit}]
        if before:
            params[1]["before"] = before

        data = rpc_call("getSignaturesForAddress", params)
        if "error" in data:
            raise RuntimeError(f"RPC error on page {page}: {data['error']}")
        rows = data.get("result", [])
        if not rows:
            break

        all_rows.extend(rows)
        oldest = rows[-1]
        pages.append(
            {
                "page": page,
                "count": len(rows),
                "newest_block_time": rows[0].get("blockTime"),
                "newest_utc": iso_utc(rows[0].get("blockTime")),
                "oldest_block_time": oldest.get("blockTime"),
                "oldest_utc": iso_utc(oldest.get("blockTime")),
                "before_for_next_page": oldest.get("signature"),
            }
        )
        before = oldest.get("signature")

        if page == 1 or page % 10 == 0:
            print(
                json.dumps(
                    {
                        "page": page,
                        "count": len(rows),
                        "oldest_utc": iso_utc(oldest.get("blockTime")),
                        "oldest_signature": oldest.get("signature"),
                    }
                ),
                flush=True,
            )

        if oldest.get("blockTime") is not None and oldest["blockTime"] < min_ts:
            break

        time.sleep(args.delay)

    trimmed = [row for row in all_rows if row.get("blockTime") is not None and row["blockTime"] >= min_ts]
    day_counts = Counter(iso_utc(row["blockTime"])[:10] for row in trimmed)

    out = {
        "address": args.address,
        "min_date_utc": args.min_date,
        "pages_fetched": len(pages),
        "rows_fetched": len(all_rows),
        "rows_kept": len(trimmed),
        "newest_utc": iso_utc(trimmed[0]["blockTime"]) if trimmed else None,
        "oldest_utc": iso_utc(trimmed[-1]["blockTime"]) if trimmed else None,
        "pages": pages,
        "day_counts": dict(sorted(day_counts.items())),
        "signatures": [
            {
                "signature": row.get("signature"),
                "slot": row.get("slot"),
                "block_time": row.get("blockTime"),
                "utc": iso_utc(row.get("blockTime")),
                "err": row.get("err"),
                "confirmation_status": row.get("confirmationStatus"),
                "memo": row.get("memo"),
            }
            for row in trimmed
        ],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: out[k] for k in ("address", "pages_fetched", "rows_fetched", "rows_kept", "newest_utc", "oldest_utc")}, indent=2))


def inspect(args):
    with open(args.signatures, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data["signatures"]
    if args.date:
        rows = [row for row in rows if row["utc"] and row["utc"].startswith(args.date)]
    rows = rows[: args.max_txs]

    matches = []
    patterns = [p.lower() for p in args.pattern]
    for idx, row in enumerate(rows, start=1):
        if idx == 1 or idx % 10 == 0:
            print(json.dumps({"inspected": idx - 1, "total": len(rows), "matches": len(matches)}), flush=True)
        tx = rpc_call(
            "getTransaction",
            [row["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        result = tx.get("result")
        if not result:
            continue
        logs = result.get("meta", {}).get("logMessages", []) or []
        flat = "\n".join(logs).lower()
        if patterns and not any(p in flat for p in patterns):
            if args.delay:
                time.sleep(args.delay)
            continue
        matches.append(
            {
                "signature": row["signature"],
                "utc": row["utc"],
                "slot": row["slot"],
                "logs": logs,
            }
        )
        if args.delay:
            time.sleep(args.delay)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2)
    print(json.dumps({"matches": len(matches), "out": args.out}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Backfill Solana program/account signatures and inspect selected tx logs.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backfill = sub.add_parser("backfill")
    p_backfill.add_argument("--address", required=True)
    p_backfill.add_argument("--min-date", required=True, help="UTC date, e.g. 2026-01-01")
    p_backfill.add_argument("--out", required=True)
    p_backfill.add_argument("--limit", type=int, default=100)
    p_backfill.add_argument("--max-pages", type=int, default=400)
    p_backfill.add_argument("--delay", type=float, default=1.0)
    p_backfill.add_argument("--before", help="Optional signature cursor to start before.")
    p_backfill.set_defaults(func=backfill)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--signatures", required=True)
    p_inspect.add_argument("--out", required=True)
    p_inspect.add_argument("--date", help="Filter signature UTC prefix, e.g. 2026-02-24")
    p_inspect.add_argument("--max-txs", type=int, default=200)
    p_inspect.add_argument("--delay", type=float, default=0.25)
    p_inspect.add_argument("--pattern", action="append", default=[], help="Case-insensitive log substring to match")
    p_inspect.set_defaults(func=inspect)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
