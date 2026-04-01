#!/usr/bin/env python3
import argparse
import html
import json
from datetime import datetime
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_num(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_pct(value, digits=2):
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def format_local_date(local_iso):
    if not local_iso:
        return "n/a", ""
    dt = datetime.fromisoformat(local_iso)
    return dt.strftime("%b %d"), dt.strftime("%H:%M:%S")


def pnl_class(value):
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def json_for_script(payload):
    return json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")


def card(label, value, subtext, tone="flat", card_id=None, value_id=None, subtext_id=None):
    card_attr = f' id="{html.escape(card_id)}"' if card_id else ""
    value_attr = f' id="{html.escape(value_id)}"' if value_id else ""
    subtext_attr = f' id="{html.escape(subtext_id)}"' if subtext_id else ""
    return f"""
    <div class="card"{card_attr}>
      <div class="card-label">{html.escape(label)}</div>
      <div class="card-value {html.escape(tone)}"{value_attr}>{html.escape(value)}</div>
      <div class="card-sub {html.escape(tone)}"{subtext_attr}>{html.escape(subtext)}</div>
    </div>
    """


def build_cards(lot_state, latest_snapshot):
    summary = latest_snapshot["summary"] if latest_snapshot else {}
    cards = [
        card(
            "Deployments",
            str(lot_state.get("deployment_count", 0)),
            "confirmed buy_xsol lots",
            card_id="card-deployments",
            value_id="summary-deployment-count",
        )
    ]
    if latest_snapshot:
        cards.extend(
            [
                card(
                    "Open Deployments",
                    str(summary["open_deployment_count"]),
                    latest_snapshot["captured_at_local"],
                    card_id="card-open-deployments",
                    value_id="summary-open-deployment-count",
                    subtext_id="summary-open-deployment-sub",
                ),
                card(
                    "Current xSOL Price",
                    fmt_num(latest_snapshot["xsol_price"], 9),
                    latest_snapshot["price_source"],
                    card_id="card-xsol-price",
                    value_id="summary-xsol-price",
                    subtext_id="summary-xsol-price-sub",
                ),
                card(
                    "Remaining xSOL",
                    fmt_num(summary["total_remaining_xsol"], 6),
                    "open lot exposure",
                    card_id="card-remaining-xsol",
                    value_id="summary-remaining-xsol",
                    subtext_id="summary-remaining-xsol-sub",
                ),
                card(
                    "Entry Value",
                    f"${fmt_num(summary['total_entry_value'])}",
                    "total deployed hyUSD",
                    card_id="card-entry-value",
                    value_id="summary-entry-value",
                    subtext_id="summary-entry-value-sub",
                ),
                card(
                    "Current Value",
                    f"${fmt_num(summary['total_current_value'])}",
                    "mark-to-market",
                    card_id="card-current-value",
                    value_id="summary-current-value",
                    subtext_id="summary-current-value-sub",
                ),
                card(
                    "Net PnL",
                    f"${fmt_num(summary['total_net_pnl'])}",
                    fmt_pct(summary["total_net_pnl_pct"]),
                    pnl_class(summary["total_net_pnl"]),
                    card_id="card-net-pnl",
                    value_id="summary-net-pnl",
                    subtext_id="summary-net-pnl-sub",
                ),
                card(
                    "Latest SOL Price",
                    "Loading...",
                    "live refresh every 60s",
                    card_id="card-sol-price",
                    value_id="summary-sol-price",
                    subtext_id="summary-sol-price-sub",
                ),
            ]
        )
    return "\n".join(cards)


def build_lot_rows(lots):
    rows = []
    for lot in sorted(lots, key=lambda row: row["block_time"] or 0, reverse=True):
        day_label, time_label = format_local_date(lot.get("local"))
        current_price = lot.get("current_price")
        current_value = lot.get("current_value")
        net_pnl = lot.get("net_pnl")
        row_class = pnl_class(net_pnl)
        rows.append(
            f"""
            <tr data-lot-id="{html.escape(lot['lot_id'])}">
              <td>
                <div class="date-main">{html.escape(day_label)}</div>
                <div class="date-sub">{html.escape(time_label)}</div>
              </td>
              <td class="num">
                <div>{fmt_num(lot['xsol_bought'], 2)}</div>
                <div class="subline">{html.escape(lot['status'])}</div>
              </td>
              <td class="num">${fmt_num(lot['entry_price'], 6)}</td>
              <td class="num">${fmt_num(lot['entry_value'])}</td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-current-price">${fmt_num(current_price, 6) if current_price is not None else 'n/a'}</span></td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-current-value">${fmt_num(current_value)}</span></td>
              <td class="num">
                <div id="{html.escape(lot['lot_id'])}-net-pnl" class="{row_class}">${fmt_num(net_pnl)}</div>
                <div id="{html.escape(lot['lot_id'])}-net-pnl-pct" class="subline {row_class}">{fmt_pct(lot.get('net_pnl_pct'))}</div>
              </td>
              <td class="num"><span id="{html.escape(lot['lot_id'])}-days-held">{html.escape(lot.get('days_held_display', 'n/a'))}</span></td>
              <td><a href="{html.escape(lot['solscan_url'])}">{html.escape(lot['signature'][:10])}...</a></td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_mark_rows(snapshots):
    rows = []
    for row in reversed(snapshots[-40:]):
        summary = row["summary"]
        rows.append(
            f"""
            <tr>
              <td>{html.escape(row['captured_at_local'])}</td>
              <td class="num">{fmt_num(row['xsol_price'], 9)}</td>
              <td>{html.escape(row['price_source'])}</td>
              <td class="num">{summary['open_deployment_count']}</td>
              <td class="num">${fmt_num(summary['total_current_value'])}</td>
              <td class="num {pnl_class(summary['total_net_pnl'])}">${fmt_num(summary['total_net_pnl'])}</td>
              <td class="num {pnl_class(summary['total_net_pnl'])}">{fmt_pct(summary['total_net_pnl_pct'])}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_html(lot_state, snapshots):
    latest_snapshot = snapshots[-1] if snapshots else None
    lots = latest_snapshot["lots"] if latest_snapshot else lot_state.get("lots", [])
    price_details = latest_snapshot.get("price_source_details") if latest_snapshot else None
    live_payload = {
        "generated_at_utc": lot_state.get("generated_at_utc"),
        "initial_xsol_price": latest_snapshot.get("xsol_price") if latest_snapshot else None,
        "initial_price_source": latest_snapshot.get("price_source") if latest_snapshot else None,
        "lots": lots,
    }
    details_html = ""
    if price_details:
        details_html = f"""
        <div class="details-grid">
          <div><strong>Exchange NAV</strong><br><code>{html.escape(str(price_details.get('exchange_levercoin_nav')))}</code></div>
          <div><strong>Pool NAV</strong><br><code>{html.escape(str(price_details.get('stability_pool_levercoin_nav')))}</code></div>
          <div><strong>Mode</strong><br><code>{html.escape(json.dumps(price_details.get('stability_mode')))}</code></div>
        </div>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hylo Stability Pool Deployments</title>
    <style>
      :root {{
        --bg: #0c0f11;
        --panel: #14181b;
        --panel-2: #1a1f23;
        --border: #2b3338;
        --text: #eef2f4;
        --muted: #9baab3;
        --up: #4ed38a;
        --down: #e07163;
        --flat: #d9b86b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--text);
        font-family: "Iowan Old Style", Georgia, serif;
        background:
          radial-gradient(circle at top right, rgba(96, 145, 255, 0.08), transparent 24%),
          radial-gradient(circle at left top, rgba(217, 184, 107, 0.10), transparent 30%),
          linear-gradient(180deg, #0b0e10 0%, #090b0d 100%);
      }}
      .wrap {{ max-width: 1240px; margin: 0 auto; padding: 32px 22px 44px; }}
      h1 {{ margin: 0 0 10px; font-size: 2.2rem; }}
      .sub {{ color: var(--muted); line-height: 1.55; max-width: 900px; }}
      .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 14px;
        margin: 24px 0;
      }}
      .card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00)), var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
      }}
      .card-label {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
      .card-value {{ font-size: 1.5rem; }}
      .card-sub {{ color: var(--muted); font-size: 0.92rem; margin-top: 6px; }}
      .card-value.flat,
      .card-sub.flat {{ color: inherit; }}
      .panel {{
        background: rgba(20,24,27,0.90);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 20px;
        margin-bottom: 18px;
      }}
      h2 {{ margin: 0 0 12px; font-size: 1.1rem; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 12px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        text-align: left;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
      .date-main {{ font-size: 1rem; }}
      .date-sub, .subline {{ color: var(--muted); font-size: 0.92rem; margin-top: 4px; }}
      .up {{ color: var(--up); }}
      .down {{ color: var(--down); }}
      .flat {{ color: var(--flat); }}
      a {{ color: #91d4f1; text-decoration: none; }}
      code {{ color: #f4d48f; word-break: break-all; }}
      .details-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
      }}
      .foot {{
        color: var(--muted);
        line-height: 1.5;
        font-size: 0.92rem;
      }}
      .live-note {{
        margin-top: 10px;
        color: var(--muted);
        font-size: 0.9rem;
      }}
      @media (max-width: 760px) {{
        .wrap {{ padding: 20px 12px 30px; }}
        h1 {{ font-size: 1.75rem; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Hylo Stability Pool Deployments</h1>
      <div class="sub">
        Persistent lot tracker built from confirmed on-chain <code>buy_xsol</code> events. A new deployment is created
        when the Stability Pool spends <code>hyUSD</code>, receives <code>xSOL</code>, and the transaction logs include the
        expected rebalance hints. Mark snapshots let you monitor these lots over time instead of only seeing a single screenshot.
      </div>
      <div class="live-note" id="live-refresh-status">
        Waiting for live DexScreener pricing. Current values will refresh in-browser every 60 seconds.
      </div>

      <section class="cards">
        {build_cards(lot_state, latest_snapshot)}
      </section>

      <section class="panel">
        <h2>Open And Historical Deployment Lots</h2>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Amount</th>
              <th>Entry Price</th>
              <th>Entry Value</th>
              <th>Current Price</th>
              <th>Current Value</th>
              <th>PnL</th>
              <th>Days Held</th>
              <th>Tx</th>
            </tr>
          </thead>
          <tbody>
            {build_lot_rows(lots)}
          </tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Mark History</h2>
        <table>
          <thead>
            <tr>
              <th>Captured</th>
              <th>xSOL Price</th>
              <th>Price Source</th>
              <th>Open Lots</th>
              <th>Current Value</th>
              <th>Net PnL</th>
              <th>Net PnL %</th>
            </tr>
          </thead>
          <tbody>
            {build_mark_rows(snapshots)}
          </tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Latest Price Context</h2>
        {details_html or '<div class="foot">No structured price-source details were stored for the latest mark.</div>'}
      </section>

      <section class="foot">
        <p>
          This tracker treats confirmed <code>buy_xsol</code> events as deployment lots and carries them forward across repeated marks.
          If future confirmed <code>sell_xsol</code> events appear, the monitor applies them FIFO against the open lots.
        </p>
        <p>
          Source repo used for the on-chain event and instruction mapping:
          <a href="https://github.com/hylo-so/sdk">hylo-so/sdk</a>.
        </p>
      </section>
    </div>
    <script id="live-lot-state" type="application/json">{html.escape(json_for_script(live_payload), quote=False)}</script>
    <script>
      (() => {{
        const REFRESH_SECONDS = 60;
        const XSOL_TOKEN = "4sWNB8zGWHkh6UnmwiEtzNxL4XrN7uK9tosbESbJFfVs";
        const SOL_TOKEN = "So11111111111111111111111111111111111111112";
        const payload = JSON.parse(document.getElementById("live-lot-state").textContent);
        const lotRows = payload.lots || [];
        let countdown = REFRESH_SECONDS;
        let livePriceState = {{
          xsol: payload.initial_xsol_price,
          xsolSource: payload.initial_price_source || "saved mark",
          sol: null,
          solSource: "",
          lastUpdated: null,
          lastError: "",
        }};

        function formatNum(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          return Number(value).toLocaleString(undefined, {{
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
          }});
        }}

        function formatCurrency(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          return `$${{formatNum(value, digits)}}`;
        }}

        function formatPct(value, digits = 2) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "n/a";
          }}
          const sign = value > 0 ? "+" : "";
          return `${{sign}}${{Number(value).toFixed(digits)}}%`;
        }}

        function pnlClass(value) {{
          if (value === null || value === undefined || Number.isNaN(value)) {{
            return "flat";
          }}
          if (value > 0) {{
            return "up";
          }}
          if (value < 0) {{
            return "down";
          }}
          return "flat";
        }}

        function setTone(element, value) {{
          if (!element) {{
            return;
          }}
          element.classList.remove("up", "down", "flat");
          element.classList.add(pnlClass(value));
        }}

        function setText(id, value) {{
          const el = document.getElementById(id);
          if (el) {{
            el.textContent = value;
          }}
        }}

        function formatDaysHeld(utc) {{
          if (!utc) {{
            return "n/a";
          }}
          const ms = Date.now() - Date.parse(utc);
          const days = Math.max(0, Math.floor(ms / 86400000));
          return `${{days}}d`;
        }}

        function bestPair(pairs, filterFn = null) {{
          const filtered = (pairs || []).filter((pair) => {{
            if (!filterFn) {{
              return true;
            }}
            return filterFn(pair);
          }});
          if (!filtered.length) {{
            return null;
          }}
          return filtered.sort((a, b) => (Number(b?.liquidity?.usd || 0) - Number(a?.liquidity?.usd || 0)))[0];
        }}

        async function fetchDexPrice(tokenMint, filterFn = null) {{
          const response = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${{tokenMint}}`, {{
            cache: "no-store",
          }});
          if (!response.ok) {{
            throw new Error(`DexScreener returned ${{response.status}}`);
          }}
          const data = await response.json();
          const pair = bestPair(data.pairs || [], filterFn);
          if (!pair || !pair.priceUsd) {{
            throw new Error("No liquid pair found");
          }}
          return {{
            price: Number(pair.priceUsd),
            dexId: pair.dexId || "dexscreener",
            pairAddress: pair.pairAddress || "",
            liquidityUsd: Number(pair?.liquidity?.usd || 0),
            quoteSymbol: pair?.quoteToken?.symbol || "",
          }};
        }}

        function recomputeView() {{
          const xsolPrice = Number(livePriceState.xsol);
          if (!xsolPrice) {{
            return;
          }}
          let totalEntryValue = 0;
          let totalCurrentValue = 0;
          let totalNetPnl = 0;
          let totalRemainingXsol = 0;
          let openDeploymentCount = 0;

          for (const lot of lotRows) {{
            const remainingXsol = Number(lot.remaining_xsol || 0);
            const remainingEntryValue = Number(lot.remaining_entry_value || 0);
            const realizedPnl = Number(lot.realized_pnl || 0);
            const currentValue = remainingXsol * xsolPrice;
            const unrealizedPnl = currentValue - remainingEntryValue;
            const netPnl = realizedPnl + unrealizedPnl;
            const netPnlPct = Number(lot.entry_value || 0) > 0 ? (netPnl / Number(lot.entry_value)) * 100 : null;

            totalEntryValue += Number(lot.entry_value || 0);
            totalCurrentValue += currentValue;
            totalNetPnl += netPnl;
            totalRemainingXsol += remainingXsol;
            if (remainingXsol > 0) {{
              openDeploymentCount += 1;
            }}

            setText(`${{lot.lot_id}}-current-price`, formatCurrency(xsolPrice, 6));
            setText(`${{lot.lot_id}}-current-value`, formatCurrency(currentValue));
            setText(`${{lot.lot_id}}-net-pnl`, formatCurrency(netPnl));
            setText(`${{lot.lot_id}}-net-pnl-pct`, formatPct(netPnlPct));
            setText(`${{lot.lot_id}}-days-held`, formatDaysHeld(lot.utc));
            setTone(document.getElementById(`${{lot.lot_id}}-net-pnl`), netPnl);
            setTone(document.getElementById(`${{lot.lot_id}}-net-pnl-pct`), netPnl);
          }}

          const totalNetPnlPct = totalEntryValue > 0 ? (totalNetPnl / totalEntryValue) * 100 : null;
          setText("summary-open-deployment-count", String(openDeploymentCount));
          setText("summary-remaining-xsol", formatNum(totalRemainingXsol, 6));
          setText("summary-entry-value", formatCurrency(totalEntryValue));
          setText("summary-current-value", formatCurrency(totalCurrentValue));
          setText("summary-net-pnl", formatCurrency(totalNetPnl));
          setText("summary-net-pnl-sub", formatPct(totalNetPnlPct));
          setText("summary-current-value-sub", "mark-to-market");
          setText("summary-xsol-price", formatNum(xsolPrice, 9));
          setTone(document.getElementById("summary-net-pnl"), totalNetPnl);
          setTone(document.getElementById("summary-net-pnl-sub"), totalNetPnl);
        }}

        function renderLiveState() {{
          if (livePriceState.xsol) {{
            setText(
              "summary-xsol-price-sub",
              `${{livePriceState.xsolSource}} • refresh in ${{countdown}}s`
            );
          }}
          if (livePriceState.sol) {{
            setText("summary-sol-price", formatCurrency(livePriceState.sol));
            setText(
              "summary-sol-price-sub",
              `${{livePriceState.solSource}} • refresh in ${{countdown}}s`
            );
          }} else {{
            setText("summary-sol-price", "Loading...");
            setText("summary-sol-price-sub", `refresh in ${{countdown}}s`);
          }}
          if (livePriceState.lastUpdated) {{
            const localTime = livePriceState.lastUpdated.toLocaleTimeString();
            setText("live-refresh-status", `Live prices updated at ${{localTime}}. Next refresh in ${{countdown}}s.`);
          }} else if (livePriceState.lastError) {{
            setText("live-refresh-status", `Live price refresh failed: ${{livePriceState.lastError}}. Retrying in ${{countdown}}s.`);
          }} else {{
            setText("live-refresh-status", `Waiting for live DexScreener pricing. Current values will refresh in-browser every ${{REFRESH_SECONDS}} seconds.`);
          }}
        }}

        async function refreshPrices() {{
          try {{
            const [xsolResult, solResult] = await Promise.all([
              fetchDexPrice(XSOL_TOKEN),
              fetchDexPrice(
                SOL_TOKEN,
                (pair) => {{
                  const quote = pair?.quoteToken?.symbol;
                  return quote === "USDC" || quote === "USDT";
                }}
              ),
            ]);
            livePriceState = {{
              xsol: xsolResult.price,
              xsolSource: `DexScreener ${{xsolResult.dexId}}`,
              sol: solResult.price,
              solSource: `DexScreener ${{solResult.dexId}}`,
              lastUpdated: new Date(),
              lastError: "",
            }};
            recomputeView();
          }} catch (error) {{
            console.error(error);
            livePriceState.lastError = error?.message || "unknown error";
          }}
          countdown = REFRESH_SECONDS;
          renderLiveState();
        }}

        recomputeView();
        renderLiveState();
        refreshPrices();
        window.setInterval(() => {{
          countdown -= 1;
          if (countdown <= 0) {{
            refreshPrices();
            return;
          }}
          renderLiveState();
        }}, 1000);
      }})();
    </script>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render Stability Pool deployment-lot HTML.")
    parser.add_argument(
        "--lots",
        default="data/stability_pool_deployments.json",
        help="Deployment lot state JSON path.",
    )
    parser.add_argument(
        "--marks",
        default="data/stability_pool_deployment_marks.jsonl",
        help="Mark-to-market snapshot JSONL path.",
    )
    parser.add_argument(
        "--out",
        default="stability_pool_deployments.html",
        help="Output HTML path.",
    )
    args = parser.parse_args()
    lot_state = load_json(args.lots)
    marks = load_jsonl(args.marks)
    Path(args.out).write_text(render_html(lot_state, marks), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
