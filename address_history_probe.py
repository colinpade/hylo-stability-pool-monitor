#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone

import hylo_tx_scan as h


KEEPER = "CcUrRBMqrCuMPVfd6sVTBJhyhBA1dE7qDoJkSy95bbcw"
VAULT_OWNER = "5YrRAQag9BbJkauDtJkd1vsTquXT6N46oU8rJ66GDxHd"

KNOWN_ADDRESSES = {
    "exchange": h.EXCHANGE,
    "stability_pool": h.STABILITY_POOL,
    "hyUSD": h.HYUSD,
    "xSOL": h.XSOL,
    "keeper": KEEPER,
    "vault_owner": VAULT_OWNER,
}


def iso_utc(block_time):
    if not block_time:
        return None
    return datetime.fromtimestamp(block_time, timezone.utc).isoformat()


def probe_address(address, page_size=1000, max_pages=50):
    before = None
    total = 0
    pages = 0
    newest = None
    oldest = None
    while pages < max_pages:
        batch = h.get_sigs(address, limit=page_size, before=before)
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
        "reached_end": bool(oldest and total > 0 and pages < max_pages),
    }


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/address_history_probe.json"
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    page_size = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    results = {}
    for label, address in KNOWN_ADDRESSES.items():
        results[label] = probe_address(address, page_size=page_size, max_pages=max_pages)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
