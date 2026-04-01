# Hylo Stability Pool Research Spec

Last updated: 2026-03-31
Audience: future LLM / agent continuing this workspace
Status: active research, partially complete, with working on-chain monitoring

## 1. Purpose

This file is the canonical handoff spec for the Hylo Stability Pool / xSOL investigation.

Primary research questions:
- When does the Hylo Stability Pool buy xSOL on-chain?
- Can those buys be monitored directly from public chain data?
- Do those buys correspond to a profitable "bottom-buying" signal?
- Do the Hylo UI screenshots map to real on-chain events?

This file should be treated as more authoritative than earlier conversational guesses.

## 2. Canonical Entities

```yaml
protocol:
  name: Hylo
  network: Solana mainnet

programs:
  exchange: HYEXCHtHkBagdStcJCp3xbbb9B7sdMdWXFNj6mdsG4hn
  stability_pool: HysTabVUfmQBFcmzu1ctRd1Y1fxd66RBpboy1bmtDSQQ

mints:
  hyUSD: 5YMkXAYccHSGnHn9nob9xEvv6Pvka9DZWH7nTbotTu9E
  xSOL: 4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs
  sHYUSD: HnnGv3HrSqjRpgdFmx7vQGjntNEoex1SU4e9Lxcxuihz

derived_stability_pool_accounts:
  pool_auth: 5YrRAQag9BbJkauDtJkd1vsTquXT6N46oU8rJ66GDxHd
  hyusd_pool_ata: EqozKyMj7FVnLHc2cJj3VC25aBr4AhVh1cGM2WDajGe9
  xsol_pool_ata: 4GPXVXuzk8ABAUkoXeBJg8r9kccEXQjoi5vqSxE9rhk1

related_addresses:
  likely_keeper_signer: CcUrRBMqrCuMPVfd6sVTBJhyhBA1dE7qDoJkSy95bbcw
```

## 3. Definitions

### 3.1 Raw `buy_xsol` event

A transaction is labeled `buy_xsol` if the Stability Pool token balances satisfy both:
- `hyUSD` pool delta is negative
- `xSOL` pool delta is positive

This logic is implemented in:
- [stability_pool_onchain_tracker.py](/Users/49ers/codex_llm/explore_xsol/stability_pool_onchain_tracker.py)

Relevant function:
- `classify_balance_change()`

### 3.2 Confirmed `buy_xsol` event

A raw `buy_xsol` event is treated as confirmed when the same transaction also contains both log hints:
- `RebalanceStableToLever`
- `SwapStableToLever`

This strict filter is implemented in:
- [stability_pool_deployments_monitor.py](/Users/49ers/codex_llm/explore_xsol/stability_pool_deployments_monitor.py)

Relevant constants:
- `REQUIRED_BUY_HINTS = {"RebalanceStableToLever", "SwapStableToLever"}`

### 3.3 Deployment lot

One confirmed `buy_xsol` transaction becomes one persistent deployment lot with:
- timestamp
- signature
- `xsol_bought`
- `hyusd_spent`
- `entry_price = hyusd_spent / xsol_bought`

Lots stay open until future confirmed `sell_xsol` events reduce them FIFO.

## 4. Mapping Hylo `/stats` To Chain

The `/stats` page "Stability Pool Composition" section is driven by the same underlying values as the pool token accounts.

Observed UI fields:
- `stabilityPoolStats.stablecoinInPool`
- `stabilityPoolStats.levercoinInPool`
- `stabilityPoolStats.stablecoinNav`
- `stabilityPoolStats.levercoinNav`

Mapping:
- `stabilityPoolStats.stablecoinInPool` ~= `hyUSD` pool ATA balance at `Eqoz...`
- `stabilityPoolStats.levercoinInPool` ~= `xSOL` pool ATA balance at `4GPX...`

Interpretation:
- actual pool quantity changes should be monitored from the token accounts
- the UI composition percentages are value-based, not quantity-based
- composition can change because price changes even if token balances do not move

Therefore, the clean public signal for "Stability Pool bought xSOL" is:
- `hyUSD` pool balance down
- `xSOL` pool balance up
- same transaction
- ideally plus `RebalanceStableToLever` and `SwapStableToLever` logs

## 5. Confirmed Historical Findings

### 5.1 Program age and deployment history

Pre-March deployment definitely existed.

Evidence:
- current Exchange program `HYEXCH...` initial deploy:
  - `2025-04-11T21:37:28+00:00`
  - tx: `22Zs7waPESNUdG5g9D7QwiKFg3v6MJy4nf98jEoQvdG54jUWGzsvRJDidWPZVqpLTQaYWrKkYS6aVmZrnF3ix6bt`
- current Stability Pool program `HysTab...` initial deploy:
  - `2025-04-11T21:55:04+00:00`
  - tx: `5giigaQ6kGXdxxWiPRhH75EA4xAVyNZoDe9yDLmEA3dvC1bwXaW3oFvp9Wehp3XnEH4uY9f7UGMgyHPLSrA7UoWB`
- current Stability Pool latest upgrade:
  - `2026-01-28T21:12:15+00:00`
  - tx: `3hoSNogB9ZuHQDLJdY37g72aLgjM7wqYV5C3ybCtkfZvoqTy5CFcoWnpzm8wqxfZdHRLFth153fAP3qLR1oxrHkz`

Source artifact:
- [pre_march_deployment_evidence.json](/Users/49ers/codex_llm/explore_xsol/data/pre_march_deployment_evidence.json)

### 5.2 Pool-account visibility boundary is not the true pool start

The current derived pool token accounts only expose history back to:
- earliest visible tx: `2026-03-27T16:43:41+00:00`
- signature: `4ccAo8AcC8dD6Tn5dcqzdG1EspxW4RnwrHTMWw8QcmQS6TWPCbxXnL2yWqjexYwFz87DgEQPv7kpXLboRPf7K1Gv`

But that tx is not initialization. Before it, the pool already held:
- `9,420,245.035451 hyUSD`
- `3,366,664.232443 xSOL`

Conclusion:
- March 27 is a visibility boundary for the derived token accounts
- March 27 is not the true start of the current funded pool

Source artifact:
- [stability_pool_account_probe.json](/Users/49ers/codex_llm/explore_xsol/data/stability_pool_account_probe.json)

### 5.3 Exact confirmed current-deployment buy events

There are exactly `6` clean confirmed `buy_xsol` events in the currently reconstructed pool-account history.

These all occurred on `2026-03-29`.

```yaml
confirmed_buy_xsol_events:
  - local: 2026-03-29T10:20:41-07:00
    utc: 2026-03-29T17:20:41+00:00
    signature: 3CtFCHqTPmNuNdNEzQMhf2cvtcV4UpqyWci7ivziV3ijfvgvVP76gy5fHfAW5cvCNQUHjck1ri4coNsbG3yYJ5yp
    hyusd_spent: 21061.983677
    xsol_bought: 344971.328588
    entry_price: 0.06105430200013629

  - local: 2026-03-29T10:22:33-07:00
    utc: 2026-03-29T17:22:33+00:00
    signature: 2va9je3QTm8YzJQ3aBHfzoNk7XYVLLDKu6VCLvgF1NnRvrNDX8EPE371jCGRnnvmmht8TSxGzdfcn9CjK5KWVp9p
    hyusd_spent: 23479.769439
    xsol_bought: 386742.798409
    entry_price: 0.06071158800006655

  - local: 2026-03-29T10:25:42-07:00
    utc: 2026-03-29T17:25:42+00:00
    signature: 1XPqZtv6sP4fdEe4DneJgEDBGa1UuXTANjT517KkCEbJArKHYkcaTRpo5JyMNZG796VCAQHN8Tsrud31XLWmbmy
    hyusd_spent: 11552.792571
    xsol_bought: 190916.507256
    entry_price: 0.060512277000274554

  - local: 2026-03-29T10:30:41-07:00
    utc: 2026-03-29T17:30:41+00:00
    signature: 2bBRYnLM9P7VYdaDWHdxTBxEvFzXA4yELBrtpTJwUaxXMi2BLQR75ZsNZ6jL3Fi13ND6iqYBGGcrRDZJUr586Uk7
    hyusd_spent: 30131.233824
    xsol_bought: 498493.006733
    entry_price: 0.060444647000110714

  - local: 2026-03-29T15:42:33-07:00
    utc: 2026-03-29T22:42:33+00:00
    signature: 3hYrVvpBCKbo7Vm2teTudVA96Kpjppt2BLf9NoKTXWfEeiwaSDbDj6H4p8R2hNY3pub6YU4UKck7xNhseSVZpbMR
    hyusd_spent: 122162.871688
    xsol_bought: 2076030.302056
    entry_price: 0.05884445500001411

  - local: 2026-03-29T15:50:42-07:00
    utc: 2026-03-29T22:50:42+00:00
    signature: 5nJq6D9EXT3W6Cdb83PStHpjvN3udmBm9GaJvvckLPQ9TmjGKLCMsJWZueXvYtSUUupAm52TBEYUJkZ1g5heyjjF
    hyusd_spent: 206746.658936
    xsol_bought: 3753534.373934
    entry_price: 0.055080529000008385
```

Aggregate totals:
- `415,135.310135 hyUSD` spent
- `7,250,688.316976 xSOL` bought

Source artifact:
- [current_buy_xsol_events.json](/Users/49ers/codex_llm/explore_xsol/data/current_buy_xsol_events.json)

### 5.4 Screenshot mapping

The first screenshot with four rows maps exactly to the first four confirmed March 29 transactions.

The later "Stability Pool Deployments" screenshot maps to the full six confirmed lots by amount and timing.

### 5.5 January 1 through February 18 result

Current negative finding:
- `2026-01-01` through `2026-01-11`
  - `1,080` HysTab transactions scanned
  - `0` matches for `RebalanceStableToLever` / `SwapStableToLever`
- `2026-01-11` through `2026-02-18`
  - `9,454` HysTab transactions scanned
  - `0` matches for `RebalanceStableToLever` / `SwapStableToLever`

Combined:
- `10,534` scanned HysTab transactions from `2026-01-01` through `2026-02-18`
- `0` matches for the clean rebalance-buy pattern

Interpretation:
- there is currently no evidence that the exact March 29 clean buy pattern appeared in January or early-to-mid February 2026
- this weakens the assumption that the same public mechanism was already firing then
- this is a negative result for the exact pattern, not proof that no Hylo stabilization behavior existed in any form

Source artifacts:
- [hystab_sig_jan01_jan11_rebalance_matches.json](/Users/49ers/codex_llm/explore_xsol/data/hystab_sig_jan01_jan11_rebalance_matches.json)
- [hystab_sig_jan11_feb18_rebalance_matches.json](/Users/49ers/codex_llm/explore_xsol/data/hystab_sig_jan11_feb18_rebalance_matches.json)

### 5.6 Financial viability conclusion so far

Current public evidence does not prove a strong profitable signal.

Best current read:
- the mechanism is real
- the March 29 buy lots are real
- the pool often gets xSOL at a discount to market
- but the broader public sample has not yet demonstrated a robust "always bought the lows profitably" edge

Source artifact:
- [hylo_viability_report.html](/Users/49ers/codex_llm/explore_xsol/hylo_viability_report.html)

## 6. Monitoring Design

### 6.1 Recommended detection logic

To catch future Stability Pool xSOL buys:
- watch `Eqoz...` (`hyUSD` pool ATA)
- watch `4GPX...` (`xSOL` pool ATA)
- when `hyUSD` balance falls and `xSOL` balance rises in the same tx, create a raw `buy_xsol` event
- require both `RebalanceStableToLever` and `SwapStableToLever` log hints for a strict confirmed lot

### 6.2 Mark-to-market logic

To mark lots over time:
- use Hylo stats `exchangeStats.levercoinNav` as current xSOL price
- store snapshots over time instead of overwriting
- compute:
  - `current_value = remaining_xsol * current_price`
  - `unrealized_pnl = current_value - remaining_entry_value`
  - `net_pnl = realized_pnl + unrealized_pnl`

### 6.3 Current monitoring artifacts

- [stability_pool_deployments_monitor.py](/Users/49ers/codex_llm/explore_xsol/stability_pool_deployments_monitor.py)
- [render_stability_pool_deployments_html.py](/Users/49ers/codex_llm/explore_xsol/render_stability_pool_deployments_html.py)
- [update_stability_pool_deployments.sh](/Users/49ers/codex_llm/explore_xsol/update_stability_pool_deployments.sh)
- [stability_pool_deployments.html](/Users/49ers/codex_llm/explore_xsol/stability_pool_deployments.html)
- [stability_pool_deployments.json](/Users/49ers/codex_llm/explore_xsol/data/stability_pool_deployments.json)
- [stability_pool_deployment_marks.jsonl](/Users/49ers/codex_llm/explore_xsol/data/stability_pool_deployment_marks.jsonl)

Current monitor behavior:
- strict mode is enabled by default
- current lot count is `6`
- all current lots are still open
- the example mark snapshot used a saved Hylo stats payload

## 7. Important Caveats

- `hylo.so/api/hylo-stats` has been inconsistent / challenge-protected from this environment, so automatic live price pulls were not made fully reliable here
- the derived pool ATA history is shallow relative to program history
- not all Stability Pool-related behavior necessarily manifests as the exact strict rebalance-buy pattern
- the January-February negative result only covers the exact pattern searched

## 8. Open Questions

- Scan `2026-02-18` through `2026-03-29` HysTab history for the same exact strict pattern to close the remaining YTD gap
- Determine whether any non-strict or differently-routed stabilization flow occurred pre-March 29
- Improve direct capture of live Hylo `/api/hylo-stats`
- Extend event-study / profitability work using the confirmed lot set plus future observations

## 9. Recommended Resume Point

If a future LLM resumes from here, do this next:

1. Read this spec first.
2. Inspect:
   - [STATE.md](/Users/49ers/codex_llm/explore_xsol/STATE.md)
   - [stability_pool_deployments.html](/Users/49ers/codex_llm/explore_xsol/stability_pool_deployments.html)
   - [current_buy_xsol_events.json](/Users/49ers/codex_llm/explore_xsol/data/current_buy_xsol_events.json)
3. If the goal is live monitoring:
   - rerun [update_stability_pool_deployments.sh](/Users/49ers/codex_llm/explore_xsol/update_stability_pool_deployments.sh)
4. If the goal is deeper history:
   - continue the HysTab pattern scan from `2026-02-18` onward

