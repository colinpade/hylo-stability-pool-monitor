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
    try:
        payload = fetch_json(args.url)
        row_count = validate(payload)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "out": args.out,
                    "source": args.url,
                    "ohlcv_rows": row_count,
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
