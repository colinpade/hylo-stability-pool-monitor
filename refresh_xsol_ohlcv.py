#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_POOL = "6t5fJwGxmTy2gWiq6CiLw2roZc93UanvANypMYQYHKGh"
DEFAULT_URL = (
    "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
    f"{DEFAULT_POOL}/ohlcv/minute?aggregate=5&limit=1000&currency=usd&token=base"
)


def fetch_json(url, timeout=30):
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "user-agent": "hylo-stability-pool-monitor/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def validate(payload):
    rows = payload["data"]["attributes"]["ohlcv_list"]
    if not rows:
        raise ValueError("empty ohlcv_list")
    first = rows[0]
    if len(first) < 6:
        raise ValueError("ohlcv rows are malformed")
    return len(rows)


def merged_payload(existing_payload, fetched_payload):
    existing_rows = (
        ((existing_payload or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    )
    fetched_rows = (
        ((fetched_payload or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    )
    merged_by_ts = {}
    for row in existing_rows:
        if row:
            merged_by_ts[int(row[0])] = row
    for row in fetched_rows:
        if row:
            merged_by_ts[int(row[0])] = row
    merged_rows = sorted(merged_by_ts.values(), key=lambda row: int(row[0]), reverse=True)
    payload = json.loads(json.dumps(fetched_payload))
    payload["data"]["attributes"]["ohlcv_list"] = merged_rows
    return payload


def load_existing_payload(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def time_span(payload):
    rows = payload["data"]["attributes"]["ohlcv_list"]
    newest = int(rows[0][0])
    oldest = int(rows[-1][0])
    return oldest, newest


def main():
    parser = argparse.ArgumentParser(description="Refresh cached xSOL/USDC 5-minute OHLCV from GeckoTerminal.")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Explicit GeckoTerminal OHLC endpoint.",
    )
    parser.add_argument(
        "--out",
        default="data/xsol_usdc_ohlcv_5m.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    existing_payload = load_existing_payload(out_path) if out_path.exists() else None
    try:
        fetched_payload = fetch_json(args.url)
        validate(fetched_payload)
        payload = merged_payload(existing_payload, fetched_payload)
        row_count = validate(payload)
        oldest_ts, newest_ts = time_span(payload)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "out": args.out,
                    "source": args.url,
                    "fetched_ohlcv_rows": len(
                        fetched_payload["data"]["attributes"]["ohlcv_list"]
                    ),
                    "ohlcv_rows": row_count,
                    "oldest_ts": oldest_ts,
                    "newest_ts": newest_ts,
                    "status": "refreshed",
                },
                indent=2,
            )
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError) as exc:
        if out_path.exists():
            print(
                json.dumps(
                    {
                        "out": args.out,
                        "source": args.url,
                        "status": "kept_cached_copy",
                        "warning": str(exc),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return
        raise SystemExit(f"unable to refresh OHLCV and no cached copy exists: {exc}")


if __name__ == "__main__":
    main()
