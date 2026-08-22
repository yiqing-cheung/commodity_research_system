from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUNCE_TO_TONNE = 31.1035 / 1_000_000


class NYMEXHTMLDashboardGenerator:
    """Generate a self-contained interactive NYMEX PGM inventory page."""

    REQUIRED_COLUMNS = (
        "date",
        "pd_total_oz",
        "pt_total_oz",
        "pd_registered_oz",
        "pt_registered_oz",
        "pd_delivery_contracts",
        "pt_delivery_contracts",
    )

    def __init__(self, csv_file="data/pgm_receipt_nymex.csv"):
        self.csv_file = Path(csv_file)

    def _load(self):
        frame = pd.read_csv(self.csv_file)
        missing = [c for c in self.REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"NYMEX CSV missing columns: {', '.join(missing)}")

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
        frame = frame.drop_duplicates(subset=["date"], keep="last")
        numeric = [c for c in self.REQUIRED_COLUMNS if c != "date"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")

        records = []
        for row in frame.itertuples(index=False):
            def tonne(value):
                return None if pd.isna(value) else round(float(value) * OUNCE_TO_TONNE, 9)

            def number(value):
                return None if pd.isna(value) else float(value)

            def delivery_kg(value, ounces_per_contract):
                contracts = number(value)
                return None if contracts is None else round(
                    contracts * ounces_per_contract * 31.1035 / 1000, 6
                )

            records.append({
                "date": row.date.strftime("%Y-%m-%d"),
                "ptTotal": tonne(row.pt_total_oz),
                "ptRegistered": tonne(row.pt_registered_oz),
                "pdTotal": tonne(row.pd_total_oz),
                "pdRegistered": tonne(row.pd_registered_oz),
                "ptDelivery": delivery_kg(row.pt_delivery_contracts, 50),
                "pdDelivery": delivery_kg(row.pd_delivery_contracts, 100),
            })
        if not records:
            raise ValueError(f"NYMEX CSV has no valid records: {self.csv_file}")
        return records

    def generate(self, output_file="site/pgm/nymex.html"):
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        data_json = json.dumps(self._load(), ensure_ascii=False, separators=(",", ":"))
        html = _HTML_TEMPLATE.replace("__NYMEX_DATA__", data_json.replace("</", "<\\/"))
        output_file.write_text(html, encoding="utf-8")
        print(f"NYMEX HTML dashboard saved: {output_file.resolve()}")
        return output_file


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="NYMEX铂钯库存与注册仓单交互研究页面">
  <title>NYMEX PGM Inventory</title>
  <script src="assets/vendor/plotly-2.35.2.min.js"></script>
  <style>
    :root{--bg:#07111f;--panel:#0d1b2d;--panel2:#10233a;--text:#edf6ff;--muted:#89a0b8;--line:#213852;--cyan:#31d7c5;--gold:#f0bd63;--blue:#65a7ff;--green:#46d29a;--red:#ff7285}
    *{box-sizing:border-box}body{margin:0;color:var(--text);background:radial-gradient(circle at 8% 0%,#12314b 0,transparent 32%),radial-gradient(circle at 100% 10%,#232746 0,transparent 30%),var(--bg);font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}
    .shell{width:min(1480px,calc(100% - 32px));margin:auto;padding:30px 0 56px}header{display:flex;justify-content:space-between;gap:22px;align-items:flex-end;margin-bottom:20px}.eyebrow{color:var(--cyan);letter-spacing:.16em;font-size:12px;font-weight:700}h1{font-size:clamp(28px,5vw,50px);margin:7px 0 5px;letter-spacing:-.04em}.subtitle,.muted{color:var(--muted)}.subtitle{margin:0}.top-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.back{color:var(--cyan);text-decoration:none;border:1px solid var(--line);padding:10px 14px;border-radius:10px;background:#081625}.switch{display:flex;padding:4px;border:1px solid var(--line);border-radius:12px;background:#081625}.switch button,.btn{border:0;color:var(--muted);background:transparent;padding:10px 18px;border-radius:9px;cursor:pointer;font:inherit;font-weight:700}.switch button.active{color:#04131c;background:var(--cyan)}
    .filter{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;padding:16px;margin-bottom:14px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted)}input[type=date]{color:var(--text);color-scheme:dark;background:#081625;border:1px solid var(--line);padding:9px 11px;border-radius:9px;font:inherit}.btn{background:var(--cyan);color:#04131c}.btn.secondary{background:#132b45;color:var(--text);border:1px solid var(--line)}.status{margin-left:auto;color:var(--muted);font-size:12px}
    .panel,.card{background:linear-gradient(145deg,rgba(17,38,61,.94),rgba(10,25,42,.96));border:1px solid var(--line);box-shadow:0 18px 50px rgba(0,0,0,.16)}.panel{border-radius:18px;padding:18px;min-width:0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px}.card{padding:17px;border-radius:16px}.label{color:var(--muted);font-size:13px}.value{font-size:clamp(24px,3vw,36px);font-weight:760;margin:7px 0 2px}.delta{font-size:13px;color:var(--muted)}.positive{color:var(--green)}.negative{color:var(--red)}.mini-switch{display:flex;gap:5px}.mini-switch button{border:1px solid var(--line);background:#081625;color:var(--muted);padding:6px 10px;border-radius:8px;cursor:pointer}.mini-switch button.active{background:var(--gold);border-color:var(--gold);color:#07111f}
    .charts{display:grid;grid-template-columns:1fr 1fr;gap:14px}.wide{grid-column:1/-1}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:5px}.panel h2{font-size:16px;margin:0}.period{color:var(--muted);font-size:12px}.chart{height:410px}.delivery{height:390px}.tables{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.table-wrap{overflow:auto;max-height:610px;border-radius:11px}table{border-collapse:separate;border-spacing:0;width:100%;min-width:830px;font-size:12px}th{position:sticky;top:0;z-index:2;background:#10233a;color:#b8cbe0}th,td{padding:10px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{position:sticky;left:0;background:#0d1b2d;z-index:1;text-align:left}th:first-child{z-index:3;background:#10233a}th:nth-child(2),td:nth-child(2){text-align:left}tbody tr:hover{background:rgba(49,215,197,.055)}.empty{text-align:center!important;color:var(--muted);padding:30px!important}footer{text-align:center;color:var(--muted);font-size:12px;margin-top:20px}
    @media(max-width:980px){header{align-items:flex-start;flex-direction:column}.cards{grid-template-columns:repeat(2,1fr)}.charts,.tables{grid-template-columns:1fr}.wide{grid-column:auto}.status{width:100%;margin-left:0}}@media(max-width:520px){.shell{width:calc(100% - 20px);padding-top:20px}.cards{grid-template-columns:1fr}.switch{width:100%}.switch button{flex:1}.chart{height:360px}}
  </style>
</head>
<body><main class="shell">
  <header><div><div class="eyebrow">NYMEX · PGM RESEARCH</div><h1><span id="metalTitle">铂金</span>海外库存</h1><p class="subtitle">库存、注册仓单、交割量与月末/年末变化</p></div><div class="top-actions"><a class="back" href="index.html">← 中国库存</a><a class="back" href="nymex_spread.html">月差分析 →</a><nav class="switch"><button data-metal="PT" class="active">PT 铂金</button><button data-metal="PD">PD 钯金</button></nav></div></header>
  <section class="panel filter"><div class="field"><label for="startDate">开始日期</label><input id="startDate" type="date"></div><div class="field"><label for="endDate">结束日期</label><input id="endDate" type="date"></div><button class="btn" id="apply">应用筛选</button><button class="btn secondary" id="reset">全部历史</button><span class="status" id="status"></span></section>
  <section class="cards" id="cards"></section>
  <section class="charts"><article class="panel"><div class="panel-head"><h2 id="totalTitle">铂金库存季节图</h2><span class="period">单位：吨</span></div><div id="totalSeasonal" class="chart"></div></article><article class="panel"><div class="panel-head"><h2 id="registeredTitle">铂金注册仓单季节图</h2><span class="period">单位：吨</span></div><div id="registeredSeasonal" class="chart"></div></article><article class="panel wide"><div class="panel-head"><h2>NYMEX 交割量时序图</h2><div class="mini-switch"><button data-delivery="both" class="active">铂钯同时</button><button data-delivery="pt">仅铂金</button><button data-delivery="pd">仅钯金</button></div></div><div id="deliveryTrend" class="delivery"></div><div class="period">2025-10-17起 · 单位：千克 · 铂金1手=50盎司，钯金1手=100盎司</div></article></section>
  <section class="tables"><article class="panel"><div class="panel-head"><h2 id="monthlyTitle">铂金月末库存</h2><span class="period">各月最后可用交易日</span></div><div class="table-wrap"><table><thead><tr><th>月份</th><th>数据日期</th><th>库存(吨)</th><th>变化(吨)</th><th>变化率</th><th>注册仓单(吨)</th><th>变化(吨)</th><th>变化率</th></tr></thead><tbody id="monthlyBody"></tbody></table></div></article><article class="panel"><div class="panel-head"><h2 id="yearlyTitle">铂金年末库存</h2><span class="period">各年最后可用交易日</span></div><div class="table-wrap"><table><thead><tr><th>年份</th><th>数据日期</th><th>库存(吨)</th><th>变化(吨)</th><th>变化率</th><th>注册仓单(吨)</th><th>变化(吨)</th><th>变化率</th></tr></thead><tbody id="yearlyBody"></tbody></table></div></article></section>
  <footer>数据来源：CME Group NYMEX · 月度及年度变化基于相邻期末数据计算</footer>
</main><script>
const ALL=__NYMEX_DATA__;let metal="PT",deliveryMode="both";
const $=id=>document.getElementById(id);const config={responsive:true,displaylogo:false,modeBarButtonsToRemove:["lasso2d","select2d"]};
const layoutBase={paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",font:{color:"#b8cbe0",family:'Inter,"Microsoft YaHei",sans-serif'},margin:{l:58,r:20,t:18,b:45},hovermode:"x unified",legend:{orientation:"h",y:1.08},xaxis:{gridcolor:"#17304a",zeroline:false},yaxis:{gridcolor:"#17304a",zeroline:false,ticksuffix:" 吨"}};
const valid=n=>n!==null&&Number.isFinite(Number(n));const fmt=(n,d=3)=>valid(n)?Number(n).toLocaleString("zh-CN",{minimumFractionDigits:d,maximumFractionDigits:d}):"—";
const changeClass=n=>!valid(n)?"":n>0?"positive":n<0?"negative":"";const signed=n=>!valid(n)?"—":`${n>0?"+":""}${fmt(n)}`;const pct=n=>!valid(n)?"—":`${n>0?"+":""}${fmt(n,1)}%`;
function range(){return {start:$("startDate").value,end:$("endDate").value}}function selected(){const r=range();return ALL.filter(x=>x.date>=r.start&&x.date<=r.end)}
function periodRows(kind){const suffix=metal==="PT"?"pt":"pd",groups=new Map();ALL.forEach(x=>{const key=kind==="month"?x.date.slice(0,7):x.date.slice(0,4);groups.set(key,x)});const rows=[...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0])).map(([period,x])=>({period,date:x.date,total:x[suffix+"Total"],registered:x[suffix+"Registered"]}));rows.forEach((x,i)=>{const p=rows[i-1];x.totalChange=p&&valid(x.total)&&valid(p.total)?x.total-p.total:null;x.totalPct=p&&p.total&&valid(x.total)?x.totalChange/p.total*100:null;x.regChange=p&&valid(x.registered)&&valid(p.registered)?x.registered-p.registered:null;x.regPct=p&&p.registered&&valid(x.registered)?x.regChange/p.registered*100:null});const r=range();return rows.filter(x=>x.date>=r.start&&x.date<=r.end).reverse()}
function renderCards(data){const suffix=metal==="PT"?"pt":"pd",latest=data[data.length-1],latestIndex=latest?ALL.findIndex(x=>x.date===latest.date):-1,previous=latestIndex>0?ALL[latestIndex-1]:null,monthly=periodRows("month"),month=monthly[0];const total=latest?.[suffix+"Total"],previousTotal=previous?.[suffix+"Total"],reg=latest?.[suffix+"Registered"],previousReg=previous?.[suffix+"Registered"],eligible=valid(total)&&valid(reg)?total-reg:null,previousEligible=valid(previousTotal)&&valid(previousReg)?previousTotal-previousReg:null,totalDaily=valid(total)&&valid(previousTotal)?total-previousTotal:null,regDaily=valid(reg)&&valid(previousReg)?reg-previousReg:null,eligibleDaily=valid(eligible)&&valid(previousEligible)?eligible-previousEligible:null;$("cards").innerHTML=[['最新库存',fmt(total)+' 吨','日变动 '+signed(totalDaily)+' 吨',changeClass(totalDaily)],['注册仓单',fmt(reg)+' 吨','日变动 '+signed(regDaily)+' 吨',changeClass(regDaily)],['非注册仓单',fmt(eligible)+' 吨','日变动 '+signed(eligibleDaily)+' 吨',changeClass(eligibleDaily)],['月度库存变化',signed(month?.totalChange)+' 吨',pct(month?.totalPct),changeClass(month?.totalChange)]].map(x=>`<article class="card"><div class="label">${x[0]}</div><div class="value">${x[1]}</div><div class="delta ${x[3]}">${x[2]}</div></article>`).join('')}
function seasonal(div,data,field){const years=[...new Set(data.map(x=>x.date.slice(0,4)))].sort();const colors=['#31d7c5','#f0bd63','#65a7ff','#ff7285','#aa87ff','#46d29a','#ec8ed0','#a7c957'];const traces=years.map((y,i)=>{const a=data.filter(x=>x.date.startsWith(y)&&valid(x[field]));return {x:a.map(x=>'2000-'+x.date.slice(5)),y:a.map(x=>x[field]),name:y,mode:'lines',line:{width:y===years.at(-1)?3:1.7,color:colors[i%colors.length]},hovertemplate:`${y}　%{y:.3f} 吨<extra></extra>`}});Plotly.react(div,traces,{...layoutBase,xaxis:{...layoutBase.xaxis,tickformat:'%m-%d',hoverformat:'%m-%d'}},config)}
function renderDelivery(data){const deliveryData=data.filter(x=>x.date>='2025-10-17');const defs=[['pt','ptDelivery','铂金交割量','#31d7c5'],['pd','pdDelivery','钯金交割量','#f0bd63']].filter(x=>deliveryMode==='both'||deliveryMode===x[0]);const traces=defs.map(([,field,name,color])=>({x:deliveryData.map(x=>x.date),y:deliveryData.map(x=>x[field]),name,mode:'lines',line:{color,width:2.2},hovertemplate:name+'　%{y:,.3f} 千克<extra></extra>'}));Plotly.react('deliveryTrend',traces,{...layoutBase,xaxis:{...layoutBase.xaxis,rangeslider:{visible:true,thickness:.08}},yaxis:{...layoutBase.yaxis,ticksuffix:' 千克'}},config)}
function renderTable(id,rows){$(id).innerHTML=rows.length?rows.map(x=>`<tr><td>${x.period}</td><td>${x.date}</td><td>${fmt(x.total)}</td><td class="${changeClass(x.totalChange)}">${signed(x.totalChange)}</td><td class="${changeClass(x.totalPct)}">${pct(x.totalPct)}</td><td>${fmt(x.registered)}</td><td class="${changeClass(x.regChange)}">${signed(x.regChange)}</td><td class="${changeClass(x.regPct)}">${pct(x.regPct)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">所选区间没有期末数据</td></tr>'}
function render(){const data=selected(),cn=metal==="PT"?"铂金":"钯金",suffix=metal==="PT"?"pt":"pd";$("metalTitle").textContent=cn;$("totalTitle").textContent=cn+'库存季节图';$("registeredTitle").textContent=cn+'注册仓单季节图';$("monthlyTitle").textContent=cn+'月末库存';$("yearlyTitle").textContent=cn+'年末库存';$("status").textContent=`显示 ${data.length.toLocaleString('zh-CN')} 条记录 · ${range().start} 至 ${range().end}`;renderCards(data);seasonal('totalSeasonal',data,suffix+'Total');seasonal('registeredSeasonal',data,suffix+'Registered');renderDelivery(data);renderTable('monthlyBody',periodRows('month'));renderTable('yearlyBody',periodRows('year'))}
const first=ALL[0].date,last=ALL.at(-1).date,defaultStart=first>'2021-01-01'?first:'2021-01-01';['startDate','endDate'].forEach(id=>{$(id).min=first;$(id).max=last});$("startDate").value=defaultStart;$("endDate").value=last;
document.querySelectorAll('[data-metal]').forEach(b=>b.onclick=()=>{metal=b.dataset.metal;document.querySelectorAll('[data-metal]').forEach(x=>x.classList.toggle('active',x===b));render()});document.querySelectorAll('[data-delivery]').forEach(b=>b.onclick=()=>{deliveryMode=b.dataset.delivery;document.querySelectorAll('[data-delivery]').forEach(x=>x.classList.toggle('active',x===b));renderDelivery(selected())});$("apply").onclick=()=>{if(range().start>range().end){alert('开始日期不能晚于结束日期');return}render()};$("reset").onclick=()=>{$("startDate").value=first;$("endDate").value=last;render()};render();
</script></body></html>'''


if __name__ == "__main__":
    NYMEXHTMLDashboardGenerator().generate()
