from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


class PTTradeHTMLGenerator:
    """Generate the interactive China platinum import/export dashboard."""

    def __init__(self, import_csv, export_csv, template_file=None):
        self.import_csv = Path(import_csv)
        self.export_csv = Path(export_csv)
        self.template_file = (
            Path(template_file)
            if template_file
            else Path(__file__).with_name("pt_trade_template.html")
        )

    @staticmethod
    def _load_file(path):
        frame = pd.read_csv(path, encoding="gb18030", dtype={"数据年月": str})
        frame["数量（吨）"] = pd.to_numeric(
            frame["数量（吨）"], errors="coerce"
        ).fillna(0)
        frame["period"] = pd.to_datetime(
            frame["数据年月"], format="%Y%m", errors="coerce"
        )
        frame = frame.dropna(subset=["period"])
        if frame.empty:
            raise ValueError(f"进出口文件没有有效数据：{path}")
        return frame

    @staticmethod
    def _safe_ratio(current, previous):
        if previous is None or pd.isna(previous) or previous == 0:
            return None
        return float(current / previous - 1)

    def _monthly_total(self, imports, exports, periods):
        imp = imports.groupby("period")["数量（吨）"].sum().reindex(
            periods, fill_value=0
        )
        exp = exports.groupby("period")["数量（吨）"].sum().reindex(
            periods, fill_value=0
        )
        series = {"import": imp, "export": exp, "netImport": imp - exp}
        rows = []
        for period in periods:
            row = {"period": period.strftime("%Y-%m")}
            for key, values in series.items():
                current = float(values.loc[period])
                previous = values.get(period - pd.DateOffset(years=1), np.nan)
                current_ytd = float(
                    values[
                        (values.index.year == period.year)
                        & (values.index.month <= period.month)
                    ].sum()
                )
                previous_ytd = float(
                    values[
                        (values.index.year == period.year - 1)
                        & (values.index.month <= period.month)
                    ].sum()
                )
                row[key] = {
                    "customs": current,
                    "yoy": self._safe_ratio(current, previous),
                    "cumYoy": self._safe_ratio(current_ytd, previous_ytd),
                }
            rows.append(row)
        return list(reversed(rows))

    def _annual_total(self, monthly_rows, latest_month):
        monthly = {row["period"]: row for row in monthly_rows}
        years = sorted({int(period[:4]) for period in monthly})
        rows = []
        for year in years:
            months = latest_month if year == years[-1] else 12
            row = {"period": str(year)}
            for key in ("import", "export", "netImport"):
                current = sum(
                    monthly[f"{year}-{month:02d}"][key]["customs"]
                    for month in range(1, months + 1)
                    if f"{year}-{month:02d}" in monthly
                )
                previous = sum(
                    monthly[f"{year - 1}-{month:02d}"][key]["customs"]
                    for month in range(1, months + 1)
                    if f"{year - 1}-{month:02d}" in monthly
                )
                yoy = self._safe_ratio(current, previous)
                row[key] = {"customs": current, "yoy": yoy, "cumYoy": yoy}
            rows.append(row)
        return list(reversed(rows))

    @staticmethod
    def _dimension_table(imports, exports, periods, column):
        imp = imports.pivot_table(
            index="period",
            columns=column,
            values="数量（吨）",
            aggfunc="sum",
            fill_value=0,
        ).reindex(periods, fill_value=0)
        exp = exports.pivot_table(
            index="period",
            columns=column,
            values="数量（吨）",
            aggfunc="sum",
            fill_value=0,
        ).reindex(periods, fill_value=0)
        dimensions = sorted(set(imp.columns) | set(exp.columns))
        imp = imp.reindex(columns=dimensions, fill_value=0)
        exp = exp.reindex(columns=dimensions, fill_value=0)
        order = sorted(
            dimensions,
            key=lambda item: float(imp[item].sum() + exp[item].sum()),
            reverse=True,
        )
        rows = []
        for period in reversed(periods):
            values = []
            for item in order:
                imported = float(imp.at[period, item])
                exported = float(exp.at[period, item])
                values.append([imported, exported, imported - exported])
            rows.append({"period": period.strftime("%Y-%m"), "values": values})
        return {"dimensions": order, "rows": rows}

    @staticmethod
    def _annual_dimension(monthly, latest_month):
        years = sorted({int(row["period"][:4]) for row in monthly["rows"]})
        by_period = {row["period"]: row for row in monthly["rows"]}
        rows = []
        for year in reversed(years):
            months = latest_month if year == years[-1] else 12
            values = []
            for index in range(len(monthly["dimensions"])):
                imported = exported = 0.0
                for month in range(1, months + 1):
                    row = by_period.get(f"{year}-{month:02d}")
                    if row:
                        imported += row["values"][index][0]
                        exported += row["values"][index][1]
                values.append([imported, exported, imported - exported])
            rows.append({"period": str(year), "values": values})
        return {"dimensions": monthly["dimensions"], "rows": rows}

    def _build_payload(self):
        imports = self._load_file(self.import_csv)
        exports = self._load_file(self.export_csv)
        start = min(imports["period"].min(), exports["period"].min())
        end = max(imports["period"].max(), exports["period"].max())
        periods = pd.date_range(start, end, freq="MS")
        latest_month = int(end.month)

        monthly = {"total": self._monthly_total(imports, exports, periods)}
        for key, column in {
            "country": "贸易伙伴名称",
            "region": "注册地名称",
            "trade": "贸易方式名称",
        }.items():
            monthly[key] = self._dimension_table(
                imports, exports, periods, column
            )

        annual = {"total": self._annual_total(monthly["total"], latest_month)}
        for key in ("country", "region", "trade"):
            annual[key] = self._annual_dimension(monthly[key], latest_month)

        return {
            "monthly": monthly,
            "annual": annual,
            "meta": {
                "start": start.strftime("%Y-%m"),
                "end": end.strftime("%Y-%m"),
                "latestMonth": latest_month,
            },
        }

    def generate(self, output_file):
        if not self.template_file.exists():
            raise FileNotFoundError(f"进出口HTML模板不存在：{self.template_file}")
        payload = self._build_payload()
        template = self.template_file.read_text(encoding="utf-8")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        html = template.replace("__DATA__", encoded.replace("</", "<\\/"))
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        print(f"China precious-metal trade dashboard generated: {output}")
        return output
