from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUNCE_TO_TONNE = 31.1035 / 1_000_000
MONTHS = [3, 5, 7, 9, 12]
NEXT_MONTH = {3: 5, 5: 7, 7: 9, 9: 12, 12: 3}
MONTH_LABEL = {3: "3月", 5: "5月", 7: "7月", 9: "9月", 12: "12月"}


def _read_wind_csv(path: Path, expected_columns: int) -> pd.DataFrame:
    """Read a Wind-exported GBK CSV and discard its metadata/footer rows."""
    frame = pd.read_csv(path, encoding="gb18030", skiprows=5, header=None)
    frame = frame.iloc[:, :expected_columns].copy()
    frame[frame.columns[0]] = pd.to_datetime(
        frame.iloc[:, 0].astype("object"), format="mixed", errors="coerce"
    )
    return frame.dropna(subset=[frame.columns[0]])


class COMEXSilverHTMLGenerator:
    """Build the COMEX silver inventory and calendar-spread seasonal page."""

    def __init__(
        self,
        stock_csv="data/comex_ag_stock.csv",
        settle_csv="data/comex_ag_settle.csv",
    ):
        self.stock_csv = Path(stock_csv)
        self.settle_csv = Path(settle_csv)

    def _inventory_records(self):
        frame = _read_wind_csv(self.stock_csv, 4)
        frame.columns = ["date", "total_oz", "registered_oz", "delivery_lots"]
        for column in ["total_oz", "registered_oz", "delivery_lots"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")

        records = []
        for row in frame.itertuples(index=False):
            total = None if pd.isna(row.total_oz) else float(row.total_oz)
            registered = (
                None if pd.isna(row.registered_oz) else float(row.registered_oz)
            )
            eligible = (
                None if total is None or registered is None else total - registered
            )
            records.append(
                {
                    "date": row.date.strftime("%Y-%m-%d"),
                    "total": None if total is None else round(total * OUNCE_TO_TONNE, 6),
                    "registered": None
                    if registered is None
                    else round(registered * OUNCE_TO_TONNE, 6),
                    "eligible": None
                    if eligible is None
                    else round(eligible * OUNCE_TO_TONNE, 6),
                    "delivery": None
                    if pd.isna(row.delivery_lots)
                    else float(row.delivery_lots),
                }
            )
        return records

    def _spread_records(self):
        frame = _read_wind_csv(self.settle_csv, 7)
        frame.columns = [
            "date", "m03", "m05", "m07", "m09", "m12", "active",
        ]
        price_columns = ["m03", "m05", "m07", "m09", "m12", "active"]
        frame[price_columns] = frame[price_columns].apply(
            pd.to_numeric, errors="coerce"
        )
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")

        records = []
        previous_main_month = None
        for row in frame.itertuples(index=False):
            if pd.isna(row.active):
                continue
            prices = {
                3: row.m03,
                5: row.m05,
                7: row.m07,
                9: row.m09,
                12: row.m12,
            }
            available = {
                month: float(value)
                for month, value in prices.items()
                if not pd.isna(value)
            }
            if not available:
                continue
            active_price = float(row.active)
            main_month = min(
                available,
                key=lambda month: abs(available[month] - active_price),
            )
            match_diff = abs(available[main_month] - active_price)
            # Some early Wind observations use a non-base delivery month as the
            # active contract.  Without that contract's settlement, the next-base
            # spread cannot be reconstructed reliably, so leave those dates out.
            if match_diff > 1e-7:
                continue
            next_month = NEXT_MONTH[main_month]
            if next_month not in available:
                continue
            next_price = available[next_month]
            records.append(
                {
                    "date": row.date.strftime("%Y-%m-%d"),
                    "mainMonth": MONTH_LABEL[main_month],
                    "nextMonth": MONTH_LABEL[next_month],
                    "mainSettle": active_price,
                    "nextSettle": next_price,
                    "spread": round(active_price - next_price, 6),
                    "monthGap": (next_month - main_month) % 12,
                    "matchDiff": round(match_diff, 8),
                    "roll": previous_main_month is not None
                    and main_month != previous_main_month,
                }
            )
            previous_main_month = main_month
        return records

    def _pair_records(self):
        """Return full-year fixed-month spreads and flag the active-pair window."""
        frame = _read_wind_csv(self.settle_csv, 7)
        frame.columns = [
            "date", "m03", "m05", "m07", "m09", "m12", "active",
        ]
        price_columns = ["m03", "m05", "m07", "m09", "m12", "active"]
        frame[price_columns] = frame[price_columns].apply(
            pd.to_numeric, errors="coerce"
        )
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")

        pairs = [(3, 5), (5, 7), (7, 9), (9, 12), (12, 3)]
        records = []
        for row in frame.itertuples(index=False):
            prices = {
                3: row.m03,
                5: row.m05,
                7: row.m07,
                9: row.m09,
                12: row.m12,
            }
            active_month = None
            if not pd.isna(row.active):
                available = {
                    month: float(value)
                    for month, value in prices.items()
                    if not pd.isna(value)
                }
                if available:
                    candidate = min(
                        available,
                        key=lambda month: abs(available[month] - float(row.active)),
                    )
                    if abs(available[candidate] - float(row.active)) <= 1e-7:
                        active_month = candidate

            for front, back in pairs:
                if pd.isna(prices[front]) or pd.isna(prices[back]):
                    continue
                front_price = float(prices[front])
                back_price = float(prices[back])
                records.append(
                    {
                        "date": row.date.strftime("%Y-%m-%d"),
                        "pair": f"{front:02d}{back:02d}",
                        "frontMonth": MONTH_LABEL[front],
                        "backMonth": MONTH_LABEL[back],
                        "frontSettle": front_price,
                        "backSettle": back_price,
                        "spread": round(front_price - back_price, 6),
                        "active": active_month == front and NEXT_MONTH[front] == back,
                    }
                )
        return records

    def generate(self, output_file="site/pgm/comex_silver.html"):
        payload = {
            "spread": self._spread_records(),
            "pairSpreads": self._pair_records(),
            "inventory": self._inventory_records(),
        }
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        html = _HTML_TEMPLATE.replace("__SILVER_DATA__", encoded.replace("</", "<\\/"))
        output.write_text(html, encoding="utf-8")
        print(f"COMEX silver dashboard saved: {output.resolve()}")
        return output


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="COMEX白银库存与主力月差季节性分析"><title>COMEX Silver Research</title>
<script src="assets/vendor/plotly-2.35.2.min.js"></script><style>
:root{--bg:#07111f;--panel:#0d1b2d;--text:#edf6ff;--muted:#89a0b8;--line:#213852;--cyan:#31d7c5;--silver:#cbd5e1;--red:#ff7285}*{box-sizing:border-box}body{margin:0;color:var(--text);background:radial-gradient(circle at 8% 0%,#12314b 0,transparent 32%),radial-gradient(circle at 100% 10%,#2b304c 0,transparent 30%),var(--bg);font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}.shell{width:min(1880px,calc(100% - 32px));margin:auto;padding:30px 0 56px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:18px}.eyebrow{color:var(--silver);letter-spacing:.16em;font-size:12px;font-weight:700}h1{font-size:clamp(28px,5vw,50px);margin:7px 0 5px;letter-spacing:-.04em}.subtitle,.period,.status{color:var(--muted)}.subtitle{margin:0}.nav{display:flex;gap:9px;flex-wrap:wrap}.nav a{color:var(--cyan);text-decoration:none;border:1px solid var(--line);padding:10px 13px;border-radius:10px;background:#081625}.panel{background:linear-gradient(145deg,rgba(17,38,61,.94),rgba(10,25,42,.96));border:1px solid var(--line);box-shadow:0 18px 50px rgba(0,0,0,.16);border-radius:18px;padding:18px;min-width:0}.filter{display:flex;gap:11px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px}.trend-controls{display:flex;gap:11px;align-items:flex-end;flex-wrap:wrap;margin:14px 0 2px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted)}input{color:var(--text);color-scheme:dark;background:#081625;border:1px solid var(--line);padding:9px 11px;border-radius:9px;font:inherit}input[type=number]{width:150px}.btn{border:0;background:var(--cyan);color:#04131c;padding:10px 15px;border-radius:9px;cursor:pointer;font:inherit;font-weight:700}.btn.secondary{background:#132b45;color:var(--text);border:1px solid var(--line)}.status{margin-left:auto;font-size:12px}.charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.charts>article:nth-child(3){display:none}.full-row{grid-column:1/-1}.full-row .chart{height:470px}.chart{height:420px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.panel h2{font-size:16px;margin:0}.note-panel{margin-bottom:14px}.note{color:var(--muted);line-height:1.7;padding:8px 4px}.note li{margin:5px 0}footer{text-align:center;color:var(--muted);font-size:12px;margin-top:20px}@media(max-width:900px){header{align-items:flex-start;flex-direction:column}.charts{grid-template-columns:1fr}.status{width:100%;margin-left:0}}@media(max-width:620px){.shell{width:calc(100% - 20px);padding-top:20px}.chart,.full-row .chart{height:360px}}
</style></head><body><main class="shell"><header><div><div class="eyebrow">COMEX · SILVER RESEARCH</div><h1>COMEX白银月差</h1><p class="subtitle">主力月份与下一主力月份月差、库存及注册仓单季节性</p></div></header>
<section class="panel note-panel"><div class="panel-head"><h2>月差说明</h2></div><div class="note"><ul><li>COMEX白银主要交割月份为3月、5月、7月、9月和12月。每日以Wind“活跃合约”结算价识别主力月份，并取其后的下一主力月份。</li><li>月差＝近端月份结算价－远端月份结算价。正值表示近端升水，负值表示远端升水。</li><li>五张分月份图展示对应Wind固定交割月份连续序列的全年月差。虚线表示该组合不是当日主力—次主力；组合实际成为主力—次主力期间以同色实线覆盖。</li><li>固定月份连续序列会在各自换年时切换实际合约，因此虚线区间可能出现由换月产生的跳点；这类跳点不应直接解释为市场月差在一天内发生同等幅度变化。</li><li>月份间隔并不完全相同：3月至5月、5月至7月和7月至9月相隔2个月；9月至12月及12月至次年3月相隔3个月。</li></ul></div></section>
<section class="panel filter"><div class="field"><label>开始日期</label><input id="start" type="date"></div><div class="field"><label>结束日期</label><input id="end" type="date"></div><button id="apply" class="btn">应用筛选</button><button id="reset" class="btn secondary">全部历史</button><span id="status" class="status"></span></section>
<section class="charts"><article class="panel"><div class="panel-head"><h2>COMEX白银月差季节图（主力-次主力）</h2><span class="period">美元/盎司</span></div><div id="spread" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>COMEX白银总库存季节图</h2><span class="period">吨</span></div><div id="total" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>月差说明</h2></div><div class="note"><ul><li>COMEX白银主要交割月份为3月、5月、7月、9月和12月。每日以Wind“活跃合约”结算价识别主力月份，并取其后的下一主力月份。</li><li>月差＝近端月份结算价－远端月份结算价。正值表示近端升水，负值表示远端升水。</li><li>五张分月份图展示对应Wind固定交割月份连续序列的全年月差。虚线表示该组合不是当日主力—次主力；组合实际成为主力—次主力期间以同色实线覆盖。</li><li>固定月份连续序列会在各自换年时切换实际合约，因此虚线区间可能出现由换月产生的跳点；这类跳点不应直接解释为市场月差在一天内发生同等幅度变化。</li><li>月份间隔并不完全相同：3月至5月、5月至7月和7月至9月相隔2个月；9月至12月及12月至次年3月相隔3个月。</li></ul></div></article><article class="panel"><div class="panel-head"><h2>COMEX白银注册仓单季节图</h2><span class="period">吨</span></div><div id="registered" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>COMEX白银非注册库存季节图</h2><span class="period">吨</span></div><div id="eligible" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>COMEX白银交割量时序图</h2><span class="period">手</span></div><div id="delivery" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>3月—5月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0305" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>5月—7月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0507" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>7月—9月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0709" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>9月—12月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread0912" class="chart"></div></article><article class="panel"><div class="panel-head"><h2>12月—3月月差季节图</h2><span class="period">美元/盎司</span></div><div id="spread1203" class="chart"></div></article><article class="panel full-row"><div class="panel-head"><h2>COMEX白银月差与负持仓成本时序图</h2><span class="period">美元/盎司</span></div><div class="trend-controls"><div class="field"><label>资金利率（%）</label><input id="interestRate" type="number" min="0" step="0.1" value="3.5"></div><div class="field"><label>仓储费（美元/银条/月）</label><input id="storageFee" type="number" min="0" step="0.5" value="10"></div><button id="trendApply" class="btn">应用参数</button><button id="trendReset" class="btn secondary">恢复默认</button><span id="trendStatus" class="status"></span></div><div id="spreadTrend" class="chart"></div><div id="costFormula" class="period"></div></article><article class="panel full-row"><div class="panel-head"><h2>COMEX白银Borrow年化收益率时序图</h2><span class="period">%</span></div><div id="borrowTrend" class="chart"></div><div id="borrowFormula" class="period"></div></article></section><footer>数据来源：Wind、CME Group COMEX</footer></main>
<script>
const DATA=__SILVER_DATA__,S=DATA.spread,P=DATA.pairSpreads,I=DATA.inventory,$=id=>document.getElementById(id),cfg={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};
const base={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#b8cbe0',family:'Inter,"Microsoft YaHei",sans-serif'},margin:{l:64,r:20,t:22,b:48},hovermode:'x unified',legend:{orientation:'h',y:1.09},xaxis:{gridcolor:'#17304a',zeroline:false},yaxis:{gridcolor:'#17304a',zeroline:false}};
const colors=['#31d7c5','#f0bd63','#65a7ff','#ff7285','#aa87ff','#46d29a','#ec8ed0','#a7c957'];
const monthTicks=['01-01','02-01','03-01','04-01','05-01','06-01','07-01','08-01','09-01','10-01','11-01','12-01'];
const valid=n=>n!==null&&Number.isFinite(Number(n));
function between(rows,a,b){return rows.filter(x=>x.date>=a&&x.date<=b)}
function seasonal(div,rows,field,digits,isSpread=false,label='库存'){
  const years=[...new Set(rows.map(x=>x.date.slice(0,4)))].sort();
  const calendar=[...new Set(rows.map(x=>x.date.slice(5)))].sort();
  const traces=years.map((year,i)=>{
    const r=rows.filter(x=>x.date.startsWith(year)&&valid(x[field]));
    return{x:r.map(x=>x.date.slice(5)),y:r.map(x=>x[field]),customdata:isSpread?r.map(x=>[x.mainSettle,x.nextSettle]):undefined,name:year,mode:'lines',connectgaps:true,line:{width:year===years.at(-1)?2.7:1.6,color:colors[i%colors.length]},hovertemplate:isSpread?`${year} %{x}<br>%{customdata[0]:.3f} − %{customdata[1]:.3f} = %{y:.3f}<extra></extra>`:`${year} %{x}<br>${label} %{y:.${digits}f}<extra></extra>`}
  });
  const rollYear=isSpread?[...years].reverse().find(year=>rows.filter(x=>x.date.startsWith(year)&&x.roll).length>=5):null;
  const rolls=rollYear?rows.filter(x=>x.date.startsWith(rollYear)&&x.roll):[];
  const shapes=rolls.map(x=>({type:'line',xref:'x',yref:'paper',x0:x.date.slice(5),x1:x.date.slice(5),y0:0,y1:1,line:{color:'#f0bd63',width:1,dash:'dot'}}));
  const annotations=rolls.map(x=>({xref:'x',yref:'paper',x:x.date.slice(5),y:-.13,text:'主力切换',showarrow:false,textangle:-90,font:{size:9,color:'#f0bd63'}}));
  Plotly.react(div,traces,{...base,margin:{...base.margin,b:isSpread?72:48},xaxis:{...base.xaxis,type:'category',categoryorder:'array',categoryarray:calendar,tickmode:'array',tickvals:monthTicks,ticktext:monthTicks},yaxis:{...base.yaxis,zeroline:isSpread,zerolinecolor:'#718096',zerolinewidth:1},shapes,annotations},cfg)
}
function deliverySeries(div,rows){
  const selected=rows.filter(x=>valid(x.delivery));
  const trace={x:selected.map(x=>x.date),y:selected.map(x=>x.delivery),type:'bar',name:'交割量',marker:{color:'#31d7c5'},hovertemplate:'%{x}<br>交割量 %{y:,.0f} 手<extra></extra>'};
  Plotly.react(div,[trace],{...base,showlegend:false,xaxis:{...base.xaxis,type:'date'},yaxis:{...base.yaxis,rangemode:'tozero'}},cfg)
}
function spreadCostTrend(div,rows){
  const rate=Number($('interestRate').value||0)/100,storage=Number($('storageFee').value||0);
  const cost=rows.map(x=>x.monthGap*rate/12*x.mainSettle+x.monthGap*storage/1000);
  const custom=rows.map((x,i)=>[x.mainSettle,x.nextSettle,x.monthGap,cost[i]]);
  const traces=[
    {x:rows.map(x=>x.date),y:rows.map(x=>x.spread),customdata:custom,name:'月差（主力－次主力）',mode:'lines',line:{color:'#31d7c5',width:2.4},hovertemplate:'%{x}<br>%{customdata[0]:.3f} − %{customdata[1]:.3f} = %{y:.3f}<extra></extra>'},
    {x:rows.map(x=>x.date),y:cost.map(x=>-x),customdata:custom,name:'-持仓成本',mode:'lines',line:{color:'#f0bd63',width:2,dash:'dot'},hovertemplate:'%{x}<br>间隔 %{customdata[2]}个月<br>-持仓成本 %{y:.3f}<extra></extra>'}
  ];
  Plotly.react(div,traces,{...base,xaxis:{...base.xaxis,type:'date',rangeslider:{visible:true,thickness:.08}},yaxis:{...base.yaxis,zeroline:true,zerolinecolor:'#718096',zerolinewidth:1}},cfg)
  $('trendStatus').textContent=`利率 ${Number($('interestRate').value).toFixed(1)}% · 仓储费 ${Number($('storageFee').value).toFixed(1)}美元/银条/月`;
  $('costFormula').textContent=`持仓成本＝月份间隔 × ${Number($('interestRate').value).toFixed(1)}% ÷ 12 × 主力价格＋月份间隔 × ${Number($('storageFee').value).toFixed(1)} ÷ 1000；图中绘制其负值。`;
}
function borrowYieldTrend(div,rows){
  const storage=Number($('storageFee').value||0);
  const yields=rows.map(x=>(-x.spread-x.monthGap*storage/1000)/x.mainSettle*12/x.monthGap*100);
  const custom=rows.map((x,i)=>[x.spread,x.mainSettle,x.monthGap,x.monthGap*storage/1000,yields[i]]);
  const trace={x:rows.map(x=>x.date),y:yields,customdata:custom,name:'Borrow年化收益率',mode:'lines',line:{color:'#65a7ff',width:2.4},hovertemplate:'%{x}<br>月差 %{customdata[0]:.3f}<br>仓储费 %{customdata[3]:.3f}<br>主力价格 %{customdata[1]:.3f}<br>间隔 %{customdata[2]}个月<br>年化收益率 %{y:.2f}%<extra></extra>'};
  Plotly.react(div,[trace],{...base,showlegend:false,xaxis:{...base.xaxis,type:'date',rangeslider:{visible:true,thickness:.08}},yaxis:{...base.yaxis,ticksuffix:'%',zeroline:true,zerolinecolor:'#718096',zerolinewidth:1}},cfg);
  $('borrowFormula').textContent=`Borrow年化收益率＝（−白银月差－月份间隔 × ${storage.toFixed(1)} ÷ 1000）÷ 主力合约价格 × 12 ÷ 月份间隔。`;
}
function pairSeasonal(div,rows,pairCode){
  const selected=rows.filter(x=>x.pair===pairCode&&valid(x.spread));
  const years=[...new Set(selected.map(x=>x.date.slice(0,4)))].sort();
  const calendar=[...new Set(selected.map(x=>x.date.slice(5)))].sort();
  const traces=[];
  years.forEach((year,i)=>{
    const r=selected.filter(x=>x.date.startsWith(year));
    const color=colors[i%colors.length];
    const hover=`${year} %{x}<br>%{customdata[0]} %{customdata[2]:.3f}<br>%{customdata[1]} %{customdata[3]:.3f}<br>月差 %{y:.3f}<extra></extra>`;
    const runs=[];
    r.forEach(point=>{
      if(!runs.length||runs.at(-1)[0].active!==point.active)runs.push([point]);
      else runs.at(-1).push(point);
    });
    runs.forEach((run,runIndex)=>{
      const active=run[0].active;
      traces.push({x:run.map(x=>x.date.slice(5)),y:run.map(x=>x.spread),customdata:run.map(x=>[x.frontMonth,x.backMonth,x.frontSettle,x.backSettle]),name:year,legendgroup:year,showlegend:runIndex===0,mode:'lines',connectgaps:true,line:{width:active?3:1.6,color,dash:active?'solid':'dash'},hovertemplate:hover});
    });
  });
  Plotly.react(div,traces,{...base,xaxis:{...base.xaxis,type:'category',categoryorder:'array',categoryarray:calendar,tickmode:'array',tickvals:monthTicks,ticktext:monthTicks},yaxis:{...base.yaxis,zeroline:true,zerolinecolor:'#718096',zerolinewidth:1}},cfg)
}
function render(){
  const a=$('start').value,b=$('end').value,sp=between(S,a,b),pairs=between(P,a,b),inv=between(I,a,b);
  seasonal('spread',sp,'spread',3,true);
  seasonal('total',inv,'total',3);
  seasonal('registered',inv,'registered',3);
  seasonal('eligible',inv,'eligible',3);
  deliverySeries('delivery',inv);
  pairSeasonal('spread0305',pairs,'0305');
  pairSeasonal('spread0507',pairs,'0507');
  pairSeasonal('spread0709',pairs,'0709');
  pairSeasonal('spread0912',pairs,'0912');
  pairSeasonal('spread1203',pairs,'1203');
  spreadCostTrend('spreadTrend',sp);
  borrowYieldTrend('borrowTrend',sp);
  $('status').textContent=`月差 ${sp.length.toLocaleString('zh-CN')} 条 · 库存 ${inv.length.toLocaleString('zh-CN')} 条`
}
const dates=[...S.map(x=>x.date),...I.map(x=>x.date)].sort(),first=dates[0],last=dates.at(-1),def=first>'2021-01-01'?first:'2021-01-01';
$('start').min=first;$('start').max=last;$('start').value=def;$('end').min=first;$('end').max=last;$('end').value=last;
$('apply').onclick=render;$('reset').onclick=()=>{$('start').value=first;$('end').value=last;render()};$('trendApply').onclick=()=>{const rows=between(S,$('start').value,$('end').value);spreadCostTrend('spreadTrend',rows);borrowYieldTrend('borrowTrend',rows)};$('trendReset').onclick=()=>{$('interestRate').value=3.5;$('storageFee').value=10;const rows=between(S,$('start').value,$('end').value);spreadCostTrend('spreadTrend',rows);borrowYieldTrend('borrowTrend',rows)};render();
</script></body></html>'''


if __name__ == "__main__":
    COMEXSilverHTMLGenerator().generate()
