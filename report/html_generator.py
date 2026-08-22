from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


class HTMLDashboardGenerator:
    """把 PT/PD 库存分析生成一个可直接发布的静态交互网页。"""

    def __init__(self, data_folder="data", report_data_folder="report_data"):
        self.data_folder = Path(data_folder)
        self.report_data_folder = Path(report_data_folder)

    def _load_metal(self, metal):
        analysis = pd.read_csv(
            self.report_data_folder / f"{metal}_inventory_analysis.csv"
        )
        inventory = pd.read_csv(
            self.data_folder / f"gfex_{metal}_warehouse_receipt.csv"
        )

        analysis["日期"] = pd.to_datetime(analysis["日期"]).dt.strftime("%Y-%m-%d")
        inventory["date"] = pd.to_datetime(
            inventory["date"].astype(str), format="%Y%m%d", errors="coerce"
        )
        inventory = inventory.dropna(subset=["date"])
        latest = inventory["date"].max()
        previous_dates = inventory.loc[inventory["date"] < latest, "date"]
        previous = previous_dates.max() if not previous_dates.empty else latest

        inventory["today_receipt"] = pd.to_numeric(
            inventory["today_receipt"], errors="coerce"
        ).fillna(0)
        inventory["change"] = pd.to_numeric(
            inventory["change"], errors="coerce"
        ).fillna(0)
        warehouse_columns = sorted(inventory["warehouse"].dropna().astype(str).unique())
        warehouse_history = []
        for date, daily in inventory.groupby("date", sort=True):
            daily = daily.groupby("warehouse", as_index=False)[
                ["today_receipt", "change"]
            ].sum()
            warehouses = {
                str(row.warehouse): {
                    "inventory": float(row.today_receipt),
                    "change": float(row.change),
                }
                for row in daily.itertuples(index=False)
            }
            warehouse_history.append({
                "date": date.strftime("%Y-%m-%d"),
                "warehouses": warehouses,
            })

        number_columns = [column for column in analysis.columns if column != "日期"]
        analysis[number_columns] = analysis[number_columns].apply(
            pd.to_numeric, errors="coerce"
        )

        # pandas 浮点列中的 NaN 用 where(..., None) 后仍可能保留 NaN。
        # 通过 pandas JSON 序列化可稳定转为 null，避免前端切换品种时图表中断。
        return {
            "analysis": json.loads(
                analysis.to_json(orient="records", force_ascii=False)
            ),
            "warehouseColumns": warehouse_columns,
            "warehouseHistory": warehouse_history,
            "latestDate": latest.strftime("%Y-%m-%d"),
            "previousDate": previous.strftime("%Y-%m-%d"),
        }

    def generate(self, output_file, metals=("PT", "PD")):
        payload = {metal: self._load_metal(metal) for metal in metals}
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

        html = _HTML_TEMPLATE.replace("__PGM_DATA__", data_json)
        output_file.write_text(html, encoding="utf-8")
        print(f"HTML dashboard saved: {output_file.resolve()}")


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="广州期货交易所铂、钯仓单交互研究报告">
  <title>广期所铂/钯库存</title>
  <script src="assets/vendor/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #07111f; --panel: #0d1b2d; --panel2: #10233a;
      --text: #edf6ff; --muted: #89a0b8; --line: #213852;
      --cyan: #31d7c5; --gold: #f0bd63; --blue: #65a7ff;
      --green: #46d29a; --red: #ff7285;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--text); background:
        radial-gradient(circle at 8% 0%, #12314b 0, transparent 32%),
        radial-gradient(circle at 100% 10%, #232746 0, transparent 30%), var(--bg);
      font-family: Inter, "Segoe UI", "Microsoft YaHei", sans-serif;
    }
    .shell { width: min(1440px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 56px; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 24px; }
    .eyebrow { color: var(--cyan); letter-spacing: .16em; font-size: 12px; font-weight: 700; }
    h1 { font-size: clamp(28px, 5vw, 52px); margin: 8px 0 6px; letter-spacing: -.04em; }
    .subtitle { color: var(--muted); margin: 0; }
    .switch { display: flex; padding: 4px; border: 1px solid var(--line); border-radius: 12px; background: #081625; }
    .switch button {
      border: 0; color: var(--muted); background: transparent; padding: 10px 20px;
      border-radius: 9px; cursor: pointer; font: inherit; font-weight: 700;
    }
    .switch button.active { color: #04131c; background: var(--cyan); }
    .header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .market-link { color: var(--cyan); text-decoration: none; border: 1px solid var(--line);
      background: #081625; padding: 10px 14px; border-radius: 10px; font-weight: 700; }
    .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 14px; }
    .card, .panel {
      background: linear-gradient(145deg, rgba(17,38,61,.94), rgba(10,25,42,.96));
      border: 1px solid var(--line); box-shadow: 0 18px 50px rgba(0,0,0,.16);
    }
    .card { padding: 18px; border-radius: 16px; }
    .label { color: var(--muted); font-size: 13px; }
    .value { font-size: clamp(25px, 3vw, 38px); font-weight: 760; margin: 8px 0 3px; }
    .delta { font-size: 13px; color: var(--muted); }
    .positive { color: var(--green); } .negative { color: var(--red); }
    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .panel { border-radius: 18px; padding: 18px; min-width: 0; }
    .panel-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 8px; }
    .panel h2 { font-size: 16px; margin: 0; }
    .period { color: var(--muted); font-size: 12px; }
    #trend, #seasonal { width: 100%; height: 430px; }
    .table-panel { margin-top: 14px; }
    .metric-switch { display: flex; gap: 6px; flex-wrap: wrap; }
    .metric-switch button {
      border: 1px solid var(--line); color: var(--muted); background: #091827;
      padding: 6px 10px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 12px;
    }
    .metric-switch button.active { color: #06141d; background: var(--gold); border-color: var(--gold); }
    .table-wrap { overflow: auto; max-height: 520px; border-radius: 12px; }
    table { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 1050px; font-size: 13px; }
    th { position: sticky; top: 0; z-index: 2; color: #b8cbe0; background: #10233a; text-align: right; }
    th:first-child, td:first-child { position: sticky; left: 0; text-align: left; background: #0d1b2d; z-index: 1; }
    th:first-child { z-index: 4; background: #10233a; }
    #warehouseTable thead tr:first-child th { top: 0; z-index: 3; }
    #warehouseTable thead tr:nth-child(2) th { top: 39px; z-index: 2; }
    #warehouseTable thead tr:nth-child(2) th:first-child { left: auto; text-align: right; z-index: 2; }
    #warehouseTable thead tr:first-child th:first-child { z-index: 5; }
    #warehouseTable .warehouse-start { border-left: 2px solid #49647f; }
    #dataTable .group-start { border-left: 2px solid #49647f; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
    tbody tr:hover { background: rgba(49,215,197,.055); }
    footer { color: var(--muted); text-align: center; font-size: 12px; margin-top: 22px; }
    @media (max-width: 900px) {
      header { align-items: flex-start; flex-direction: column; }
      .cards { grid-template-columns: repeat(2, 1fr); }
      .chart-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 520px) {
      .shell { width: min(100% - 20px, 1440px); padding-top: 22px; }
      .cards { grid-template-columns: 1fr; }
      .switch { width: 100%; } .switch button { flex: 1; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <div class="eyebrow">GFEX · PGM RESEARCH</div>
        <h1>广期所铂/钯库存</h1>
        <p class="subtitle">国内铂族金属仓单结构与日度变化</p>
      </div>
        <div class="header-actions">
        <nav class="switch" aria-label="切换品种">
          <button type="button" data-metal="PT" class="active">PT 铂</button>
          <button type="button" data-metal="PD">PD 钯</button>
        </nav>
      </div>
    </header>

    <section class="cards" id="cards"></section>

    <section class="chart-grid">
      <article class="panel">
        <div class="panel-head"><h2>库存趋势</h2><span class="period" id="period"></span></div>
        <div id="trend"></div>
      </article>
      <article class="panel">
        <div class="panel-head">
          <h2>月内季节图</h2>
          <div class="metric-switch" aria-label="切换季节图指标">
            <button type="button" data-metric="仓单量" class="active">总仓单</button>
            <button type="button" data-metric="仓库仓单量">仓库仓单</button>
            <button type="button" data-metric="厂库仓单量">厂库仓单</button>
          </div>
        </div>
        <div id="seasonal"></div>
      </article>
    </section>

    <section class="panel table-panel">
      <div class="panel-head"><h2>各库存变化详情</h2><span class="period" id="warehousePeriod"></span></div>
      <div class="table-wrap"><table id="warehouseTable"></table></div>
    </section>

    <section class="panel table-panel">
      <div class="panel-head"><h2>库存分析明细</h2><span class="period">单位：千克</span></div>
      <div class="table-wrap"><table id="dataTable"></table></div>
    </section>
    <footer>Data source: Guangzhou Futures Exchange</footer>
  </main>

  <script>
    const DATA = __PGM_DATA__;
    const columns = ["日期","仓单量","仓单变化量","仓单累计变化量","仓库仓单量","仓库仓单变化量","仓库仓单累计变化量","厂库仓单量","厂库仓单变化量","厂库仓单累计变化量"];
    const fmt = value => value == null || Number.isNaN(+value) ? "—" : Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 0});
    const signed = value => value == null || Number.isNaN(+value) ? "—" : `${+value > 0 ? "+" : ""}${fmt(value)}`;
    const cls = value => +value > 0 ? "positive" : (+value < 0 ? "negative" : "");
    const plotConfig = {responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d","select2d"]};
    const layoutBase = {
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: {color: "#b9cbe0", family: "Inter, Segoe UI, Microsoft YaHei"},
      margin: {l: 56, r: 18, t: 20, b: 48},
      xaxis: {gridcolor: "#20364e", zerolinecolor: "#20364e"},
      yaxis: {gridcolor: "#20364e", zerolinecolor: "#20364e", tickformat: ","},
      hovermode: "x unified", legend: {orientation: "h", y: 1.12}
    };

    let currentMetal = "PT";
    let currentMetric = "仓单量";

    function renderSeasonal(metal, metric) {
      const rows = DATA[metal].analysis;
      const grouped = {};
      rows.forEach(row => {
        const date = new Date(`${row["日期"]}T00:00:00`);
        const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
        (grouped[key] ||= []).push({day: date.getDate(), value: row[metric]});
      });
      const palette = ["#31d7c5", "#65a7ff", "#f0bd63", "#c68cff", "#ff7285", "#7bd88f"];
      const traces = Object.entries(grouped).map(([month, points], index) => ({
        x: points.map(p => p.day), y: points.map(p => p.value), name: month,
        mode: "lines+markers", line: {width: 2, color: palette[index % palette.length]},
        marker: {size: 5}, hovertemplate: `${month}-%{x}<br>${metric} %{y:,.0f}<extra></extra>`
      }));
      Plotly.purge("seasonal");
      Plotly.newPlot("seasonal", traces, {
        ...layoutBase, hovermode: "closest",
        xaxis: {...layoutBase.xaxis, title: "日", dtick: 1, range: [1, 31]},
        yaxis: {...layoutBase.yaxis, title: metric}
      }, plotConfig);
    }

    function render(metal) {
      currentMetal = metal;
      const payload = DATA[metal];
      const rows = payload.analysis.slice().sort((a, b) => a["日期"].localeCompare(b["日期"]));
      const latest = rows[rows.length - 1];
      document.querySelectorAll("[data-metal]").forEach(button => button.classList.toggle("active", button.dataset.metal === metal));
      document.getElementById("period").textContent = `${rows[0]["日期"]} — ${payload.latestDate}`;
      document.getElementById("warehousePeriod").textContent = `${payload.previousDate} → ${payload.latestDate}`;

      const cards = [
        ["总仓单", "仓单量", "仓单变化量"],
        ["仓库仓单", "仓库仓单量", "仓库仓单变化量"],
        ["厂库仓单", "厂库仓单量", "厂库仓单变化量"],
        ["月累计变化", "仓单累计变化量", "仓单累计变化量"]
      ];
      document.getElementById("cards").innerHTML = cards.map(([label, valueKey, deltaKey], i) => {
        const delta = latest[deltaKey];
        return `<article class="card"><div class="label">${label}</div><div class="value">${fmt(latest[valueKey])}</div><div class="delta ${cls(delta)}">${i === 3 ? "本月 " : "日变动 "}${signed(delta)}</div></article>`;
      }).join("");

      Plotly.purge("trend");
      Plotly.newPlot("trend", [
        {x: rows.map(r => r["日期"]), y: rows.map(r => r["仓单量"]), name: "仓单总量", mode: "lines", line: {color: "#31d7c5", width: 3}},
        {x: rows.map(r => r["日期"]), y: rows.map(r => r["仓库仓单量"]), name: "仓库仓单", mode: "lines", line: {color: "#65a7ff", width: 2}},
        {x: rows.map(r => r["日期"]), y: rows.map(r => r["厂库仓单量"]), name: "厂库仓单", mode: "lines", line: {color: "#f0bd63", width: 2}}
      ], {...layoutBase, xaxis: {...layoutBase.xaxis, rangeslider: {visible: true, thickness: .08}}}, plotConfig);

      renderSeasonal(metal, currentMetric);

      const warehouseRows = payload.warehouseHistory.slice().sort((a,b) => b.date.localeCompare(a.date));
      const warehouseColumns = payload.warehouseColumns;
      document.getElementById("warehouseTable").innerHTML =
        `<thead><tr><th rowspan="2">日期</th>${warehouseColumns.map(name => `<th colspan="2" class="warehouse-start">${name}</th>`).join("")}</tr>` +
        `<tr>${warehouseColumns.map(() => `<th class="warehouse-start">库存</th><th>变化</th>`).join("")}</tr></thead>` +
        `<tbody>${warehouseRows.map(row => `<tr><td>${row.date}</td>${warehouseColumns.map(name => { const item = row.warehouses[name]; return `<td class="warehouse-start">${item ? fmt(item.inventory) : "—"}</td><td class="${item ? cls(item.change) : ""}">${item ? signed(item.change) : "—"}</td>`; }).join("")}</tr>`).join("")}</tbody>`;

      document.getElementById("dataTable").innerHTML =
        `<thead><tr>${columns.map((c, i) => `<th class="${[1,4,7].includes(i) ? "group-start" : ""}">${c}</th>`).join("")}</tr></thead>` +
        `<tbody>${rows.slice().reverse().map(row => `<tr>${columns.map((c, i) => `<td class="${[1,4,7].includes(i) ? "group-start " : ""}${c === "日期" ? "" : cls(row[c])}">${c === "日期" ? row[c] : fmt(row[c])}</td>`).join("")}</tr>`).join("")}</tbody>`;
    }

    document.querySelectorAll("[data-metal]").forEach(button => button.addEventListener("click", () => render(button.dataset.metal)));
    document.querySelectorAll("[data-metric]").forEach(button => button.addEventListener("click", () => {
      currentMetric = button.dataset.metric;
      document.querySelectorAll("[data-metric]").forEach(item => item.classList.toggle("active", item === button));
      renderSeasonal(currentMetal, currentMetric);
    }));
    render("PT");
  </script>
</body>
</html>
"""
