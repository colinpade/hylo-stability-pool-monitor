#!/bin/zsh
set -euo pipefail

addr="${3:-HysTabVUfmQBFcmzu1ctRd1Y1fxd66RBpboy1bmtDSQQ}"
before="${4:-}"
pages="${1:-5}"
sleep_s="${2:-2.5}"

for ((i=1; i<=pages; i++)); do
  while true; do
    if [[ -n "$before" ]]; then
      payload=$(jq -nc --arg addr "$addr" --arg before "$before" '{
        jsonrpc:"2.0",
        id:1,
        method:"getSignaturesForAddress",
        params:[$addr,{limit:100,before:$before}]
      }')
    else
      payload=$(jq -nc --arg addr "$addr" '{
        jsonrpc:"2.0",
        id:1,
        method:"getSignaturesForAddress",
        params:[$addr,{limit:100}]
      }')
    fi

    out=$(curl -s https://api.mainnet-beta.solana.com -H 'Content-Type: application/json' --data "$payload")
    err_code=$(echo "$out" | jq -r '.error.code // empty')
    if [[ "$err_code" == "429" ]]; then
      sleep 8
      continue
    fi
    break
  done

  echo "$out" | jq --argjson page "$i" '{
    page:$page,
    count:(.result|length),
    newest:.result[0].blockTime,
    oldest:.result[-1].blockTime,
    oldest_sig:.result[-1].signature,
    error:(.error // null)
  }'
  before=$(echo "$out" | jq -r '.result[-1].signature // empty')
  [[ -z "$before" ]] && break
  sleep "$sleep_s"
done
