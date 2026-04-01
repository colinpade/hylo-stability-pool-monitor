#!/usr/bin/env python3
import argparse
import html
import json
from pathlib import Path


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_num(value, digits=6):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_pct(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}%"


def action_class(action):
    return {
        "buy_xsol": "buy",
        "sell_xsol": "sell",
        "initial": "neutral",
        "pool_grew_both": "other",
        "pool_shrank_both": "other",
        "hyusd_only": "other",
        "xsol_only": "other",
    }.get(action, "neutral")


def card(label, value, subtext):
    return f"""
    <div class="card">
      <div class="card-label">{html.escape(label)}</div>
      <div class="card-value">{html.escape(value)}</div>
      <div class="card-sub">{html.escape(subtext)}</div>
    </div>
    """


def build_summary(snapshots, events):
    latest = snapshots[-1] if snapshots else None
    buy_events = [row for row in events if row["action"] == "buy_xsol"]
    sell_events = [row for row in events if row["action"] == "sell_xsol"]
    spent = sum(abs(row["hyusd_pool"]["delta"]) for row in buy_events)
    received = sum(row["xsol_pool"]["delta"] for row in buy_events)
    latest_action = latest["action"] if latest else "n/a"
    latest_ratio = None
    if latest:
        hyusd = latest["hyusd_pool"]["amount"]
        xsol = latest["xsol_pool"]["amount"]
        latest_ratio = (
            (xsol / (xsol + hyusd)) * 100.0
            if (xsol + hyusd) > 0
            else None
        )
    cards = []
    if latest:
        cards.append(
            card(
                "Current hyUSD In Pool",
                fmt_num(latest["hyusd_pool"]["amount"]),
                f"slot {latest['slot']}",
            )
        )
        cards.append(
            card(
                "Current xSOL In Pool",
                fmt_num(latest["xsol_pool"]["amount"]),
                latest["captured_at_local"],
            )
        )
        cards.append(
            card(
                "sHYUSD Supply",
                fmt_num(latest["shyusd_mint"]["supply"]),
                "current LP supply",
            )
        )
        cards.append(
            card(
                "xSOL Quantity Share",
                fmt_pct(latest_ratio),
                "quantity-only, not NAV-adjusted",
            )
        )
        cards.append(
            card(
                "Latest Snapshot Action",
                latest_action,
                latest["captured_at_local"],
            )
        )
    cards.append(
        card(
            "Buy Events In Backfill",
            str(len(buy_events)),
            f"{fmt_num(spent)} hyUSD spent for {fmt_num(received)} xSOL",
        )
    )
    cards.append(
        card(
            "Sell Events In Backfill",
            str(len(sell_events)),
            "reverse pool moves",
        )
    )
    return "\n".join(cards)


def build_event_rows(events, limit):
    rows = []
    for row in list(reversed(events[-limit:])):
        hints = ", ".join(row.get("log_hints") or []) or "n/a"
        rows.append(
            f"""
            <tr class="{action_class(row['action'])}">
              <td>{html.escape(row.get('local') or 'n/a')}</td>
              <td><span class="pill {action_class(row['action'])}">{html.escape(row['action'])}</span></td>
              <td class="num">{fmt_num(row['hyusd_pool']['delta'])}</td>
              <td class="num">{fmt_num(row['xsol_pool']['delta'])}</td>
              <td class="num">{fmt_num(row.get('estimated_hyusd_per_xsol') or 0.0, 8) if row.get('estimated_hyusd_per_xsol') is not None else 'n/a'}</td>
              <td>{html.escape(hints)}</td>
              <td><a href="{html.escape(row['solscan_url'])}">{html.escape(row['signature'][:8])}...</a></td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_snapshot_rows(snapshots, limit):
    rows = []
    for row in list(reversed(snapshots[-limit:])):
        delta = row.get("delta") or {}
        rows.append(
            f"""
            <tr>
              <td>{html.escape(row['captured_at_local'])}</td>
              <td>{html.escape(row['action'])}</td>
              <td class="num">{fmt_num(row['hyusd_pool']['amount'])}</td>
              <td class="num">{fmt_num(row['xsol_pool']['amount'])}</td>
              <td class="num">{fmt_num(delta.get('hyusd_pool')) if delta else 'n/a'}</td>
              <td class="num">{fmt_num(delta.get('xsol_pool')) if delta else 'n/a'}</td>
              <td class="num">{fmt_num(row['shyusd_mint']['supply'])}</td>
              <td>{html.escape(str(row['slot']))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_html(snapshots, events):
    latest = snapshots[-1] if snapshots else None
    derived = latest["derived_accounts"] if latest else (events[-1]["derived_accounts"] if events and "derived_accounts" in events[-1] else None)
    addresses_html = ""
    if latest:
        addrs = latest["derived_accounts"]
        addresses_html = f"""
        <div class="address-grid">
          <div><strong>Pool Auth</strong><br><code>{html.escape(addrs['pool_auth'])}</code></div>
          <div><strong>hyUSD Pool</strong><br><code>{html.escape(addrs['hyusd_pool'])}</code></div>
          <div><strong>xSOL Pool</strong><br><code>{html.escape(addrs['xsol_pool'])}</code></div>
          <div><strong>Stability Pool Program</strong><br><code>{html.escape(addrs['stability_pool_program'])}</code></div>
        </div>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hylo Stability Pool On-Chain Tracker</title>
    <style>
      :root {{
        --bg: #0f1417;
        --panel: #171d21;
        --panel-2: #1d252a;
        --border: #2d3840;
        --text: #eef3f5;
        --muted: #9bb0b8;
        --buy: #1f8f5f;
        --sell: #a34e3c;
        --other: #7f8f9d;
        --accent: #d6b86f;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
        background:
          radial-gradient(circle at top right, rgba(214, 184, 111, 0.12), transparent 28%),
          radial-gradient(circle at left center, rgba(64, 126, 142, 0.16), transparent 35%),
          linear-gradient(180deg, #101518 0%, #0b0f12 100%);
        color: var(--text);
      }}
      .wrap {{
        max-width: 1180px;
        margin: 0 auto;
        padding: 36px 24px 48px;
      }}
      .hero {{
        display: grid;
        gap: 14px;
        margin-bottom: 26px;
      }}
      h1 {{
        margin: 0;
        font-size: 2.2rem;
        letter-spacing: 0.01em;
      }}
      .sub {{
        color: var(--muted);
        max-width: 820px;
        line-height: 1.5;
      }}
      .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        margin-bottom: 26px;
      }}
      .card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00)), var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 18px;
      }}
      .card-label {{
        color: var(--muted);
        font-size: 0.9rem;
        margin-bottom: 8px;
      }}
      .card-value {{
        font-size: 1.6rem;
        margin-bottom: 6px;
      }}
      .card-sub {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .panel {{
        background: rgba(23, 29, 33, 0.88);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 20px;
        margin-bottom: 18px;
        backdrop-filter: blur(8px);
      }}
      .panel h2 {{
        margin: 0 0 12px;
        font-size: 1.15rem;
      }}
      .address-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 12px;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th, td {{
        padding: 12px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        text-align: left;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.84rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      td.num {{
        text-align: right;
        font-variant-numeric: tabular-nums;
      }}
      .pill {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.8rem;
        border: 1px solid transparent;
      }}
      .pill.buy {{
        color: #d7ffea;
        background: rgba(31, 143, 95, 0.16);
        border-color: rgba(31, 143, 95, 0.35);
      }}
      .pill.sell {{
        color: #ffd9d1;
        background: rgba(163, 78, 60, 0.16);
        border-color: rgba(163, 78, 60, 0.35);
      }}
      .pill.other, .pill.neutral {{
        color: #e5edf1;
        background: rgba(127, 143, 157, 0.14);
        border-color: rgba(127, 143, 157, 0.3);
      }}
      a {{
        color: #90d4f2;
        text-decoration: none;
      }}
      code {{
        color: #f3d893;
        word-break: break-all;
      }}
      .foot {{
        color: var(--muted);
        font-size: 0.92rem;
        line-height: 1.5;
      }}
      @media (max-width: 760px) {{
        .wrap {{ padding: 24px 14px 32px; }}
        h1 {{ font-size: 1.7rem; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <section class="hero">
        <h1>Hylo Stability Pool On-Chain Tracker</h1>
        <div class="sub">
          Direct RPC view of the Stability Pool token accounts. This tracks actual pool-balance changes in
          <code>hyUSD</code> and <code>xSOL</code>, which is the cleanest public signal for when the pool likely bought or sold <code>xSOL</code>.
          Quantity share is shown only as a rough gauge; it is not the same as the UI's NAV-adjusted composition percentage.
        </div>
      </section>

      <section class="cards">
        {build_summary(snapshots, events)}
      </section>

      <section class="panel">
        <h2>Derived On-Chain Addresses</h2>
        {addresses_html}
      </section>

      <section class="panel">
        <h2>Recent Balance-Changing Transactions</h2>
        <table>
          <thead>
            <tr>
              <th>Local Time</th>
              <th>Action</th>
              <th>hyUSD Delta</th>
              <th>xSOL Delta</th>
              <th>Implied hyUSD/xSOL</th>
              <th>Hints</th>
              <th>Tx</th>
            </tr>
          </thead>
          <tbody>
            {build_event_rows(events, limit=80)}
          </tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Recent Snapshots</h2>
        <table>
          <thead>
            <tr>
              <th>Captured</th>
              <th>Action</th>
              <th>hyUSD In Pool</th>
              <th>xSOL In Pool</th>
              <th>hyUSD Delta</th>
              <th>xSOL Delta</th>
              <th>sHYUSD Supply</th>
              <th>Slot</th>
            </tr>
          </thead>
          <tbody>
            {build_snapshot_rows(snapshots, limit=40)}
          </tbody>
        </table>
      </section>

      <section class="foot">
        <p>
          Notes: a <code>buy_xsol</code> row means the pool's <code>hyUSD</code> balance dropped while the pool's <code>xSOL</code> balance rose
          in the same transaction. A <code>sell_xsol</code> row is the reverse. Mixed rows still matter, but they do not cleanly describe
          a single <code>hyUSD -> xSOL</code> conversion.
        </p>
      </section>
    </div>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render Stability Pool on-chain tracker HTML.")
    parser.add_argument(
        "--snapshots",
        default="data/stability_pool_balance_snapshots.jsonl",
        help="Snapshot JSONL path.",
    )
    parser.add_argument(
        "--events",
        default="data/stability_pool_balance_changes.jsonl",
        help="Balance-change JSONL path.",
    )
    parser.add_argument(
        "--out",
        default="stability_pool_onchain_tracker.html",
        help="Output HTML path.",
    )
    args = parser.parse_args()

    snapshots = load_jsonl(Path(args.snapshots))
    events = load_jsonl(Path(args.events))
    output = Path(args.out)
    output.write_text(render_html(snapshots, events), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
