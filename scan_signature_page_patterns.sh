#!/bin/zsh
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: $0 <address> <before_signature_or_dash> <out_json> <pattern1> [pattern2 ...]" >&2
  exit 1
fi

addr="$1"
before="$2"
out="$3"
shift 3
patterns=("$@")

build_payload() {
  if [[ "$before" != "-" ]]; then
    jq -nc --arg addr "$addr" --arg before "$before" '{
      jsonrpc:"2.0",
      id:1,
      method:"getSignaturesForAddress",
      params:[$addr,{limit:100,before:$before}]
    }'
  else
    jq -nc --arg addr "$addr" '{
      jsonrpc:"2.0",
      id:1,
      method:"getSignaturesForAddress",
      params:[$addr,{limit:100}]
    }'
  fi
}

rpc_post() {
  local payload="$1"
  while true; do
    local out
    out=$(curl -s https://api.mainnet-beta.solana.com -H 'Content-Type: application/json' --data "$payload")
    local err_code
    err_code=$(echo "$out" | jq -r '.error.code // empty')
    if [[ "$err_code" == "429" ]]; then
      sleep 6
      continue
    fi
    echo "$out"
    return 0
  done
}

sig_payload=$(build_payload)
sig_out=$(rpc_post "$sig_payload")
sig_file=$(mktemp)
echo "$sig_out" > "$sig_file"

count=$(jq '.result | length' "$sig_file")
echo "scanning $count signatures" >&2

echo "[" > "$out"
first=1
for sig in $(jq -r '.result[].signature' "$sig_file"); do
  tx_payload=$(jq -nc --arg sig "$sig" '{
    jsonrpc:"2.0",
    id:1,
    method:"getTransaction",
    params:[$sig,{encoding:"jsonParsed",maxSupportedTransactionVersion:0}]
  }')
  tx_out=$(rpc_post "$tx_payload")
  tx_file=$(mktemp)
  echo "$tx_out" > "$tx_file"
  block_time=$(jq '.result.blockTime // null' "$tx_file")
  log_blob=$(jq -r '.result.meta.logMessages // [] | join("\n")' "$tx_file" | tr '[:upper:]' '[:lower:]')
  matched=()
  for pat in "${patterns[@]}"; do
    pat_lc=$(echo "$pat" | tr '[:upper:]' '[:lower:]')
    if [[ "$log_blob" == *"$pat_lc"* ]]; then
      matched+=("$pat")
    fi
  done
  if [[ ${#matched[@]} -gt 0 ]]; then
    obj=$(jq -nc \
      --arg sig "$sig" \
      --argjson block_time "$block_time" \
      --argjson matched "$(printf '%s\n' "${matched[@]}" | jq -R . | jq -s .)" \
      --argjson logs "$(jq '.result.meta.logMessages // []' "$tx_file")" \
      '{signature:$sig, block_time:$block_time, matched:$matched, logs:$logs}')
    if [[ $first -eq 0 ]]; then
      echo "," >> "$out"
    fi
    echo "$obj" >> "$out"
    first=0
  fi
  rm -f "$tx_file"
  sleep 0.35
done
echo "]" >> "$out"
rm -f "$sig_file"
