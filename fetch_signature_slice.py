#!/usr/bin/env python3
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import hylo_tx_scan as h


def iso_utc(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a historical signature slice using the existing curl/PublicNode RPC helper."
    )
    parser.add_argument("--address", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-date", required=True, help="UTC date, e.g. 2026-01-01")
    parser.add_argument("--before", help="Optional before cursor")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    min_ts = int(datetime.fromisoformat(args.min_date).replace(tzinfo=timezone.utc).timestamp())
    before = args.before
    all_rows = []
    pages = []

    for page in range(1, args.max_pages + 1):
        rows = h.get_sigs(args.address, limit=args.limit, before=before)
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
        if args.delay:
            time.sleep(args.delay)

    kept = [row for row in all_rows if row.get("blockTime") is not None and row["blockTime"] >= min_ts]
    day_counts = Counter(iso_utc(row["blockTime"])[:10] for row in kept)
    out = {
        "address": args.address,
        "min_date_utc": args.min_date,
        "pages_fetched": len(pages),
        "rows_fetched": len(all_rows),
        "rows_kept": len(kept),
        "newest_utc": iso_utc(kept[0]["blockTime"]) if kept else None,
        "oldest_utc": iso_utc(kept[-1]["blockTime"]) if kept else None,
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
            for row in kept
        ],
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
    print(json.dumps({k: out[k] for k in ("pages_fetched", "rows_fetched", "rows_kept", "newest_utc", "oldest_utc")}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
