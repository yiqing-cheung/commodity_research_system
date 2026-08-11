from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUNCE_TO_TONNE = 31.1035 / 1_000_000


class NYMEXSpreadHTMLGenerator:
    """Generate the interactive NYMEX platinum calendar-spread page."""

    def __init__(
        self,
        spread_csv="data/PL_main_next_quarter_spread.csv",
        inventory_csv="data/pgm_receipt_nymex.csv",
    ):
        self.spread_csv = Path(spread_csv)
        self.inventory_csv = Path(inventory_csv)

    def _spread_records(self):
        frame = pd.read_csv(self.spread_csv)
        required = [
            "datetime", "main_contract", "main_close", "next_contract",
            "next_close", "spread_main_minus_next",
        ]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Spread CSV missing columns: {', '.join(missing)}")
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        for column in ["main_close", "next_close", "spread_main_minus_next"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(
            subset=["datetime", "main_close", "next_close", "spread_main_minus_next"]
        ).sort_values("datetime").drop_duplicates("datetime", keep="last")
        return [
            {
                "date": row.datetime.strftime("%Y-%m-%d"),
                "mainContract": row.main_contract,
                "mainClose": float(row.main_close),
                "nextContract": row.next_contract,
                "nextClose": float(row.next_close),
                "spread": float(row.spread_main_minus_next),
            }
            for row in frame.itertuples(index=False)
        ]

    def _inventory_records(self):
        frame = pd.read_csv(self.inventory_csv)
        required = ["date", "pt_total_oz", "pt_registered_oz"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Inventory CSV missing columns: {', '.join(missing)}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["pt_total_oz"] = pd.to_numeric(frame["pt_total_oz"], errors="coerce")
        frame["pt_registered_oz"] = pd.to_numeric(
            frame["pt_registered_oz"], errors="coerce"
        )
        frame = frame.dropna(subset=["date"]).sort_values("date")
        frame = frame.drop_duplicates("date", keep="last")
        return [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "inventory": None if pd.isna(row.pt_total_oz) else round(
                    float(row.pt_total_oz) * OUNCE_TO_TONNE, 9
                ),
                "registered": None if pd.isna(row.pt_registered_oz) else round(
                    float(row.pt_registered_oz) * OUNCE_TO_TONNE, 9
                ),
            }
            for row in frame.itertuples(index=False)
        ]

    def generate(self, output_file="site/pgm/nymex_spread.html"):
        payload = {
            "spread": self._spread_records(),
            "inventory": self._inventory_records(),
        }
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        html = _HTML_TEMPLATE.replace("__SPREAD_DATA__", encoded.replace("</", "<\\/"))
        output.write_text(html, encoding="utf-8")
        print(f"NYMEX spread dashboard saved: {output.resolve()}")
        return output


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="NYMEX铂金主力与下一季度合约月差分析"><title>NYMEX Platinum Spread</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><style>
:root{--bg:#07111f;--panel:#0d1b2d;--text:#edf6ff;--muted:#89a0b8;--line:#213852;--cyan:#31d7c5;--gold:#f0bd63;--blue:#65a7ff;--red:#ff7285;--green:#46d29a}*{box-sizing:border-box}body{margin:0;color:var(--text);background:radial-gradient(circle at 8% 0%,#12314b 0,transparent 32%),radial-gradient(circle at 100% 10%,#232746 0,transparent 30%),var(--bg);font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}.shell{width:min(1480px,calc(100% - 32px));margin:auto;padding:30px 0 56px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:18px}.eyebrow{color:var(--cyan);letter-spacing:.16em;font-size:12px;font-weight:700}h1{font-size:clamp(28px,5vw,50px);margin:7px 0 5px;letter-spacing:-.04em}.subtitle,.period{color:var(--muted)}.subtitle{margin:0}.nav{display:flex;gap:9px;flex-wrap:wrap}.nav a{color:var(--cyan);text-decoration:none;border:1px solid var(--line);padding:10px 13px;border-radius:10px;background:#081625}.panel,.card{background:linear-gradient(145deg,rgba(17,38,61,.94),rgba(10,25,42,.96));border:1px solid var(--line);box-shadow:0 18px 50px rgba(0,0,0,.16)}.panel{border-radius:18px;padding:18px;min-width:0}.filter{display:flex;gap:11px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted)}input{color:var(--text);color-scheme:dark;background:#081625;border:1px solid var(--line);padding:9px 11px;border-radius:9px;font:inherit}input[type=number]{width:135px}.btn{border:0;background:var(--cyan);color:#04131c;padding:10px 15px;border-radius:9px;cursor:pointer;font:inherit;font-weight:700}.btn.secondary{background:#132b45;color:var(--text);border:1px solid var(--line)}.status{margin-left:auto;color:var(--muted);font-size:12px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px}.card{padding:16px;border-radius:16px}.label{color:var(--muted);font-size:13px}.value{font-size:clamp(22px,3vw,34px);font-weight:760;margin:7px 0 2px}.delta{color:var(--muted);font-size:12px}.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.chart{height:420px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:4px}.panel h2{font-size:16px;margin:0}.section-title{font-size:13px;color:var(--cyan);letter-spacing:.12em;margin:24px 0 9px}.positive{color:var(--green)}.negative{color:var(--red)}footer{text-align:center;color:var(--muted);font-size:12px;margin-top:20px}@media(max-width:950px){header{align-items:flex-start;flex-direction:column}.cards,.charts{grid-template-columns:1fr 1fr}.status{width:100%;margin-left:0}}@media(max-width:620px){.shell{width:calc(100% - 20px);padding-top:20px}.cards,.charts{grid-template-columns:1fr}.chart{height:360px}}
</style></head><body><main class="shell"><header><div><div class="eyebrow">NYMEX · PLATINUM CURVE</div><h1>NYMEX月差分析</h1><p class="subtitle">主力合约与下一季度合约的期限结构、持仓成本及库存验证</p></div><nav class="nav"><a href="nymex.html">← 海外库存</a><a href="index.html">中国库存</a></nav></header>
<div class="section-title">月差季节性与库存</div><section class="panel filter"><div class="field"><label>开始日期</label><input id="seasonStart" type="date"></div><div class="field"><label>结束日期</label><input id="seasonEnd" type="date"></div><button id="seasonApply" class="btn">应用筛选</button><button id="seasonReset" class="btn secondary">全部历史</button><span id="seasonStatus" class="status"></span></section>
<section class="charts"><article class="panel"><div class="panel-head"><h2>NYMEX PL月差季节图</h2><span class="period">美元/盎司</span></div><div id="spreadSeasonal" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>NYMEX铂金库存季节图</h2><span class="period">吨</span></div><div id="inventorySeasonal" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>月差说明</h2></div><div style="padding:12px 5px;color:var(--muted);line-height:1.85"><ul style="margin:0;padding-left:20px"><li>NYMEX铂金期货按月挂牌。我们比较每日各月份合约的成交量，以成交量最大的合约作为主力；历史上主力主要集中在1月、4月、7月和10月合约。用于月差比较的下一合约取主力月份之后3个月的合约。</li><li>月差定义为“主力合约结算价－下一合约结算价”。正值表示近端价格高于远端，负值表示远端价格高于近端。</li><li>结算价不是简单的最后成交价。CME对活跃月份主要依据美东时间13:03–13:05结算时段内成交的成交量加权平均价（VWAP）确定；其他月份使用美东时间12:35–13:05的日历价差结算时段。</li><li>具体推导分为三个层级：首先使用结算时段内日历价差成交的VWAP，并与已确定月份的结算价组合计算。例如10月结算价为2,000美元/盎司、10月－次年1月价差VWAP为−18美元/盎司，则1月结算价推导为2,000−(−18)=2,018美元/盎司。若没有相关价差成交，则使用日历价差买卖报价构造远月合约的隐含买卖区间，并在合理区间内确定结算价；若仍没有符合合理性标准的隐含报价，则参考前一合约月份的净价格变动确定。</li></ul></div></article><article class="panel"><div class="panel-head"><h2>NYMEX铂金注册仓单季节图</h2><span class="period">吨</span></div><div id="registeredSeasonal" class="chart"></div></article></section>
<div class="section-title">月差时序与持仓成本</div><section class="panel filter"><div class="field"><label>开始日期</label><input id="trendStart" type="date"></div><div class="field"><label>结束日期</label><input id="trendEnd" type="date"></div><div class="field"><label>资金利率（%）</label><input id="interestRate" type="number" min="0" step="0.1" value="3.5"></div><div class="field"><label>仓储费（美元/手/月）</label><input id="storageFee" type="number" min="0" step="0.5" value="20"></div><button id="trendApply" class="btn">应用参数</button><button id="trendReset" class="btn secondary">恢复默认</button><span id="trendStatus" class="status"></span></section>
<section class="cards" id="cards"></section><article class="panel"><div class="panel-head"><h2>月差与负持仓成本时序</h2><span class="period">美元/盎司</span></div><div id="spreadTrend" class="chart"></div><div class="period">持仓成本 = 主力价格 × 资金利率 × 3/12 + 仓储费 ÷ 50 × 3；图中绘制其负值。</div></article><footer>数据来源：CME Group NYMEX</footer></main>
<script>const DATA=__SPREAD_DATA__,S=DATA.spread,I=DATA.inventory,$=id=>document.getElementById(id),cfg={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};const base={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#b8cbe0',family:'Inter,"Microsoft YaHei",sans-serif'},margin:{l:62,r:20,t:18,b:48},hovermode:'x unified',legend:{orientation:'h',y:1.08},xaxis:{gridcolor:'#17304a',zeroline:false},yaxis:{gridcolor:'#17304a',zeroline:false}};const colors=['#31d7c5','#f0bd63','#65a7ff','#ff7285','#aa87ff','#46d29a','#ec8ed0','#a7c957'];const valid=n=>n!==null&&Number.isFinite(Number(n));const fmt=(n,d=2)=>valid(n)?Number(n).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';function between(rows,a,b){return rows.filter(x=>x.date>=a&&x.date<=b)}function seasonal(div,rows,field,digits=2){const years=[...new Set(rows.map(x=>x.date.slice(0,4)))].sort();const traces=years.map((year,i)=>{const r=rows.filter(x=>x.date.startsWith(year)&&valid(x[field]));return{x:r.map(x=>'2000-'+x.date.slice(5)),y:r.map(x=>x[field]),name:year,mode:'lines',line:{width:year===years.at(-1)?3:1.7,color:colors[i%colors.length]},hovertemplate:`${year}　%{y:.${digits}f}<extra></extra>`}});Plotly.react(div,traces,{...base,xaxis:{...base.xaxis,tickformat:'%m-%d',hoverformat:'%m-%d'},yaxis:{...base.yaxis}},cfg)}function renderSeason(){const a=$('seasonStart').value,b=$('seasonEnd').value,sp=between(S,a,b),inv=between(I,a,b);seasonal('spreadSeasonal',sp,'spread',1);seasonal('inventorySeasonal',inv,'inventory',3);seasonal('registeredSeasonal',inv,'registered',3);$('seasonStatus').textContent=`月差 ${sp.length.toLocaleString('zh-CN')} 条 · 库存 ${inv.length.toLocaleString('zh-CN')} 条`}function holding(row){const rate=Number($('interestRate').value||0)/100,storage=Number($('storageFee').value||0);return row.mainClose*rate*3/12+storage/50*3}function renderTrend(){const a=$('trendStart').value,b=$('trendEnd').value,rows=between(S,a,b),cost=rows.map(holding),latest=rows.at(-1),latestCost=latest?holding(latest):null;Plotly.react('spreadTrend',[{x:rows.map(x=>x.date),y:rows.map(x=>x.spread),name:'月差（主力－下一合约）',mode:'lines',line:{color:'#31d7c5',width:2.4},hovertemplate:'月差　%{y:.2f}<extra></extra>'},{x:rows.map(x=>x.date),y:cost.map(x=>-x),name:'-持仓成本',mode:'lines',line:{color:'#f0bd63',width:2,dash:'dot'},hovertemplate:'-持仓成本　%{y:.2f}<extra></extra>'}],{...base,xaxis:{...base.xaxis,rangeslider:{visible:true,thickness:.08}},yaxis:{...base.yaxis}},cfg);const deviation=latest&&latestCost!==null?latest.spread+latestCost:null;$('cards').innerHTML=[['最新月差',fmt(latest?.spread,1),'美元/盎司'],['最新负持仓成本',latestCost===null?'—':fmt(-latestCost,1),'美元/盎司'],['月差－负成本线',fmt(deviation,1),'美元/盎司'],['最新合约',latest?`${latest.mainContract} / ${latest.nextContract}`:'—',latest?.date||'—']].map(x=>`<article class="card"><div class="label">${x[0]}</div><div class="value">${x[1]}</div><div class="delta">${x[2]}</div></article>`).join('');$('trendStatus').textContent=`${rows.length.toLocaleString('zh-CN')} 条 · 利率 ${fmt(Number($('interestRate').value),1)}% · 仓储费 ${fmt(Number($('storageFee').value),1)}`}const first=S[0].date,last=S.at(-1).date,def=first>'2021-01-01'?first:'2021-01-01';for(const id of ['seasonStart','trendStart']){$(id).min=first;$(id).max=last;$(id).value=def}for(const id of ['seasonEnd','trendEnd']){$(id).min=first;$(id).max=last;$(id).value=last}$('seasonApply').onclick=()=>renderSeason();$('seasonReset').onclick=()=>{$('seasonStart').value=first;$('seasonEnd').value=last;renderSeason()};$('trendApply').onclick=()=>renderTrend();$('trendReset').onclick=()=>{$('trendStart').value=def;$('trendEnd').value=last;$('interestRate').value=3.5;$('storageFee').value=20;renderTrend()};renderSeason();renderTrend();</script></body></html>'''


if __name__ == "__main__":
    NYMEXSpreadHTMLGenerator().generate()
