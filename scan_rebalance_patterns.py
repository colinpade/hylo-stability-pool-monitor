#!/usr/bin/env python3
import argparse
import json
import sys
import time
from datetime import datetime

import hylo_tx_scan as h


def load_signatures(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("signatures", [])


def in_range(row, start, end):
    utc = row.get("utc")
    if not utc:
        return False
    ts = datetime.fromisoformat(utc)
    if start and ts < start:
        return False
    if end and ts >= end:
        return False
    return True


def normalize_logs(logs):
    return logs or []


def find_hits(logs, patterns):
    hits = []
    lowered = [line.lower() for line in logs]
    for pattern in patterns:
        p = pattern.lower()
        for original, lower in zip(logs, lowered):
            if p in lower:
                hits.append(original)
    # stable unique order
    seen = set()
    unique = []
    for line in hits:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def main():
    parser = argparse.ArgumentParser(
        description="Batch scan Solana tx logs for rebalance patterns."
    )
    parser.add_argument("--signatures", required=True, help="JSON file from backfill_program_signatures.py")
    parser.add_argument("--out", required=True)
    parser.add_argument("--start-utc", help="Inclusive ISO datetime, e.g. 2026-01-01T00:00:00+00:00")
    parser.add_argument("--end-utc", help="Exclusive ISO datetime, e.g. 2026-03-01T00:00:00+00:00")
    parser.add_argument("--pattern", action="append", default=[], help="Case-insensitive log substring to match")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--max-txs", type=int, default=0)
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start_utc) if args.start_utc else None
    end = datetime.fromisoformat(args.end_utc) if args.end_utc else None
    patterns = args.pattern or ["rebalancestabletolever", "swapstabletolever"]

    rows = [row for row in load_signatures(args.signatures) if in_range(row, start, end)]
    if args.max_txs > 0:
        rows = rows[: args.max_txs]

    matches = []
    inspected = 0

    for idx in range(0, len(rows), args.batch_size):
        batch_rows = rows[idx : idx + args.batch_size]
        responses = h.get_txs_batch([row["signature"] for row in batch_rows])
        for row, result in zip(batch_rows, responses):
            inspected += 1
            if not result:
                continue
            meta = result.get("meta") or {}
            logs = normalize_logs(meta.get("logMessages"))
            log_hits = find_hits(logs, patterns)
            if log_hits:
                matches.append(
                    {
                        "signature": row["signature"],
                        "utc": row["utc"],
                        "slot": row["slot"],
                        "err": row.get("err"),
                        "log_hits": log_hits,
                        "logs": logs,
                    }
                )
        if inspected == len(batch_rows) or inspected % 200 == 0:
            print(
                json.dumps(
                    {
                        "inspected": inspected,
                        "total": len(rows),
                        "matches": len(matches),
                        "last_utc": batch_rows[-1]["utc"],
                    }
                ),
                flush=True,
            )
        if args.delay:
            time.sleep(args.delay)

    out = {
        "source": args.signatures,
        "start_utc": args.start_utc,
        "end_utc": args.end_utc,
        "patterns": patterns,
        "inspected": len(rows),
        "matches": matches,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
    print(json.dumps({"inspected": len(rows), "matches": len(matches), "out": args.out}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
