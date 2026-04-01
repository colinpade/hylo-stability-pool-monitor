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


def card(label, value, subtext, tone="flat"):
    return f"""
    <div class="card">
      <div class="card-label">{html.escape(label)}</div>
      <div class="card-value {html.escape(tone)}">{html.escape(value)}</div>
      <div class="card-sub {html.escape(tone)}">{html.escape(subtext)}</div>
    </div>
    """


def build_cards(lot_state, latest_snapshot):
    summary = latest_snapshot["summary"] if latest_snapshot else {}
    cards = [
        card(
            "Deployments",
            str(lot_state.get("deployment_count", 0)),
            "confirmed buy_xsol lots",
        )
    ]
    if latest_snapshot:
        cards.extend(
            [
                card(
                    "Open Deployments",
                    str(summary["open_deployment_count"]),
                    latest_snapshot["captured_at_local"],
                ),
                card(
                    "Current xSOL Price",
                    fmt_num(latest_snapshot["xsol_price"], 9),
                    latest_snapshot["price_source"],
                ),
                card(
                    "Remaining xSOL",
                    fmt_num(summary["total_remaining_xsol"], 6),
                    "open lot exposure",
                ),
                card(
                    "Entry Value",
                    f"${fmt_num(summary['total_entry_value'])}",
                    "total deployed hyUSD",
                ),
                card(
                    "Current Value",
                    f"${fmt_num(summary['total_current_value'])}",
                    "mark-to-market",
                ),
                card(
                    "Net PnL",
                    f"${fmt_num(summary['total_net_pnl'])}",
                    fmt_pct(summary["total_net_pnl_pct"]),
                    pnl_class(summary["total_net_pnl"]),
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
        rows.append(
            f"""
            <tr>
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
              <td class="num">${fmt_num(current_price, 6) if current_price is not None else 'n/a'}</td>
              <td class="num">${fmt_num(current_value)}</td>
              <td class="num {pnl_class(net_pnl)}">
                <div>${fmt_num(net_pnl)}</div>
                <div class="subline {pnl_class(net_pnl)}">{fmt_pct(lot.get('net_pnl_pct'))}</div>
              </td>
              <td class="num">{html.escape(lot.get('days_held_display', 'n/a'))}</td>
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
