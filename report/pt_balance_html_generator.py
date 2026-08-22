from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


class PTBalanceHTMLGenerator:
    """Generate the monthly China platinum supply, inventory and consumption page."""

    def __init__(self, import_csv, export_csv, inventory_csv):
        self.import_csv = Path(import_csv)
        self.export_csv = Path(export_csv)
        self.inventory_csv = Path(inventory_csv)

    @staticmethod
    def _trade_monthly(path):
        frame = pd.read_csv(path, encoding="gb18030", dtype={"数据年月": str})
        frame["period"] = pd.to_datetime(frame["数据年月"], format="%Y%m", errors="coerce")
        frame["数量（吨）"] = pd.to_numeric(frame["数量（吨）"], errors="coerce").fillna(0)
        return frame.dropna(subset=["period"]).groupby("period")["数量（吨）"].sum()

    def _inventory_monthly(self):
        frame = pd.read_csv(self.inventory_csv)
        frame["date"] = pd.to_datetime(frame["date"].astype(str), format="%Y%m%d", errors="coerce")
        frame["today_receipt"] = pd.to_numeric(frame["today_receipt"], errors="coerce")
        frame = frame.dropna(subset=["date", "today_receipt"])
        daily = frame.groupby("date")["today_receipt"].sum().sort_index() / 1000
        return daily.groupby(daily.index.to_period("M")).last(), daily.groupby(daily.index.to_period("M")).apply(lambda x: x.index[-1])

    def _records(self):
        imports = self._trade_monthly(self.import_csv)
        exports = self._trade_monthly(self.export_csv)
        inventory, inventory_dates = self._inventory_monthly()
        trade_periods = imports.index.union(exports.index).sort_values()
        all_periods = trade_periods.to_period("M").union(inventory.index).sort_values()
        # Expose five rolling forecast months after the latest customs trade month.
        latest_trade = trade_periods.max().to_period("M")
        forecast_periods = pd.period_range(latest_trade + 1, latest_trade + 5, freq="M")
        all_periods = all_periods.union(forecast_periods).sort_values()
        first_inventory = inventory.index.min()
        previous_inventory = 0.0
        records = []
        for period in all_periods:
            stamp = period.to_timestamp()
            imported = float(imports.get(stamp, 0)) if stamp in trade_periods else None
            exported = float(exports.get(stamp, 0)) if stamp in trade_periods else None
            net_import = None if imported is None else imported - (exported or 0)
            if period < first_inventory:
                month_end_inventory = 0.0
                inventory_change = 0.0
                inventory_date = None
            elif period in inventory.index:
                inventory_stamp = inventory_dates.loc[period]
                expected_month_end = pd.offsets.BMonthEnd().rollback(period.to_timestamp(how="end").normalize())
                if inventory_stamp.normalize() == expected_month_end:
                    month_end_inventory = float(inventory.loc[period])
                    inventory_change = month_end_inventory - previous_inventory
                    previous_inventory = month_end_inventory
                    inventory_date = inventory_stamp.strftime("%Y-%m-%d")
                else:
                    month_end_inventory = None
                    inventory_change = None
                    inventory_date = inventory_stamp.strftime("%Y-%m-%d")
            else:
                month_end_inventory = None
                inventory_change = None
                inventory_date = None
            consumption = None if net_import is None or inventory_change is None else net_import - inventory_change
            records.append({
                "period": str(period),
                "import": imported,
                "export": exported,
                "netImport": net_import,
                "inventory": month_end_inventory,
                "inventoryChange": inventory_change,
                "consumption": consumption,
                "inventoryDate": inventory_date,
                "tradeMissing": net_import is None,
            })

        by_period = {record["period"]: record for record in records}

        def ratio(current, previous):
            if current is None or previous is None or previous == 0:
                return None
            return current / previous - 1

        def ytd(field, year, month):
            values = [by_period.get(f"{year}-{m:02d}", {}).get(field) for m in range(1, month + 1)]
            available = [value for value in values if value is not None]
            return sum(available) if available else None

        for record in records:
            period = pd.Period(record["period"], freq="M")
            previous_month = by_period.get(str(period - 1), {})
            previous_year = by_period.get(str(period - 12), {})
            for field, prefix in (("import", "import"), ("export", "export"),
                                  ("netImport", "netImport"), ("consumption", "consumption")):
                current = record[field]
                record[f"{prefix}YoY"] = ratio(current, previous_year.get(field))
                current_ytd = ytd(field, period.year, period.month) if current is not None else None
                prior_ytd = ytd(field, period.year - 1, period.month) if current is not None else None
                record[f"{prefix}CumYoY"] = ratio(current_ytd, prior_ytd)
            record["netImportMoM"] = ratio(record["netImport"], previous_month.get("netImport"))
        return records

    def generate(self, output_file="site/pgm/pt_balance.html"):
        encoded = json.dumps({"records": self._records()}, ensure_ascii=False, separators=(",", ":"))
        html = _HTML_TEMPLATE.replace("__DATA__", encoded.replace("</", "<\\/"))
        html = html.replace("月度消费＝", "月度表观消费＝").replace("推算消费", "表观消费")
        html = html.replace("${r.length}个月 · ${complete.length}个月可计算消费", "")
        html = html.replace(
            "ticktext:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']",
            "ticktext:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],"
            "range:[0.5,12.5],autorange:false,tickangle:0,automargin:true,tickfont:{size:11}",
        )
        html = html.replace(
            "x:a.map(x=>Number(x.period.slice(5)))",
            "x:a.map(x=>Number(x.period.slice(5))+'月')",
        ).replace(
            "tickmode:'array',tickvals:[1,2,3,4,5,6,7,8,9,10,11,12],"
            "ticktext:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],"
            "range:[0.5,12.5],autorange:false,tickangle:0,automargin:true,tickfont:{size:11}",
            "type:'category',categoryorder:'array',"
            "categoryarray:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],"
            "tickangle:0,automargin:true,tickfont:{size:11}",
        ).replace("${year}年%{x}月<br>", "${year}年%{x}<br>")
        html = html.replace(
            "启用后取每月最后一个公布日的仓单合计。</div>",
            "启用后取每月最后一个公布日的仓单合计。<br>"
            "海关数据含71101100：未锻造铂，铂粉；71101910：铂板、片；"
            "71101990：其他半制的铂。</div>",
        )
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        print(f"China platinum balance dashboard generated: {output}")
        return output


_HTML_TEMPLATE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>中国铂月度供需</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><style>
.annual-wrap{max-height:50vh!important}
.table-wrap{max-height:76vh!important}.table-wrap table{border-collapse:separate!important;border-spacing:0}.balance-title th::after{content:'单位：吨';position:absolute;right:16px;top:50%;transform:translateY(-50%);color:#8ea5bb;font-size:12px;font-weight:400;letter-spacing:0}.year-start td{border-top:3px solid #31d7c5!important}.annual-wrap{overflow:auto;margin-top:14px;max-height:38vh}.annual-table{min-width:1500px!important;width:100%;border-collapse:separate!important;border-spacing:0}.annual-table th,.annual-table td{text-align:right;min-width:105px}.annual-table tbody td:first-child{position:sticky;left:0;z-index:3;background:#0d1b2d;text-align:left;min-width:150px}.estimate-input{width:104px;padding:6px 8px;border-radius:6px;text-align:right;border-color:#31d7c5;background:#071b2a}.estimate-input::placeholder{color:#69839a}.estimated{color:#f0bd63}.table-wrap,.annual-wrap{position:relative;isolation:isolate}.table-wrap thead,.annual-wrap thead{position:sticky;top:0;z-index:30;filter:drop-shadow(0 5px 5px rgba(0,0,0,.45))}.table-wrap thead th,.annual-wrap thead th{position:relative!important;top:auto!important;z-index:31!important;background:#0d1b2d!important;background-clip:padding-box}.table-wrap .balance-title th,.annual-wrap .balance-title th{background:#122a43!important}.table-wrap tbody,.annual-wrap tbody{position:relative;z-index:1}.cards,.charts,.status{display:none!important}.seasonal-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.seasonal-chart{height:390px}@media(max-width:760px){.seasonal-grid{grid-template-columns:1fr}}
:root{--bg:#07111f;--panel:#0d1b2d;--text:#edf6ff;--muted:#8ea5bb;--line:#213852;--cyan:#31d7c5;--gold:#f0bd63;--blue:#65a7ff;--red:#ff7285}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 8% 0,#12314b 0,transparent 32%),var(--bg);color:var(--text);font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}.shell{width:min(1540px,calc(100% - 32px));margin:auto;padding:30px 0 55px}.eyebrow{color:var(--cyan);font-size:12px;font-weight:700;letter-spacing:.16em}h1{font-size:clamp(30px,5vw,52px);margin:7px 0 5px}.subtitle,.muted{color:var(--muted)}.subtitle{margin:0 0 18px}.panel,.card{background:linear-gradient(145deg,rgba(17,38,61,.95),rgba(10,25,42,.97));border:1px solid var(--line);box-shadow:0 18px 50px rgba(0,0,0,.16)}.panel{border-radius:18px;padding:18px}.note{margin-bottom:14px;line-height:1.7;color:var(--muted)}.formula{color:var(--text);font-weight:700}.filter{display:flex;gap:11px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted)}input{color:var(--text);color-scheme:dark;background:#081625;border:1px solid var(--line);padding:9px 11px;border-radius:9px;font:inherit}.btn{border:0;background:var(--cyan);color:#04131c;padding:10px 15px;border-radius:9px;font-weight:700;cursor:pointer}.status{margin-left:auto;color:var(--muted);font-size:12px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px}.card{padding:16px;border-radius:16px}.label{font-size:13px;color:var(--muted)}.value{font-size:clamp(24px,3vw,36px);font-weight:760;margin:8px 0 3px}.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px}.full{grid-column:1/-1}.chart{height:430px}.head{display:flex;justify-content:space-between;gap:12px}.head h2{font-size:16px;margin:0}.table-wrap{overflow:auto;margin-top:14px}table{width:100%;min-width:1500px;border-collapse:collapse;font-size:13px}th,td{padding:10px 12px;border:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--muted);background:#0d1b2d}.balance-title th{text-align:center!important;color:var(--text);font-size:19px;letter-spacing:.08em;background:#122a43;padding:14px}.group-head th,.sub-head th{text-align:center!important}.group-head th{color:var(--cyan);font-size:14px}.sub-head th{font-weight:600}footer{text-align:center;color:var(--muted);font-size:12px;margin-top:18px}@media(max-width:900px){.cards,.charts{grid-template-columns:1fr 1fr}.status{width:100%;margin-left:0}}@media(max-width:620px){.shell{width:calc(100% - 20px)}.cards,.charts{grid-template-columns:1fr}.chart{height:360px}}
</style></head><body><main class="shell"><div class="eyebrow">CHINA PLATINUM · MONTHLY BALANCE</div><h1>中国铂月度供需</h1><p class="subtitle">海关净进口、广期所月末仓单库存与推算消费</p><section class="panel note"><div class="formula">月度消费＝当月净进口－（当月月末库存－上月月末库存）</div><div>净进口＝进口－出口；广期所仓单启用前库存按0处理，启用后取每月最后一个公布日的仓单合计。</div></section><section class="panel filter"><div class="field"><label>开始月份</label><input id="start" type="month"></div><div class="field"><label>结束月份</label><input id="end" type="month"></div><button id="apply" class="btn">应用筛选</button><span id="status" class="status"></span></section><section id="cards" class="cards"></section><section class="charts"><article class="panel full"><div class="head"><h2>月度供给与消费</h2><span class="muted">吨</span></div><div id="flow" class="chart"></div></article><article class="panel"><div class="head"><h2>广期所月末库存</h2><span class="muted">吨</span></div><div id="inventory" class="chart"></div></article><article class="panel"><div class="head"><h2>月度库存变化</h2><span class="muted">吨</span></div><div id="change" class="chart"></div></article></section><section class="panel table-wrap"><table><thead><tr class="balance-title"><th colspan="16">铂供需平衡表</th></tr><tr class="group-head"><th rowspan="2">月份</th><th colspan="3">铂进口量</th><th colspan="3">铂出口量</th><th colspan="4">铂净进口量</th><th colspan="2">铂库存</th><th colspan="3">铂表观消费</th></tr><tr class="sub-head"><th>海关</th><th>同比</th><th>累计同比</th><th>海关</th><th>同比</th><th>累计同比</th><th>海关</th><th>同比</th><th>累计同比</th><th>环比</th><th>合计</th><th>变化</th><th>合计</th><th>同比</th><th>累计同比</th></tr></thead><tbody id="rows"></tbody></table></section><footer>数据来源：中国海关、广州期货交易所；数量单位：吨</footer></main><script>
const D=__DATA__.records,$=id=>document.getElementById(id),valid=x=>x!==null&&Number.isFinite(Number(x)),fmt=(x,d=2)=>valid(x)?Number(x).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—',pct=x=>valid(x)?`${(Number(x)*100).toFixed(1)}%`:'—',cfg={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};const base={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#b8cbe0',family:'Inter,"Microsoft YaHei",sans-serif'},margin:{l:65,r:20,t:22,b:55},hovermode:'x unified',legend:{orientation:'h',y:1.08},xaxis:{gridcolor:'#17304a'},yaxis:{gridcolor:'#17304a',zerolinecolor:'#718096'}};
const TRUE_D=JSON.parse(JSON.stringify(D)),seasonDefs=[['season-import','铂进口量','import'],['season-export','铂出口量','export'],['season-net','铂净进口量','netImport'],['season-consumption','铂表观消费量','consumption']];document.querySelector('.cards').insertAdjacentHTML('beforebegin',`<section class="seasonal-grid">${seasonDefs.map(x=>`<article class="panel"><div class="head"><h2>${x[1]}季节图</h2><span class="muted">吨</span></div><div id="${x[0]}" class="seasonal-chart"></div></article>`).join('')}</section>`);function renderSeasonals(){const colors=['#31d7c5','#f0bd63','#65a7ff','#ff7285','#a78bfa','#fb923c','#22c55e','#e879f9','#38bdf8','#facc15','#94a3b8','#f472b6'];seasonDefs.forEach(([id,title,field])=>{const rows=TRUE_D.filter(x=>!x.tradeMissing&&valid(x[field])),years=[...new Set(rows.map(x=>x.period.slice(0,4)))];const traces=years.map((year,i)=>{const a=rows.filter(x=>x.period.startsWith(year+'-'));return{x:a.map(x=>Number(x.period.slice(5))),y:a.map(x=>x[field]),name:year,mode:'lines+markers',line:{color:colors[i%colors.length],width:year===years.at(-1)?3:1.5},marker:{size:year===years.at(-1)?6:4},hovertemplate:`${year}年%{x}月<br>%{y:.3f}吨<extra></extra>`}});Plotly.react(id,traces,{...base,hovermode:'closest',margin:{l:60,r:18,t:25,b:48},legend:{orientation:'h',y:1.12},xaxis:{...base.xaxis,tickmode:'array',tickvals:[1,2,3,4,5,6,7,8,9,10,11,12],ticktext:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']}},cfg)})}renderSeasonals();
function render(){const a=$('start').value,b=$('end').value,r=D.filter(x=>x.period>=a&&x.period<=b),complete=r.filter(x=>valid(x.consumption)),latest=complete.at(-1);$('cards').innerHTML=[['最新完整月份',latest?.period||'—',''],['当月供给',fmt(latest?.netImport),'吨'],['库存变化',fmt(latest?.inventoryChange),'吨'],['推算消费',fmt(latest?.consumption),'吨']].map(x=>`<article class="card"><div class="label">${x[0]}</div><div class="value">${x[1]}</div><div class="muted">${x[2]}</div></article>`).join('');Plotly.react('flow',[{x:r.map(x=>x.period),y:r.map(x=>x.netImport),name:'净进口/供给',mode:'lines+markers',line:{color:'#31d7c5',width:2.5}},{x:r.map(x=>x.period),y:r.map(x=>x.consumption),name:'推算消费',mode:'lines+markers',line:{color:'#f0bd63',width:2.5}}],base,cfg);Plotly.react('inventory',[{x:r.map(x=>x.period),y:r.map(x=>x.inventory),name:'月末库存',type:'bar',marker:{color:'#65a7ff'},customdata:r.map(x=>x.inventoryDate),hovertemplate:'%{x}<br>%{y:.3f}吨<br>数据日 %{customdata}<extra></extra>'}],{...base,showlegend:false,yaxis:{...base.yaxis,rangemode:'tozero'}},cfg);Plotly.react('change',[{x:r.map(x=>x.period),y:r.map(x=>x.inventoryChange),name:'库存变化',type:'bar',marker:{color:r.map(x=>x.inventoryChange>=0?'#ff7285':'#31d7c5')},hovertemplate:'%{x}<br>%{y:.3f}吨<extra></extra>'}],{...base,showlegend:false},cfg);$('rows').innerHTML=[...r].reverse().map(x=>`<tr><td>${x.period}</td><td>${fmt(x.import,3)}</td><td>${pct(x.importYoY)}</td><td>${pct(x.importCumYoY)}</td><td>${fmt(x.export,3)}</td><td>${pct(x.exportYoY)}</td><td>${pct(x.exportCumYoY)}</td><td>${fmt(x.netImport,3)}</td><td>${pct(x.netImportYoY)}</td><td>${pct(x.netImportCumYoY)}</td><td>${pct(x.netImportMoM)}</td><td>${fmt(x.inventory,3)}</td><td>${fmt(x.inventoryChange,3)}</td><td>${fmt(x.consumption,3)}</td><td>${pct(x.consumptionYoY)}</td><td>${pct(x.consumptionCumYoY)}</td></tr>`).join('');$('status').textContent=`${r.length}个月 · ${complete.length}个月可计算消费`}
document.querySelector('.table-wrap').insertAdjacentHTML('beforebegin','<section class="panel annual-wrap"><table class="annual-table"><thead><tr class="balance-title"><th colspan="11">铂年度供需平衡表</th></tr><tr class="group-head"><th rowspan="2">年份</th><th colspan="2">铂进口量</th><th colspan="2">铂出口量</th><th colspan="2">铂净进口量</th><th colspan="2">铂库存</th><th colspan="2">铂表观消费</th></tr><tr class="sub-head"><th>海关</th><th>环比</th><th>海关</th><th>环比</th><th>海关</th><th>环比</th><th>合计</th><th>变化</th><th>合计</th><th>环比</th></tr></thead><tbody id="annual-rows"></tbody></table></section>');
function renderAnnual(){const years=[...new Set(D.map(x=>x.period.slice(0,4)))].reverse(),sum=(a,f)=>{const v=a.map(x=>x[f]).filter(valid);return v.length?v.reduce((s,x)=>s+Number(x),0):null},last=(a,f)=>[...a].reverse().find(x=>valid(x[f]))?.[f]??null,ratio=(c,p)=>valid(c)&&valid(p)&&Number(p)!==0?Number(c)/Number(p)-1:null,rows=years.map(year=>{const all=D.filter(x=>x.period.startsWith(year+'-')),upto=Math.max(...all.filter(x=>valid(x.netImport)).map(x=>Number(x.period.slice(5)))),cur=all.filter(x=>Number(x.period.slice(5))<=upto),prev=D.filter(x=>x.period.startsWith((Number(year)-1)+'-')&&Number(x.period.slice(5))<=upto),im=sum(cur,'import'),ex=sum(cur,'export'),ni=sum(cur,'netImport'),co=sum(cur,'consumption'),pim=sum(prev,'import'),pex=sum(prev,'export'),pni=sum(prev,'netImport'),pco=sum(prev,'consumption'),iv=last(all,'inventory'),piv=last(D.filter(x=>x.period.startsWith((Number(year)-1)+'-')),'inventory');return{year,im,ex,ni,co,iv,ic:valid(iv)&&valid(piv)?Number(iv)-Number(piv):null,imy:ratio(im,pim),exy:ratio(ex,pex),niy:ratio(ni,pni),coy:ratio(co,pco)}});$('annual-rows').innerHTML=rows.map(x=>`<tr><td>${x.year}</td><td>${fmt(x.im,3)}</td><td>${pct(x.imy)}</td><td>${fmt(x.ex,3)}</td><td>${pct(x.exy)}</td><td>${fmt(x.ni,3)}</td><td>${pct(x.niy)}</td><td>${fmt(x.iv,3)}</td><td>${fmt(x.ic,3)}</td><td>${fmt(x.co,3)}</td><td>${pct(x.coy)}</td></tr>`).join('')}
const ESTIMATE_KEY='pt-balance-user-estimates-v1';let estimates={};try{estimates=JSON.parse(localStorage.getItem(ESTIMATE_KEY)||'{}')}catch(e){estimates={}}D.forEach(x=>{x.baseInventory=x.inventory;x.baseInventoryChange=x.inventoryChange});function applyUserEstimates(){let previousInventory=0;D.forEach(x=>{if(x.tradeMissing){const e=estimates[x.period]||{},ni=e.netImport===''||e.netImport===undefined?null:Number(e.netImport),co=e.consumption===''||e.consumption===undefined?null:Number(e.consumption);x.netImport=Number.isFinite(ni)?ni:null;x.consumption=Number.isFinite(co)?co:null;if(valid(x.netImport)&&valid(x.consumption)){x.inventoryChange=Number(x.netImport)-Number(x.consumption);x.inventory=previousInventory+x.inventoryChange;x.userEstimated=true}else{x.inventoryChange=x.baseInventoryChange;x.inventory=x.baseInventory;x.userEstimated=false}}if(valid(x.inventory))previousInventory=Number(x.inventory)})}function estimateInput(x,field){const value=estimates[x.period]?.[field]??'';return `<input class="estimate-input" type="number" step="0.001" value="${value}" placeholder="用户填写" onchange="saveEstimate('${x.period}','${field}',this.value)">`}window.saveEstimate=function(period,field,value){estimates[period]??={};estimates[period][field]=value;localStorage.setItem(ESTIMATE_KEY,JSON.stringify(estimates));applyUserEstimates();renderAnnual();render()};applyUserEstimates();
const monthlyRender=render;render=function(){monthlyRender();const a=$('start').value,b=$('end').value,r=D.filter(x=>x.period>=a&&x.period<=b);$('rows').innerHTML=[...r].reverse().map((x,i,arr)=>`<tr class="${i>0&&x.period.slice(0,4)!==arr[i-1].period.slice(0,4)?'year-start':''}"><td>${x.period}</td><td>${fmt(x.import,3)}</td><td>${pct(x.importYoY)}</td><td>${pct(x.importCumYoY)}</td><td>${fmt(x.export,3)}</td><td>${pct(x.exportYoY)}</td><td>${pct(x.exportCumYoY)}</td><td>${x.tradeMissing?estimateInput(x,'netImport'):fmt(x.netImport,3)}</td><td>${pct(x.netImportYoY)}</td><td>${pct(x.netImportCumYoY)}</td><td>${pct(x.netImportMoM)}</td><td class="${x.userEstimated?'estimated':''}">${fmt(x.inventory,3)}</td><td class="${x.userEstimated?'estimated':''}">${fmt(x.inventoryChange,3)}</td><td>${x.tradeMissing?estimateInput(x,'consumption'):fmt(x.consumption,3)}</td><td>${pct(x.consumptionYoY)}</td><td>${pct(x.consumptionCumYoY)}</td></tr>`).join('')};renderAnnual();
const unfilteredSeasonals=renderSeasonals;renderSeasonals=function(){const start=$('start').value||TRUE_D[0].period,end=$('end').value||TRUE_D.at(-1).period,flags=TRUE_D.map(x=>x.tradeMissing);TRUE_D.forEach(x=>{if(x.period<start||x.period>end)x.tradeMissing=true});unfilteredSeasonals();TRUE_D.forEach((x,i)=>x.tradeMissing=flags[i])};
const periods=D.map(x=>x.period),first=periods[0],last=periods.at(-1),def=first>'2021-01'?first:'2021-01';$('start').min=first;$('start').max=last;$('start').value=def;$('end').min=first;$('end').max=last;$('end').value=last;$('apply').onclick=()=>{render();renderSeasonals()};render();renderSeasonals();
</script></body></html>'''


if __name__ == "__main__":
    PTBalanceHTMLGenerator(
        "data/pt_cn_import.csv",
        "data/pt_cn_export.csv",
        "data/gfex_PT_warehouse_receipt.csv",
    ).generate()
