#!/bin/zsh
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: $0 <tsv_path> <output_jsonl> <keeper_pubkey> <vault_owner_pubkey> [min_hyusd_spent]" >&2
  exit 1
fi

tsv_path=$1
output_path=$2
keeper=$3
vault_owner=$4
min_hyusd_spent=${5:-0}
rpc_url="${RPC_URL:-https://solana-rpc.publicnode.com}"

tmp_req=$(mktemp)
tmp_resp=$(mktemp)
trap 'rm -f "$tmp_req" "$tmp_resp"' EXIT

: > "$output_path"

while IFS=$'\t' read -r _ sig; do
  [[ -n "${sig:-}" ]] || continue

  python3 - "$tmp_req" "$sig" <<'PY'
import json
import sys

out_path = sys.argv[1]
sig = sys.argv[2]
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "getTransaction",
    "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, separators=(",", ":"))
PY

  delay=0.6
  while true; do
    curl --http1.1 -s "$rpc_url" \
      -H 'Content-Type: application/json' \
      --data @"$tmp_req" > "$tmp_resp"

    if python3 - "$tmp_resp" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

error = data.get("error")
if error and error.get("code") == 429:
    raise SystemExit(1)
PY
    then
      break
    fi

    sleep "$delay"
    delay=$(python3 - <<'PY' "$delay"
import sys
print(min(float(sys.argv[1]) * 1.7, 8.0))
PY
)
  done

  python3 - "$tmp_resp" "$keeper" "$vault_owner" "$min_hyusd_spent" >> "$output_path" <<'PY'
import json
import sys
from datetime import datetime, timezone

import hylo_tx_scan as h

resp_path = sys.argv[1]
keeper = sys.argv[2]
vault_owner = sys.argv[3]
min_hyusd_spent = float(sys.argv[4])

with open(resp_path, "r", encoding="utf-8") as f:
    data = json.load(f)

if data.get("error"):
    raise SystemExit(json.dumps(data["error"]))

tx = data.get("result")
if not tx:
    raise SystemExit(0)

diffs = h.token_diffs(tx)
keeper_hyusd = sum(
    d["diff"] for d in diffs if d["mint"] == h.HYUSD and d.get("owner") == keeper
)
keeper_xsol = sum(
    d["diff"] for d in diffs if d["mint"] == h.XSOL and d.get("owner") == keeper
)
vault_hyusd = sum(
    d["diff"] for d in diffs if d["mint"] == h.HYUSD and d.get("owner") == vault_owner
)
vault_xsol = sum(
    d["diff"] for d in diffs if d["mint"] == h.XSOL and d.get("owner") == vault_owner
)

if keeper_hyusd >= -min_hyusd_spent or keeper_xsol <= 0:
    raise SystemExit(0)

logs = tx.get("meta", {}).get("logMessages", [])
instruction_logs = [line for line in logs if "Instruction:" in line]
sig = tx.get("transaction", {}).get("signatures", [None])[0]
bt = tx.get("blockTime")

print(
    json.dumps(
        {
            "signature": sig,
            "block_time": bt,
            "iso_utc": datetime.fromtimestamp(bt, timezone.utc).isoformat() if bt else None,
            "keeper_hyusd_diff": keeper_hyusd,
            "keeper_xsol_diff": keeper_xsol,
            "vault_hyusd_diff": vault_hyusd,
            "vault_xsol_diff": vault_xsol,
            "instruction_logs": instruction_logs,
            "token_diffs": [
                d
                for d in diffs
                if d["mint"] in (h.HYUSD, h.XSOL)
                and d.get("owner") in (keeper, vault_owner)
            ],
        },
        separators=(",", ":"),
    )
)
PY

  sleep 0.25
done < "$tsv_path"
