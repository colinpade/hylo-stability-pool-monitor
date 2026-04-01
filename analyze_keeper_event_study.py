#!/usr/bin/env python3
import json
import sys
from bisect import bisect_right


HORIZONS = [
    ("1h", 3600),
    ("6h", 21600),
    ("24h", 86400),
]


def load_clusters(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ohlcv(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw["data"]["attributes"]["ohlcv_list"]
    bars = [
        {
            "ts": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]
    bars.sort(key=lambda row: row["ts"])
    return bars


def last_bar_at_or_before(timestamps, bars, ts):
    idx = bisect_right(timestamps, ts) - 1
    if idx < 0:
        return None
    return bars[idx]


def pct_change(a, b):
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: analyze_keeper_event_study.py <clusters_json> <ohlcv_json>"
        )

    clusters = load_clusters(sys.argv[1])
    bars = load_ohlcv(sys.argv[2])
    timestamps = [bar["ts"] for bar in bars]
    first_bar_ts = timestamps[0]
    last_bar_ts = timestamps[-1]

    out = []
    for cluster in clusters:
        event_ts = int(cluster["start_block_time"])
        entry_bar = (
            last_bar_at_or_before(timestamps, bars, event_ts)
            if event_ts >= first_bar_ts
            else None
        )
        row = dict(cluster)
        row["market_entry_bar_ts"] = entry_bar["ts"] if entry_bar else None
        row["market_entry_close"] = entry_bar["close"] if entry_bar else None
        row["market_entry_gap_seconds"] = (
            event_ts - entry_bar["ts"] if entry_bar else None
        )
        for label, seconds in HORIZONS:
            target_ts = event_ts + seconds
            future_bar = (
                last_bar_at_or_before(timestamps, bars, target_ts)
                if target_ts <= last_bar_ts
                else None
            )
            row[f"{label}_bar_ts"] = future_bar["ts"] if future_bar else None
            row[f"{label}_close"] = future_bar["close"] if future_bar else None
            row[f"{label}_return_pct"] = pct_change(
                row["market_entry_close"],
                future_bar["close"] if future_bar else None,
            )
        out.append(row)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
