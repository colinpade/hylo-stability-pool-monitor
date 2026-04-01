#!/bin/zsh
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: $0 <tsv_path> <account> <output_jsonl> <pattern> [pattern...]" >&2
  exit 1
fi

tsv_path=$1
account=$2
output_path=$3
shift 3
patterns=("$@")
rpc_url="${RPC_URL:-https://solana-rpc.publicnode.com}"

tmp_req=$(mktemp)
tmp_resp=$(mktemp)
trap 'rm -f "$tmp_req" "$tmp_resp"' EXIT

: > "$output_path"

while IFS=$'\t' read -r block_time sig; do
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
    if ! curl --http1.1 -s "$rpc_url" \
      -H 'Content-Type: application/json' \
      --data @"$tmp_req" > "$tmp_resp"; then
      sleep "$delay"
      delay=$(python3 - <<'PY' "$delay"
import sys
print(min(float(sys.argv[1]) * 1.7, 8.0))
PY
)
      continue
    fi

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

  python3 - "$tmp_resp" "$account" "${patterns[@]}" >> "$output_path" <<'PY'
import json
import sys

import hylo_tx_scan as h

resp_path = sys.argv[1]
account = sys.argv[2]
patterns = sys.argv[3:]

with open(resp_path, "r", encoding="utf-8") as f:
    data = json.load(f)

if data.get("error"):
    raise SystemExit(json.dumps(data["error"]))

tx = data.get("result")
if tx:
    sig = tx.get("transaction", {}).get("signatures", [None])[0]
    hit = h.maybe_log_match(tx, sig, account, patterns)
    if hit:
        print(json.dumps(hit, separators=(",", ":")))
PY

  sleep 0.25
done < "$tsv_path"
