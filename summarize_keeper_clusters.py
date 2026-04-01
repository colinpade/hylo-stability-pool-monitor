#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def load_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda row: row["block_time"])
    return rows


def cluster_rows(rows, max_gap_seconds):
    clusters = []
    current = []
    for row in rows:
        if not current or row["block_time"] - current[-1]["block_time"] <= max_gap_seconds:
            current.append(row)
            continue
        clusters.append(current)
        current = [row]
    if current:
        clusters.append(current)
    return clusters


def summarize_cluster(rows, base_price, tz_name):
    tz = ZoneInfo(tz_name)
    hyusd_spent = sum(-row["keeper_hyusd_diff"] for row in rows)
    xsol_bought = sum(row["keeper_xsol_diff"] for row in rows)
    implied_price = hyusd_spent / xsol_bought
    start_bt = min(row["block_time"] for row in rows)
    end_bt = max(row["block_time"] for row in rows)
    start_dt = datetime.fromtimestamp(start_bt, timezone.utc)
    end_dt = datetime.fromtimestamp(end_bt, timezone.utc)
    return {
        "start_block_time": start_bt,
        "end_block_time": end_bt,
        "start_utc": start_dt.isoformat(),
        "end_utc": end_dt.isoformat(),
        "start_local": start_dt.astimezone(tz).isoformat(),
        "end_local": end_dt.astimezone(tz).isoformat(),
        "tx_count": len(rows),
        "hyusd_spent": hyusd_spent,
        "xsol_bought": xsol_bought,
        "implied_hyusd_per_xsol": implied_price,
        "vs_first_cluster_pct": ((implied_price / base_price) - 1.0) * 100.0,
        "first_signature": rows[0]["signature"],
        "last_signature": rows[-1]["signature"],
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: summarize_keeper_clusters.py <input_jsonl> [max_gap_seconds] [local_tz]"
        )

    input_path = sys.argv[1]
    max_gap_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    local_tz = sys.argv[3] if len(sys.argv) > 3 else "America/Los_Angeles"

    rows = load_rows(input_path)
    if not rows:
        print("[]")
        return

    grouped = cluster_rows(rows, max_gap_seconds)
    base_rows = grouped[0]
    base_price = sum(-row["keeper_hyusd_diff"] for row in base_rows) / sum(
        row["keeper_xsol_diff"] for row in base_rows
    )

    summary = [
        summarize_cluster(cluster, base_price=base_price, tz_name=local_tz)
        for cluster in grouped
    ]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
