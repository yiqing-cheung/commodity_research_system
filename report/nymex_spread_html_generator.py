from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


OUNCE_TO_TONNE = 31.1035 / 1_000_000
MONTH_CODE = {"F": 1, "J": 4, "N": 7, "V": 10}
PRICE_SOURCE_CUTOFF = "2026-07-31"


def _delivery_month(contract):
    match = re.search(r"_([FJNV])", str(contract).upper())
    return MONTH_CODE.get(match.group(1)) if match else None


class NYMEXSpreadHTMLGenerator:
    """Generate the interactive NYMEX platinum calendar-spread page."""

    def __init__(self, spread_csv="data/PL_main_next_quarter_spread.csv", inventory_csv="data/pgm_receipt_nymex.csv"):
        self.spread_csv = Path(spread_csv)
        self.inventory_csv = Path(inventory_csv)

    def _spread_records(self):
        frame = pd.read_csv(self.spread_csv)
        required = ["datetime", "main_contract", "main_close", "next_contract", "next_close", "spread_main_minus_next"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Spread CSV missing columns: {', '.join(missing)}")
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        for column in ["main_close", "next_close", "spread_main_minus_next"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["datetime", "main_close", "next_close", "spread_main_minus_next"]).sort_values("datetime").drop_duplicates("datetime", keep="last")
        records, previous_main = [], None
        for row in frame.itertuples(index=False):
            main_month, next_month = _delivery_month(row.main_contract), _delivery_month(row.next_contract)
            if main_month is None or next_month is None:
                continue
            date = row.datetime.strftime("%Y-%m-%d")
            records.append({
                "date": date, "mainContract": str(row.main_contract), "mainPrice": round(float(row.main_close), 6),
                "nextContract": str(row.next_contract), "nextPrice": round(float(row.next_close), 6),
                "spread": round(float(row.spread_main_minus_next), 6), "monthGap": (next_month-main_month) % 12,
                "pair": f"{main_month:02d}{next_month:02d}", "roll": previous_main is not None and str(row.main_contract) != previous_main,
                "priceType": "结算价" if date >= PRICE_SOURCE_CUTOFF else "收盘价",
            })
            previous_main = str(row.main_contract)
        return records

    def _inventory_records(self):
        frame = pd.read_csv(self.inventory_csv)
        required = ["date", "pt_total_oz", "pt_registered_oz"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Inventory CSV missing columns: {', '.join(missing)}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ["pt_total_oz", "pt_registered_oz", "pt_delivery_contracts"]:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
        records = []
        for row in frame.itertuples(index=False):
            total = None if pd.isna(row.pt_total_oz) else float(row.pt_total_oz)
            registered = None if pd.isna(row.pt_registered_oz) else float(row.pt_registered_oz)
            eligible = None if total is None or registered is None else total-registered
            delivery = getattr(row, "pt_delivery_contracts", None)
            records.append({
                "date": row.date.strftime("%Y-%m-%d"),
                "total": None if total is None else round(total*OUNCE_TO_TONNE, 9),
                "registered": None if registered is None else round(registered*OUNCE_TO_TONNE, 9),
                "eligible": None if eligible is None else round(eligible*OUNCE_TO_TONNE, 9),
                "delivery": None if delivery is None or pd.isna(delivery) else int(delivery),
            })
        return records

    def generate(self, output_file="site/pgm/nymex_spread.html"):
        payload = {"spread": self._spread_records(), "inventory": self._inventory_records(), "priceSourceCutoff": PRICE_SOURCE_CUTOFF}
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        output.write_text(_HTML_TEMPLATE.replace("__SPREAD_DATA__", encoded.replace("</", "<\/")), encoding="utf-8")
        print(f"NYMEX spread dashboard saved: {output.resolve()}")
        return output


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="NYMEX铂金月差、库存、持仓成本及Borrow收益分析"><title>NYMEX Platinum Spread</title>
<script src="assets/vendor/plotly-2.35.2.min.js"></script><style>
:root{--bg:#07111f;--panel:#0d1b2d;--text:#edf6ff;--muted:#89a0b8;--line:#213852;--cyan:#31d7c5;--gold:#f0bd63;--blue:#65a7ff;--red:#ff7285}*{box-sizing:border-box}body{margin:0;color:var(--text);background:radial-gradient(circle at 8% 0%,#12314b 0,transparent 32%),radial-gradient(circle at 100% 10%,#232746 0,transparent 30%),var(--bg);font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}.shell{width:min(1880px,calc(100% - 32px));margin:auto;padding:30px 0 56px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:18px}.eyebrow{color:var(--cyan);letter-spacing:.16em;font-size:12px;font-weight:700}h1{font-size:clamp(28px,5vw,50px);margin:7px 0 5px;letter-spacing:-.04em}.subtitle,.period,.status{color:var(--muted)}.subtitle{margin:0}.nav{display:flex;gap:9px;flex-wrap:wrap}.nav a{color:var(--cyan);text-decoration:none;border:1px solid var(--line);padding:10px 13px;border-radius:10px;background:#081625}.panel{background:linear-gradient(145deg,rgba(17,38,61,.94),rgba(10,25,42,.96));border:1px solid var(--line);box-shadow:0 18px 50px rgba(0,0,0,.16);border-radius:18px;padding:18px;min-width:0}.filter,.trend-controls{display:flex;gap:11px;align-items:flex-end;flex-wrap:wrap}.filter{margin-bottom:14px}.trend-controls{margin:14px 0 2px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted)}input{color:var(--text);color-scheme:dark;background:#081625;border:1px solid var(--line);padding:9px 11px;border-radius:9px;font:inherit}input[type=number]{width:160px}.btn{border:0;background:var(--cyan);color:#04131c;padding:10px 15px;border-radius:9px;cursor:pointer;font:inherit;font-weight:700}.btn.secondary{background:#132b45;color:var(--text);border:1px solid var(--line)}.status{margin-left:auto;font-size:12px}.charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.full-row{grid-column:1/-1}.chart{height:420px}.full-row .chart{height:470px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.panel h2{font-size:16px;margin:0}.note-panel{margin-bottom:14px}.note{color:var(--muted);line-height:1.72;padding:8px 4px}.note li{margin:5px 0}.warning{color:#ffd0d7;border-left:3px solid var(--red);padding:10px 12px;margin:12px 0 0;background:rgba(255,114,133,.07)}footer{text-align:center;color:var(--muted);font-size:12px;margin-top:20px}@media(max-width:900px){header{align-items:flex-start;flex-direction:column}.charts{grid-template-columns:1fr}.status{width:100%;margin-left:0}.full-row{grid-column:auto}}@media(max-width:620px){.shell{width:calc(100% - 20px);padding-top:20px}.chart,.full-row .chart{height:360px}}
</style></head><body><main class="shell"><header><div><div class="eyebrow">NYMEX · PLATINUM CURVE</div><h1>NYMEX铂金月差</h1><p class="subtitle">主力月份与下一季度月份月差、库存、持仓成本及Borrow收益</p></div></header>
<section class="panel note-panel"><div class="panel-head"><h2>月差说明</h2></div><div class="note"><ul><li>NYMEX铂金主要活跃交割月份为1月、4月、7月和10月。每日以成交量最大的合约作为主力，并取其后3个月的合约作为次主力。</li><li>月差＝近月价格－远月价格。正值表示近月升水，负值表示远月升水。</li><li>持仓成本＝主力价格×资金利率×3÷12＋仓储费÷50×3，其中NYMEX铂金每手50盎司。</li><li>Borrow年化收益率＝（−月差−仓储费÷50×3）÷主力价格×12÷3。</li></ul><div class="warning"><strong>数据口径警示：</strong>2026-07-30及以前使用两个合约的收盘价计算月差；2026-07-31起使用CME官方结算价。对于日终期限结构、持仓成本和Borrow收益分析，CME官方结算价通常更准确，因为各月份采用统一结算时点，并会综合日历价差成交或报价；收盘价可能来自不同时间的最后成交，远月流动性不足时偏差尤其明显。</div></div></section>
<section class="panel filter"><div class="field"><label>开始日期</label><input id="start" type="date"></div><div class="field"><label>结束日期</label><input id="end" type="date"></div><button id="apply" class="btn">应用筛选</button><button id="reset" class="btn secondary">全部历史</button><span id="status" class="status"></span></section>
<section class="charts"><article class="panel"><div class="panel-head"><h2>活跃合约月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>NYMEX铂金总库存季节图</h2><span class="period">吨</span></div><div id="total" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>1月—4月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0104" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>4月—7月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0407" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>7月—10月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0710" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>10月—次年1月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread1001" class="chart"></div></article><article class="panel full-row"><div class="panel-head"><h2>活跃月差与负持仓成本</h2><span class="period">美元/盎司</span></div><div class="trend-controls"><div class="field"><label>资金利率（%）</label><input id="interestRate" type="number" min="0" step="0.1" value="3.5"></div><div class="field"><label>仓储费（美元/手/月）</label><input id="storageFee" type="number" min="0" step="0.5" value="20"></div><button id="trendApply" class="btn">应用参数</button><button id="trendReset" class="btn secondary">恢复默认</button><span id="trendStatus" class="status"></span></div><div id="spreadTrend" class="chart"></div><div id="costFormula" class="period"></div></article><article class="panel full-row"><div class="panel-head"><h2>Borrow年化收益率</h2><span class="period">%</span></div><div id="borrowTrend" class="chart"></div><div id="borrowFormula" class="period"></div></article></section><footer>数据来源：历史收盘价数据、CME Group NYMEX</footer></main>
<script>
const DATA=__SPREAD_DATA__,S=DATA.spread,I=DATA.inventory,CUT=DATA.priceSourceCutoff,$=id=>document.getElementById(id),cfg={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};
const base={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#b8cbe0',family:'Inter,"Microsoft YaHei",sans-serif'},margin:{l:64,r:20,t:22,b:48},hovermode:'x unified',legend:{orientation:'h',y:1.09},xaxis:{gridcolor:'#17304a',zeroline:false},yaxis:{gridcolor:'#17304a',zeroline:false}};
const colors=['#31d7c5','#f0bd63','#65a7ff','#ff7285','#aa87ff','#46d29a','#ec8ed0','#a7c957'],monthTicks=['01-01','02-01','03-01','04-01','05-01','06-01','07-01','08-01','09-01','10-01','11-01','12-01'];
const valid=n=>n!==null&&Number.isFinite(Number(n));function between(rows,a,b){return rows.filter(x=>x.date>=a&&x.date<=b)}function gapRuns(rows,maxDays=10){const runs=[];rows.forEach(point=>{const run=runs.at(-1),previous=run?.at(-1),gap=previous?(new Date(point.date)-new Date(previous.date))/86400000:0;if(!run||gap>maxDays)runs.push([point]);else run.push(point)});return runs}
function seasonal(div,rows,field,digits,isSpread=false,label='库存'){const years=[...new Set(rows.map(x=>x.date.slice(0,4)))].sort(),calendar=[...new Set(rows.map(x=>x.date.slice(5)))].sort(),traces=[];years.forEach((year,i)=>{const r=rows.filter(x=>x.date.startsWith(year)&&valid(x[field]));gapRuns(r).forEach((run,j)=>traces.push({x:run.map(x=>x.date.slice(5)),y:run.map(x=>x[field]),customdata:isSpread?run.map(x=>[x.mainPrice,x.nextPrice,x.priceType,x.mainContract,x.nextContract]):undefined,name:year,legendgroup:year,showlegend:j===0,mode:'lines',connectgaps:false,line:{width:year===years.at(-1)?2.7:1.6,color:colors[i%colors.length]},hovertemplate:isSpread?`${year} %{x}<br>%{customdata[3]} %{customdata[0]:.2f}<br>%{customdata[4]} %{customdata[1]:.2f}<br>%{customdata[2]}月差 %{y:.2f}<extra></extra>`:`${year} %{x}<br>${label} %{y:.${digits}f}<extra></extra>`}))});const rollYear=isSpread?[...years].reverse().find(year=>rows.filter(x=>x.date.startsWith(year)&&x.roll).length>=3):null,rolls=rollYear?rows.filter(x=>x.date.startsWith(rollYear)&&x.roll):[],shapes=rolls.map(x=>({type:'line',xref:'x',yref:'paper',x0:x.date.slice(5),x1:x.date.slice(5),y0:0,y1:1,line:{color:'#f0bd63',width:1,dash:'dot'}}));Plotly.react(div,traces,{...base,xaxis:{...base.xaxis,type:'category',categoryorder:'array',categoryarray:calendar,tickmode:'array',tickvals:monthTicks,ticktext:monthTicks},yaxis:{...base.yaxis,zeroline:isSpread,zerolinecolor:'#718096',zerolinewidth:1},shapes},cfg)}
function deliverySeries(div,rows){const r=rows.filter(x=>valid(x.delivery));Plotly.react(div,[{x:r.map(x=>x.date),y:r.map(x=>x.delivery),type:'bar',marker:{color:'#31d7c5'},hovertemplate:'%{x}<br>交割量 %{y:,.0f} 手<extra></extra>'}],{...base,showlegend:false,xaxis:{...base.xaxis,type:'date'},yaxis:{...base.yaxis,rangemode:'tozero'}},cfg)}
function pairSeasonal(div,rows,pair){const selected=rows.filter(x=>x.pair===pair&&valid(x.spread)),years=[...new Set(selected.map(x=>x.date.slice(0,4)))].sort(),traces=[];years.forEach((year,i)=>gapRuns(selected.filter(x=>x.date.startsWith(year))).forEach((run,j)=>traces.push({x:run.map(x=>'2000-'+x.date.slice(5)),y:run.map(x=>x.spread),customdata:run.map(x=>[x.mainContract,x.nextContract,x.mainPrice,x.nextPrice,x.priceType]),name:year,legendgroup:year,showlegend:j===0,mode:'lines',connectgaps:false,line:{width:year===years.at(-1)?2.7:1.6,color:colors[i%colors.length]},hovertemplate:`${year} %{x|%m-%d}<br>%{customdata[0]} %{customdata[2]:.2f}<br>%{customdata[1]} %{customdata[3]:.2f}<br>%{customdata[4]}月差 %{y:.2f}<extra></extra>`})));Plotly.react(div,traces,{...base,xaxis:{...base.xaxis,type:'date',range:['2000-01-01','2000-12-31'],tickformat:'%m-%d',hoverformat:'%m-%d'},yaxis:{...base.yaxis,zeroline:true,zerolinecolor:'#718096',zerolinewidth:1}},cfg)}
function sourceMarker(rows){if(!rows.length||CUT<rows[0].date||CUT>rows.at(-1).date)return{shapes:[],annotations:[]};return{shapes:[{type:'line',xref:'x',yref:'paper',x0:CUT,x1:CUT,y0:0,y1:1,line:{color:'#ff7285',width:1.5,dash:'dash'}}],annotations:[{xref:'x',yref:'paper',x:CUT,y:1,text:'结算价口径起点',showarrow:false,xanchor:'left',font:{size:10,color:'#ff7285'}}]}}
function holding(x){const rate=Number($('interestRate').value||0)/100,storage=Number($('storageFee').value||0);return x.mainPrice*rate*x.monthGap/12+storage/50*x.monthGap}
function spreadCostTrend(rows){const cost=rows.map(holding),custom=rows.map((x,i)=>[x.mainPrice,x.nextPrice,x.monthGap,cost[i],x.priceType,x.mainContract,x.nextContract]),marker=sourceMarker(rows);Plotly.react('spreadTrend',[{x:rows.map(x=>x.date),y:rows.map(x=>x.spread),customdata:custom,name:'月差（主力－次主力）',mode:'lines',line:{color:'#31d7c5',width:2.4},hovertemplate:'%{x}<br>%{customdata[5]} / %{customdata[6]}<br>%{customdata[0]:.2f} − %{customdata[1]:.2f} = %{y:.2f}<br>%{customdata[4]}<extra></extra>'},{x:rows.map(x=>x.date),y:cost.map(x=>-x),customdata:custom,name:'-持仓成本',mode:'lines',line:{color:'#f0bd63',width:2,dash:'dot'},hovertemplate:'%{x}<br>间隔 %{customdata[2]}个月<br>-持仓成本 %{y:.2f}<extra></extra>'}],{...base,xaxis:{...base.xaxis,type:'date',rangeslider:{visible:true,thickness:.08}},yaxis:{...base.yaxis,zeroline:true,zerolinecolor:'#718096',zerolinewidth:1},...marker},cfg);$('trendStatus').textContent=`利率 ${Number($('interestRate').value).toFixed(1)}% · 仓储费 ${Number($('storageFee').value).toFixed(1)}美元/手/月`;$('costFormula').textContent=`持仓成本＝主力价格 × ${Number($('interestRate').value).toFixed(1)}% × 3 ÷ 12＋${Number($('storageFee').value).toFixed(1)} ÷ 50 × 3；图中绘制其负值。`}
function borrowYieldTrend(rows){const storage=Number($('storageFee').value||0),yields=rows.map(x=>(-x.spread-storage/50*x.monthGap)/x.mainPrice*12/x.monthGap*100),custom=rows.map((x,i)=>[x.spread,x.mainPrice,x.monthGap,storage/50*x.monthGap,x.priceType]),marker=sourceMarker(rows);Plotly.react('borrowTrend',[{x:rows.map(x=>x.date),y:yields,customdata:custom,name:'Borrow年化收益率',mode:'lines',line:{color:'#65a7ff',width:2.4},hovertemplate:'%{x}<br>%{customdata[4]}月差 %{customdata[0]:.2f}<br>仓储费 %{customdata[3]:.2f}<br>主力价格 %{customdata[1]:.2f}<br>年化收益率 %{y:.2f}%<extra></extra>'}],{...base,showlegend:false,xaxis:{...base.xaxis,type:'date',rangeslider:{visible:true,thickness:.08}},yaxis:{...base.yaxis,ticksuffix:'%',zeroline:true,zerolinecolor:'#718096',zerolinewidth:1},...marker},cfg);$('borrowFormula').textContent=`Borrow年化收益率＝（−月差−${storage.toFixed(1)} ÷ 50 × 3）÷ 主力价格 × 12 ÷ 3。`}
function render(){const a=$('start').value,b=$('end').value,sp=between(S,a,b),inv=between(I,a,b);seasonal('spread',sp,'spread',2,true);seasonal('total',inv,'total',3,false,'总库存');pairSeasonal('spread0104',sp,'0104');pairSeasonal('spread0407',sp,'0407');pairSeasonal('spread0710',sp,'0710');pairSeasonal('spread1001',sp,'1001');spreadCostTrend(sp);borrowYieldTrend(sp);$('status').textContent=`月差 ${sp.length.toLocaleString('zh-CN')} 条 · 库存 ${inv.length.toLocaleString('zh-CN')} 条`}
const dates=[...S.map(x=>x.date),...I.map(x=>x.date)].sort(),first=dates[0],last=dates.at(-1),def=first>'2021-01-01'?first:'2021-01-01';$('start').min=first;$('start').max=last;$('start').value=def;$('end').min=first;$('end').max=last;$('end').value=last;$('apply').onclick=render;$('reset').onclick=()=>{$('start').value=first;$('end').value=last;render()};$('trendApply').onclick=()=>{const rows=between(S,$('start').value,$('end').value);spreadCostTrend(rows);borrowYieldTrend(rows)};$('trendReset').onclick=()=>{$('interestRate').value=3.5;$('storageFee').value=20;const rows=between(S,$('start').value,$('end').value);spreadCostTrend(rows);borrowYieldTrend(rows)};render();
</script></body></html>'''


if __name__ == "__main__":
    NYMEXSpreadHTMLGenerator().generate()
