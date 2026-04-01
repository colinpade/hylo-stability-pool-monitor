# Explore xSOL State

Saved: 2026-03-29

## Goal

Investigate Hylo's "Stability Pool bought xSOL" pattern:

- identify past `stable -> xSOL` / `rebalance_stable_to_lever` occurrences
- estimate when those occurrences happened on-chain
- compare xSOL performance after each occurrence over fixed forward windows
- keep the research in a human-readable HTML report

## Confirmed addresses

- Hylo Exchange: `HYEXCHtHkBagdStcJCp3xbbb9B7sdMdWXFNj6mdsG4hn`
- Hylo Stability Pool: `HysTabVUfmQBFcmzu1ctRd1Y1fxd66RBpboy1bmtDSQQ`
- hyUSD mint: `5YMkXAYccHSGnHn9nob9xEvv6Pvka9DZWH7nTbotTu9E`
- xSOL mint: `4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs`
- likely keeper signer seen in related txs: `CcUrRBMqrCuMPVfd6sVTBJhyhBA1dE7qDoJkSy95bbcw`
- labeled Stability Pool vault owner: `5YrRAQag9BbJkauDtJkd1vsTquXT6N46oU8rJ66GDxHd`

## Screenshot rows under investigation

- `30,131.233824 hyUSD -> 498,493.006733 xSOL`
- `11,552.792571 hyUSD -> 190,916.507256 xSOL`
- `23,479.769439 hyUSD -> 386,742.798409 xSOL`
- `21,061.983677 hyUSD -> 344,971.328588 xSOL`

## What was scanned

- 3,000 recent Hylo Exchange signatures
- 1,000 recent Stability Pool signatures
- 1,000 recent keeper-signer signatures
- 1,000 recent labeled vault-owner signatures
- extracted keeper-buy matches from the cached Stability Pool page
- xSOL public market feeds from DexScreener / GeckoTerminal
- GeckoTerminal `xSOL / USDC` 5-minute OHLC bars

## Main findings so far

- The screenshot is consistent with `hyUSD -> xSOL` buys and the implied xSOL price is plausible versus public market pricing.
- A direct public on-chain 1:1 match for the four screenshot rows was **not** recovered from the scanned Exchange / Stability Pool / keeper / vault-owner history.
- The strongest public mechanism recovered so far is **not** a clean decoded `RebalanceStableToLeverEvent` row.
- Instead, the repeatable public pattern is:
  - keeper wallet spends `hyUSD`
  - keeper wallet receives `xSOL`
  - labeled vault owner loses `xSOL`
  - logs usually include `Route` / `SharedAccountsRoute`, `SwapV2`, `Swap`, `UserWithdraw`, `Burn`
- From the cached `hystab_1000.tsv` page, that keeper-buy pattern produced:
  - `144` matching transactions
  - `34` time clusters
  - UTC span: `2026-03-26T22:32:15+00:00` to `2026-03-29T23:18:34+00:00`
- The largest public cluster before the tweet window was:
  - `2026-03-29T17:28:31+00:00` to `2026-03-29T17:29:36+00:00`
  - `18` txs
  - `133.500888 hyUSD` spent
  - `2363.183645 xSOL` bought
  - implied execution price: `0.05649197 hyUSD / xSOL`
- Joining those cluster times to GeckoTerminal `xSOL / USDC` 5-minute OHLC gives a preliminary event-study result:
  - all `34` clusters: average execution `-1.58%` vs public market at event time
  - all `34` clusters: average forward return `-0.45%` at `+1h`, `-1.76%` at `+6h`, `-5.59%` at `+24h`
  - March 29 only (`9` clusters): average execution `-1.51%` vs market, `+0.62%` at `+1h`, `-1.75%` at `+6h` on the `4` eligible clusters
- Working interpretation:
  - the tweet is probably referring to a real recurring Stability Pool xSOL-acquisition mechanism
  - the screenshot itself still looks like a Hylo-specific feed/indexer aggregation rather than a simple explorer row
- Newer and more screenshot-like finding:
  - explicit `SwapStableToLeverEventV1` rows on the public Hylo Exchange stream are closer to the screenshot pattern than the keeper-only trace
  - Exchange pages 4-7 currently yield `13` grouped clusters between `2026-03-27T08:35:55+00:00` and `2026-03-28T11:51:33+00:00`
  - largest grouped Exchange cluster found so far:
    - `2026-03-27T08:35:55+00:00` to `2026-03-27T08:36:15+00:00`
    - `25` txs
    - `17,968.306561 hyUSD` burned
    - `243,241.579563 xSOL` minted
    - implied execution price `0.07387 hyUSD / xSOL`
    - public market returns after cluster: `-0.43%` at `+1h`, `-10.32%` at `+6h`, `-7.13%` at `+24h`
  - other larger Exchange-side clusters found on `2026-03-27`:
    - `4,712.858749 hyUSD -> 67,972.153212 xSOL` at `2026-03-27T10:37:32+00:00`
    - `4,534.991158 hyUSD -> 69,827.652207 xSOL` at `2026-03-27T22:42:37+00:00`
    - `2,315.449938 hyUSD -> 34,684.884857 xSOL` at `2026-03-27T13:49:50+00:00`
  - these are still below the screenshot’s biggest row, but they are in the same order of magnitude and materially closer than the keeper-only pool trace
- Important scope correction:
  - the March 26-29 on-chain slice is **not** the full age of Hylo / xSOL / hyUSD
  - current direct RPC pagination only reaches back to:
    - Exchange: `2026-03-26T23:45:43+00:00`
    - Stability Pool: `2026-03-27T01:05:55+00:00`
    - keeper: `2026-03-27T00:03:42+00:00`
    - xSOL mint: `2026-03-26T23:45:43+00:00`
    - hyUSD mint: `2026-03-26T23:45:43+00:00`
  - but external/public evidence shows the protocol and tokens are much older:
    - official docs `Season 0` mention `4` private-beta snapshots
    - GeckoTerminal earliest xSOL pool creation in cached page 1: `2025-08-16T09:36:46Z`
    - GeckoTerminal earliest hyUSD pool creation in cached page 1: `2025-07-29T19:01:59Z`
    - GeckoTerminal earliest `xSOL / hyUSD` pool creation across cached token pages: `2025-11-03T16:55:20Z`
    - GitHub repo dates:
      - `hylo-so/sdk` created `2025-07-15T21:51:55Z`
      - `hylo-so/model` created `2024-02-26T13:25:19Z`
      - `hylo-so/WhitePaper-Gitbook` created `2024-04-22T19:00:16Z`
  - implication:
    - the current public scan is reliable for a recent recurring pattern study
    - it is **not** enough to claim a full January-to-date activation history
    - a real YTD activation study now needs an archival/indexed source or a Hylo-specific API/feed
  - official RPC cross-check:
    - querying `https://api.mainnet-beta.solana.com` for one page older than PublicNode's current oldest signatures returned:
      - `5` slightly older signatures for `xSOL`
      - `5` slightly older signatures for `hyUSD`
      - `0` older signatures for the current `Hylo Exchange`
      - `0` older signatures for the current `Stability Pool`
    - this makes the late-March boundary look especially real for the current Exchange / Stability Pool accounts, even though the broader token markets are older
- Public repo review was useful:
  - `hylo-so/sdk` exposes an explicit Stability Pool client method: `rebalance_stable_to_lever()`
  - `hylo-so/sdk` instruction builders confirm `HYUSD -> XSOL` is `swap_stable_to_lever`
  - `hylo-so/model` treats stability pool activations as a recurring measurable event
  - the model code suggests the xSOL-side pool action is the one triggered in lower-collateral states
- The most important repo insight:
  - Hylo's own SDK parses events from `innerInstructions[*].instructions[*].data`
  - those payloads are base58, not the earlier `Program data:` base64 path
  - the SDK checks the event discriminator at byte offset `8` and deserializes payload from byte `16`

## Code changes already made

`hylo_tx_scan.py` was updated to:

- add a local base58 decoder
- inspect inner CPI instruction `data`
- try event decoding from both:
  - `Program data:` logs
  - inner instruction payloads with discriminator at offset `8`

New helper scripts:

- `scan_logmatches.sh`
  - fetches transactions via shell `curl`
  - matches by instruction/log pattern against cached signature pages
- `scan_keeper_buys.sh`
  - extracts transactions where the keeper spends `hyUSD` and receives `xSOL`
  - emits raw JSONL rows with token diffs and instruction logs
- `summarize_keeper_clusters.py`
  - groups raw keeper-buy JSONL rows into time clusters
  - outputs cluster totals, timestamps, and implied execution prices
- `analyze_keeper_event_study.py`
  - joins cluster timestamps to GeckoTerminal OHLC bars
  - computes `+1h`, `+6h`, `+24h` forward returns
- `stability_pool_onchain_tracker.py`
  - derives the real Stability Pool pool-authority and token-account PDAs from on-chain seeds
  - captures direct RPC snapshots of `hyUSD` pool balance, `xSOL` pool balance, and `sHYUSD` supply
  - reconstructs recent balance-changing txs from the pool token-account history
  - probes the full public signature depth of the derived pool accounts
- `render_stability_pool_tracker_html.py`
  - renders the on-chain tracker JSONL files into a human-readable HTML report
- `analyze_viability.py`
  - summarizes whether the public sample supports a financially viable `hyUSD -> xSOL` buy-the-dip edge
  - emits both JSON summary stats and a readable HTML verdict
- `extract_current_buy_xsol.py`
  - extracts all clean `buy_xsol` rows from the full current-deployment pool-account history
  - joins those rows to cached market data where horizon coverage exists
  - emits JSON and HTML summaries

## Where the decode currently stands

- The patched scanner still did not surface recent `SwapStableToLeverEventV1` or `RebalanceStableToLeverEvent` objects from the cached pages.
- A known Exchange tx was inspected directly:
  - signature: `5EBQaxGGMf1Bj6z2UM9dRav1nU7mxG1pvAGEH2UtZPyQjMWghqbBHXEiaTFufdR5e3UcjXsiXoFG5iW6yTkettKY`
  - log shows: `Instruction: SwapLeverToStable`
  - inner HYEXCH CPI data exists
  - returnData exists for HYEXCH
- That HYEXCH inner CPI payload did **not** match the known event discriminators at offset `0` or `8`.
- This means one of these is still true:
  - the relevant event is emitted in a different transaction set than the recent cached pages
  - the screenshot rows are coming from an internal Hylo activity/indexer layer rather than a simple explorer-visible event stream
  - the useful decode target is the instruction/returnData format rather than the published event structs
- The investigation is now less dependent on event decoding because the keeper-buy balance-delta pattern is recoverable publicly.

## Best next steps

1. If the goal is truly January-to-date, switch from the current RPC-only route to an archival/indexed source or Hylo-specific API/feed.
2. If exact screenshot rows still matter, trace the Hylo frontend/API/indexer layer directly; public explorer history has not produced a 1:1 row match.
3. Add longer market-history windows where future data exists:
   - 72 hours
   - 7 days
4. Compare public market price with keeper implied execution price more systematically:
   - average discount by cluster size
   - discount persistence by day
5. Continue extending older Hylo Exchange pages and cluster the explicit `SwapStableToLeverEventV1` stream to see whether any public row or grouped cluster gets near the screenshot sizes inside the currently retrievable window.
6. If needed, continue decoding HYEXCH `returnData` / instruction args for the larger non-public screenshot-style amounts.
7. Track the direct Stability Pool token-account balances over time:
   - `hyUSD` pool ATA: `EqozKyMj7FVnLHc2cJj3VC25aBr4AhVh1cGM2WDajGe9`
   - `xSOL` pool ATA: `4GPXVXuzk8ABAUkoXeBJg8r9kccEXQjoi5vqSxE9rhk1`
   - pool auth / labeled vault owner: `5YrRAQag9BbJkauDtJkd1vsTquXT6N46oU8rJ66GDxHd`
   - these are derived from the Stability Pool `POOL_AUTH` seed and match the public labeled owner already found earlier
8. Scope correction from the direct pool-account probe:
   - stronger answer: **yes, a pre-`2026-03-27` mainnet deployment existed**
   - current program IDs were first deployed on mainnet on `2025-04-11`:
     - Exchange `HYEXCH...`: deploy tx `22Zs7waP...`, `2025-04-11T21:37:28+00:00`
     - Stability Pool `HysTab...`: deploy tx `5giigaQ6...`, `2025-04-11T21:55:04+00:00`
   - both current program-data accounts point to a latest deploy/upgrade on `2026-01-28`:
     - Exchange programData `BA5b6Fz...`: slot `396561417`, `2026-01-28T21:26:01+00:00`
     - Stability Pool programData `9Zzs2JU...`: slot `396559373`, `2026-01-28T21:12:15+00:00`
     - confirmed Stability Pool upgrade tx `3hoSNogB...` logs `Upgraded program HysTab...`
   - the earlier March-boundary interpretation was too aggressive:
     - direct pool-account history still bottoms out at `2026-03-27T16:43:41+00:00`
     - but the earliest visible current pool tx `4ccAo8Ac...` is a `UserDeposit`, not initialization
     - before that tx, the pool already held:
       - `9,420,245.035451 hyUSD`
       - `3,366,664.232443 xSOL`
     - so the March 27 boundary is a **history visibility cutoff**, not the real start of the current pool
   - saved summary:
     - `pre_march_deployment_report.html`
     - `data/pre_march_deployment_evidence.json`
   - continued program-history recovery:
     - direct pagination of the current `HysTab...` program invocation stream now reaches back well before March
     - saved checkpoints:
       - `data/hystab_pages_25.jsonl`: down to `2026-03-11T02:56:50-07:00`
       - `data/hystab_pages_25_70.jsonl`: down to `2026-02-18T08:05:55-08:00`
       - `data/hystab_pages_130_250.jsonl`: currently saved down to `2026-01-11T22:20:34-08:00`
       - `data/hystab_pages_330_370.jsonl`: currently saved down to `2025-12-27T15:37:45-08:00`
     - this proves the current Stability Pool program history is materially deeper than the current derived pool-account history
     - `2026-01-01` is now confirmed to be inside the currently visible public program-history window
     - but a clean pre-`2026-03-27` `buy_xsol` extraction is still pending
     - sampled older transactions so far:
       - `2026-02-27 10:18:23 PM`: external swap + `UserDeposit`, not `RebalanceStableToLever`
       - `2026-02-27 03:57:15 PM`: `UserWithdraw`
       - `2026-01-13 01:45:31 AM`: loan actions + external routing + `UserWithdraw`, not `RebalanceStableToLever`
       - `2026-01-11 10:20:34 PM`: external routing + `UserDeposit`, not `RebalanceStableToLever`
     - exact March 29 clean buy pattern for matching:
       - `HysTab...` logs `Instruction: RebalanceStableToLever`
       - nested `HYEXCH...` logs `Instruction: SwapStableToLever`
     - summary file: `data/hystab_program_history_depth.json`
9. Exhaustive current-deployment `buy_xsol` result:
   - scanning the full current pool-account history produced `326` balance-changing rows:
     - `207` `pool_shrank_both`
     - `113` `hyusd_only`
     - `6` clean `buy_xsol`
   - all `6` clean `buy_xsol` events occurred on `2026-03-29`
   - exact local times (`America/Los_Angeles`) and sizes:
     - `2026-03-29 10:20:41 AM`: `21,061.983677 hyUSD -> 344,971.328588 xSOL`
     - `2026-03-29 10:22:33 AM`: `23,479.769439 hyUSD -> 386,742.798409 xSOL`
     - `2026-03-29 10:25:42 AM`: `11,552.792571 hyUSD -> 190,916.507256 xSOL`
     - `2026-03-29 10:30:41 AM`: `30,131.233824 hyUSD -> 498,493.006733 xSOL`
     - `2026-03-29 03:42:33 PM`: `122,162.871688 hyUSD -> 2,076,030.302056 xSOL`
     - `2026-03-29 03:50:42 PM`: `206,746.658936 hyUSD -> 3,753,534.373934 xSOL`
   - the screenshot rows map exactly to the first four rows above
   - aggregate across all `6` clean events:
     - `415,135.310135 hyUSD` spent
     - `7,250,688.316976 xSOL` bought
10. Deployment-lot monitor added:
   - `stability_pool_deployments_monitor.py`
     - rebuilds persistent deployment lots from confirmed on-chain `buy_xsol` events
     - strict mode requires both `RebalanceStableToLever` and `SwapStableToLever` hints
     - can mark lots to market from either a manual `--xsol-price` or a saved Hylo stats JSON file
     - supports FIFO lot reduction if future confirmed `sell_xsol` events appear
   - `render_stability_pool_deployments_html.py`
     - renders the deployment lots plus mark history into a readable HTML table
   - `update_stability_pool_deployments.sh`
     - single wrapper to refresh pool events, rebuild lots, append a new mark snapshot, and rerender HTML
   - demo/sample artifacts:
     - `data/hylo_stats_sample.json`
     - `data/stability_pool_deployments.json`
     - `data/stability_pool_deployment_marks.jsonl`
     - `stability_pool_deployments.html`
11. Canonical future-LLM handoff spec added:
   - `HYLO_STABILITY_POOL_LLM_SPEC.md`
   - contains the source-of-truth addresses, definitions, confirmed findings, monitoring design, and resume point

## Files in this folder

- `hylo_tx_scan.py`: current tracer script
- `address_history_probe.py`: paginates Hylo addresses and mints to the oldest directly visible RPC signatures
- `scan_logmatches.sh`: log-pattern scanner using shell `curl`
- `scan_keeper_buys.sh`: raw keeper-buy extractor
- `summarize_keeper_clusters.py`: cluster summarizer
- `analyze_keeper_event_study.py`: market-join event-study helper
- `stability_pool_onchain_tracker.py`: on-chain balance snapshot logger and recent balance-change backfiller
- `render_stability_pool_tracker_html.py`: HTML renderer for the tracker outputs
- `analyze_viability.py`: profitability / viability summarizer for the Exchange-side and keeper-proxy samples
- `extract_current_buy_xsol.py`: extractor and reporter for all clean current-deployment `buy_xsol` rows
- `hylo_stability_pool_trace_report.html`: readable HTML report
- `hylo_viability_report.html`: current financial viability report from the public sample
- `current_buy_xsol_events.html`: clean current-deployment `buy_xsol` report
- `data/stability_pool_account_probe.json`: one-page public history depth for the current derived pool accounts
- `data/`: raw scan artifacts and cached transaction outputs
  - `stability_pool_balance_changes_full.jsonl`: exhaustive current-deployment pool-account balance changes
  - `current_buy_xsol_events.json`: clean current-deployment `buy_xsol` rows with market joins
  - `stability_pool_balance_snapshots.jsonl`: direct RPC snapshots of pool balances and LP supply
  - `stability_pool_balance_changes.jsonl`: recent balance-changing txs reconstructed from the pool token accounts
  - `viability_summary.json`: machine-readable current verdict and sample statistics
  - `hyex_swapstable_clusters_pages4_7.json`: grouped explicit Exchange-side `SwapStableToLever` clusters with forward returns
  - `address_history_probe.json`: oldest visible signatures from direct RPC pagination for Hylo accounts and mints
  - `protocol_age_summary.json`: combined scope check across RPC-visible history, GeckoTerminal pool creation dates, and Hylo GitHub repo dates
  - `official_rpc_before_oldest_check.json`: official Solana RPC check for whether anything older exists immediately before the current oldest visible signatures
  - `xsol_pools_geckoterminal.json`: xSOL pool metadata with pool creation dates
  - `hyusd_pools_geckoterminal.json`: hyUSD pool metadata with pool creation dates
  - `hylo_github_repos.json`: Hylo GitHub org repo metadata
