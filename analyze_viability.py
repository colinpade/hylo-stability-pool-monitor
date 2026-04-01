#!/usr/bin/env python3
import argparse
import html
import json
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def mean(values):
    return sum(values) / len(values) if values else None


def median(values):
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def summarize(rows, fields):
    out = {"count": len(rows)}
    for field in fields:
        values = [row[field] for row in rows if row.get(field) is not None]
        out[field] = {
            "mean": mean(values),
            "median": median(values),
            "count": len(values),
        }
    return out


def subset(rows, predicate):
    return [row for row in rows if predicate(row)]


def with_net_edge(rows):
    out = []
    for row in rows:
        item = dict(row)
        fill = row.get("execution_vs_market_pct")
        for horizon in ("1h_return_pct", "6h_return_pct", "24h_return_pct"):
            value = row.get(horizon)
            item[f"net_{horizon}"] = (
                None
                if fill is None or value is None
                else value - fill
            )
        out.append(item)
    return out


def fmt(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def table_row(label, summary, fields):
    cells = []
    for field in fields:
        info = summary[field]
        cells.append(f"<td>{fmt(info['mean'])}</td>")
        cells.append(f"<td>{fmt(info['median'])}</td>")
    return f"<tr><th>{html.escape(label)}</th>{''.join(cells)}</tr>"


def render_html(summary):
    exchange = summary["exchange"]
    keeper = summary["keeper"]
    verdict = summary["verdict"]
    key_cases = summary["exchange"]["largest_cases"]
    case_rows = []
    for row in key_cases:
        case_rows.append(
            f"""
            <tr>
              <td>{html.escape(row['start_utc'])}</td>
              <td>{fmt(row['hyusd_burned'], 0)}</td>
              <td>{fmt(row['execution_vs_market_pct'])}%</td>
              <td>{fmt(row.get('1h_return_pct'))}%</td>
              <td>{fmt(row.get('6h_return_pct'))}%</td>
              <td>{fmt(row.get('24h_return_pct'))}%</td>
              <td>{fmt(row.get('net_24h_return_pct'))}%</td>
            </tr>
            """
        )

    fields = [
        "execution_vs_market_pct",
        "1h_return_pct",
        "6h_return_pct",
        "24h_return_pct",
        "net_24h_return_pct",
    ]
    headers = """
      <tr>
        <th>Sample</th>
        <th>Fill Mean</th>
        <th>Fill Median</th>
        <th>1h Mean</th>
        <th>1h Median</th>
        <th>6h Mean</th>
        <th>6h Median</th>
        <th>24h Mean</th>
        <th>24h Median</th>
        <th>Net 24h Mean</th>
        <th>Net 24h Median</th>
      </tr>
    """
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hylo xSOL Viability Check</title>
    <style>
      :root {{
        --bg: #11151a;
        --panel: #171d24;
        --panel-alt: #1c252e;
        --border: #2e3945;
        --text: #eef4f8;
        --muted: #9bb0bc;
        --warn: #d8a04d;
        --good: #3aa675;
        --bad: #d96b5f;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--text);
        font-family: "Iowan Old Style", Georgia, serif;
        background:
          radial-gradient(circle at top left, rgba(216, 160, 77, 0.12), transparent 30%),
          radial-gradient(circle at bottom right, rgba(58, 166, 117, 0.10), transparent 32%),
          linear-gradient(180deg, #0f1418 0%, #0a0d10 100%);
      }}
      .wrap {{ max-width: 1180px; margin: 0 auto; padding: 34px 22px 44px; }}
      h1 {{ margin: 0 0 10px; font-size: 2.2rem; }}
      .sub {{ color: var(--muted); max-width: 900px; line-height: 1.55; }}
      .verdict {{
        margin: 20px 0 24px;
        padding: 18px 20px;
        border-radius: 18px;
        background: rgba(217, 107, 95, 0.12);
        border: 1px solid rgba(217, 107, 95, 0.24);
      }}
      .verdict strong {{ display: block; margin-bottom: 6px; color: #ffd8d2; }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        margin-bottom: 22px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
      }}
      .label {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
      .value {{ font-size: 1.55rem; }}
      .panel {{
        background: rgba(23, 29, 36, 0.9);
        border: 1px solid var(--border);
        border-radius: 20px;
        padding: 20px;
        margin-bottom: 18px;
      }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 11px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        text-align: left;
      }}
      th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
      .foot {{ color: var(--muted); line-height: 1.5; font-size: 0.94rem; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Hylo xSOL Viability Check</h1>
      <div class="sub">
        This report tests the public sample for actual financial edge. It uses the grouped Exchange-side
        <code>hyUSD -> xSOL</code> clusters and the smaller Stability Pool keeper-buy proxy clusters already recovered
        from chain, then checks whether entry quality and forward xSOL returns support a repeatable profitable pattern.
      </div>

      <div class="verdict">
        <strong>{html.escape(verdict['headline'])}</strong>
        {html.escape(verdict['detail'])}
      </div>

      <div class="grid">
        <div class="card">
          <div class="label">Exchange Sample</div>
          <div class="value">{exchange['all']['count']} clusters</div>
        </div>
        <div class="card">
          <div class="label">Mean Exchange Fill Vs Market</div>
          <div class="value">{fmt(exchange['all']['execution_vs_market_pct']['mean'])}%</div>
        </div>
        <div class="card">
          <div class="label">Mean Exchange 24h Return</div>
          <div class="value">{fmt(exchange['all']['24h_return_pct']['mean'])}%</div>
        </div>
        <div class="card">
          <div class="label">Mean Exchange Net 24h</div>
          <div class="value">{fmt(exchange['all']['net_24h_return_pct']['mean'])}%</div>
        </div>
        <div class="card">
          <div class="label">Keeper Proxy Sample</div>
          <div class="value">{keeper['all']['count']} clusters</div>
        </div>
        <div class="card">
          <div class="label">Keeper Proxy Mean 24h</div>
          <div class="value">{fmt(keeper['all']['24h_return_pct']['mean'])}%</div>
        </div>
      </div>

      <div class="panel">
        <h2>Exchange Sample Summary</h2>
        <table>
          <thead>{headers}</thead>
          <tbody>
            {table_row('All exchange clusters', exchange['all'], fields)}
            {table_row('Better or equal fill', exchange['better_or_equal_fill'], fields)}
            {table_row('Worse fill', exchange['worse_fill'], fields)}
            {table_row('Large clusters >= 1000 hyUSD', exchange['large_ge_1000'], fields)}
            {table_row('Small clusters < 1000 hyUSD', exchange['small_lt_1000'], fields)}
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h2>Largest Exchange Cases</h2>
        <table>
          <thead>
            <tr>
              <th>Start UTC</th>
              <th>hyUSD Burned</th>
              <th>Fill Vs Market</th>
              <th>1h</th>
              <th>6h</th>
              <th>24h</th>
              <th>Net 24h</th>
            </tr>
          </thead>
          <tbody>
            {''.join(case_rows)}
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h2>Keeper Proxy Summary</h2>
        <table>
          <thead>
            <tr>
              <th>Sample</th>
              <th>1h Mean</th>
              <th>1h Median</th>
              <th>6h Mean</th>
              <th>6h Median</th>
              <th>24h Mean</th>
              <th>24h Median</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>All keeper proxy clusters</th>
              <td>{fmt(keeper['all']['1h_return_pct']['mean'])}%</td>
              <td>{fmt(keeper['all']['1h_return_pct']['median'])}%</td>
              <td>{fmt(keeper['all']['6h_return_pct']['mean'])}%</td>
              <td>{fmt(keeper['all']['6h_return_pct']['median'])}%</td>
              <td>{fmt(keeper['all']['24h_return_pct']['mean'])}%</td>
              <td>{fmt(keeper['all']['24h_return_pct']['median'])}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="foot">
        The exact screenshot rows are still not directly matched on public chain data. So this is a public-sample viability test, not a full internal PnL audit.
        The threshold for saying "financially viable" should be stronger than a few isolated winning clusters. Right now the public sample does not clear that bar.
      </div>
    </div>
  </body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Summarize Hylo xSOL financial viability from public samples.")
    parser.add_argument(
        "--exchange",
        default="data/hyex_swapstable_clusters_pages4_7.json",
        help="Exchange cluster JSON input.",
    )
    parser.add_argument(
        "--keeper",
        default="data/hystab_keeper_buy_event_study.json",
        help="Keeper proxy cluster JSON input.",
    )
    parser.add_argument(
        "--json-out",
        default="data/viability_summary.json",
        help="Output JSON summary path.",
    )
    parser.add_argument(
        "--html-out",
        default="hylo_viability_report.html",
        help="Output HTML report path.",
    )
    args = parser.parse_args()

    exchange_rows = with_net_edge(load_json(args.exchange))
    keeper_rows = load_json(args.keeper)

    exchange = {
        "all": summarize(
            exchange_rows,
            [
                "execution_vs_market_pct",
                "1h_return_pct",
                "6h_return_pct",
                "24h_return_pct",
                "net_1h_return_pct",
                "net_6h_return_pct",
                "net_24h_return_pct",
            ],
        ),
        "better_or_equal_fill": summarize(
            subset(exchange_rows, lambda row: row["execution_vs_market_pct"] <= 0),
            [
                "execution_vs_market_pct",
                "1h_return_pct",
                "6h_return_pct",
                "24h_return_pct",
                "net_1h_return_pct",
                "net_6h_return_pct",
                "net_24h_return_pct",
            ],
        ),
        "worse_fill": summarize(
            subset(exchange_rows, lambda row: row["execution_vs_market_pct"] > 0),
            [
                "execution_vs_market_pct",
                "1h_return_pct",
                "6h_return_pct",
                "24h_return_pct",
                "net_1h_return_pct",
                "net_6h_return_pct",
                "net_24h_return_pct",
            ],
        ),
        "large_ge_1000": summarize(
            subset(exchange_rows, lambda row: row["hyusd_burned"] >= 1000),
            [
                "execution_vs_market_pct",
                "1h_return_pct",
                "6h_return_pct",
                "24h_return_pct",
                "net_1h_return_pct",
                "net_6h_return_pct",
                "net_24h_return_pct",
            ],
        ),
        "small_lt_1000": summarize(
            subset(exchange_rows, lambda row: row["hyusd_burned"] < 1000),
            [
                "execution_vs_market_pct",
                "1h_return_pct",
                "6h_return_pct",
                "24h_return_pct",
                "net_1h_return_pct",
                "net_6h_return_pct",
                "net_24h_return_pct",
            ],
        ),
        "largest_cases": sorted(
            exchange_rows,
            key=lambda row: row["hyusd_burned"],
            reverse=True,
        )[:8],
    }

    keeper = {
        "all": summarize(
            keeper_rows,
            ["1h_return_pct", "6h_return_pct", "24h_return_pct"],
        )
    }

    verdict = {
        "headline": "Current public sample does not yet confirm a financially viable edge.",
        "detail": (
            "The Exchange-side sample averages +0.12% at +1h, but -0.52% at +6h and -1.49% at +24h. "
            "After netting entry quality versus market, mean net +24h drops to "
            f"{fmt(exchange['all']['net_24h_return_pct']['mean'])}%. "
            "The keeper-proxy sample is weaker still at -5.59% mean +24h. "
            "That is not enough to claim the Stability Pool reliably buys bottoms profitably."
        ),
    }

    summary = {
        "verdict": verdict,
        "exchange": exchange,
        "keeper": keeper,
    }

    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    html_out = Path(args.html_out)
    html_out.write_text(render_html(summary), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
