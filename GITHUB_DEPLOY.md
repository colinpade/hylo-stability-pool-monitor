# GitHub Deploy Notes

This repo is prepared for:
- GitHub Actions scheduled monitoring
- GitHub Pages public dashboard
- `ntfy.sh` push alerts when new confirmed Stability Pool xSOL buys or sells appear

## What the workflow does

The workflow:
- runs every 10 minutes
- attempts to fetch `https://hylo.so/api/hylo-stats`
- rebuilds the deployment-lot tracker
- refreshes the cached `xSOL / USDC` 5-minute market series
- rebuilds the grouped trigger signal report
- publishes the latest dashboard to GitHub Pages
- commits updated tracker artifacts back to `main`
- sends an `ntfy.sh` alert when a new confirmed buy or sell is detected

Workflow file:
- `.github/workflows/stability-pool-monitor.yml`

## Required GitHub setup

1. Create a GitHub repo and push this directory to it.
2. In GitHub:
   - Settings -> Pages
   - Source: GitHub Actions
3. Add repository secrets:
   - `NTFY_TOPIC`

Optional:
- `NTFY_AUTH_HEADER`
  - Example:
  - `Authorization: Bearer <token>`
  - only needed if your ntfy topic is protected

## Expected public URL

Once Pages is enabled, the dashboard should appear at:

`https://<github-user>.github.io/<repo>/`

The workflow copies:
- `stability_pool_deployments.html` -> site index
- `stability_pool_onchain_tracker.html`
- `hylo_stability_pool_trace_report.html`
- `hylo_viability_report.html`
- `current_buy_xsol_events.html`
- `stability_pool_signal_report.html`

## Manual run

You can trigger a run from:
- GitHub -> Actions -> `Stability Pool Monitor` -> `Run workflow`

## Current assumptions

- The repo is public.
- GitHub-hosted runners can reach `hylo.so/api/hylo-stats`.
- If the live stats fetch fails, the workflow falls back to the committed `data/live_hylo_stats.json`.
