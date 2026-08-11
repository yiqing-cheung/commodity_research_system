"""Analysis and charting for NYMEX platinum/palladium inventory data."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go


# One troy ounce = 31.1035 grams = 31.1035 / 1,000,000 metric tonnes.
OUNCE_TO_TONNE = 31.1035 / 1_000_000

DEFAULT_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)

REQUIRED_COLUMNS = {
    "date",
    "pd_total_oz",
    "pt_total_oz",
    "pd_registered_oz",
    "pt_registered_oz",
    "pd_delivery_contracts",
    "pt_delivery_contracts",
}

SEASONAL_METRICS = {
    "pt_inventory": {
        "column": "pt_total_tonnes",
        "title": "NYMEX铂金库存季节图",
        "ylabel": "库存（吨）",
    },
    "pd_inventory": {
        "column": "pd_total_tonnes",
        "title": "NYMEX钯金库存季节图",
        "ylabel": "库存（吨）",
    },
    "pt_registered": {
        "column": "pt_registered_tonnes",
        "title": "NYMEX铂金注册仓单季节图",
        "ylabel": "注册仓单（吨）",
    },
    "pd_registered": {
        "column": "pd_registered_tonnes",
        "title": "NYMEX钯金注册仓单季节图",
        "ylabel": "注册仓单（吨）",
    },
}

YEAR_COLORS = {
    2021: "#64748B",
    2022: "#8B5CF6",
    2023: "#3B82F6",
    2024: "#10B981",
    2025: "#F59E0B",
    2026: "#EF4444",
}


matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


class NYMEXInventoryAnalyzer:
    def __init__(
        self,
        file_path: str | Path,
        years=DEFAULT_YEARS,
    ) -> None:
        self.file_path = Path(file_path)
        self.years = tuple(int(year) for year in years)
        self.df: pd.DataFrame | None = None

    def load_data(self) -> pd.DataFrame:
        if not self.file_path.exists():
            raise FileNotFoundError(f"NYMEX CSV不存在：{self.file_path}")

        frame = pd.read_csv(self.file_path, encoding="utf-8-sig")
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError("NYMEX CSV缺少字段：" + ", ".join(missing))

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).copy()

        numeric_columns = sorted(REQUIRED_COLUMNS - {"date"})
        frame[numeric_columns] = frame[numeric_columns].apply(
            pd.to_numeric,
            errors="coerce",
        )

        frame = (
            frame.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )

        frame["pt_total_tonnes"] = frame["pt_total_oz"] * OUNCE_TO_TONNE
        frame["pd_total_tonnes"] = frame["pd_total_oz"] * OUNCE_TO_TONNE
        frame["pt_registered_tonnes"] = (
            frame["pt_registered_oz"] * OUNCE_TO_TONNE
        )
        frame["pd_registered_tonnes"] = (
            frame["pd_registered_oz"] * OUNCE_TO_TONNE
        )
        frame["year"] = frame["date"].dt.year
        frame["seasonal_date"] = pd.to_datetime(
            "2000-" + frame["date"].dt.strftime("%m-%d"),
            errors="coerce",
        )

        self.df = frame
        return frame

    def _require_data(self) -> pd.DataFrame:
        if self.df is None:
            return self.load_data()
        return self.df

    def _seasonal_data(self, metric: str) -> tuple[pd.DataFrame, dict]:
        if metric not in SEASONAL_METRICS:
            raise ValueError(
                f"不支持的季节图指标：{metric}；"
                f"可选值：{', '.join(SEASONAL_METRICS)}"
            )
        frame = self._require_data()
        data = frame[frame["year"].isin(self.years)].copy()
        data = data.dropna(
            subset=["seasonal_date", SEASONAL_METRICS[metric]["column"]]
        )
        if data.empty:
            raise ValueError(f"{metric}在{self.years}没有可画数据")
        return data, SEASONAL_METRICS[metric]

    def plot_seasonal_png(self, metric: str, output_path: str | Path) -> Path:
        data, config = self._seasonal_data(metric)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, axis = plt.subplots(figsize=(13, 6.8))
        for year in self.years:
            yearly = data[data["year"] == year].sort_values("seasonal_date")
            if yearly.empty:
                continue
            axis.plot(
                yearly["seasonal_date"],
                yearly[config["column"]],
                label=str(year),
                color=YEAR_COLORS.get(year),
                linewidth=2.0 if year != max(self.years) else 2.8,
                alpha=0.92,
            )

        axis.set_title(config["title"], fontsize=17, fontweight="bold", pad=14)
        axis.set_xlabel("月-日")
        axis.set_ylabel(config["ylabel"])
        axis.set_xlim(pd.Timestamp("2000-01-01"), pd.Timestamp("2000-12-31"))
        axis.xaxis.set_major_locator(mdates.MonthLocator())
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        axis.grid(axis="y", color="#CBD5E1", linewidth=0.8, alpha=0.65)
        axis.spines[["top", "right"]].set_visible(False)
        axis.legend(title="年份", ncol=6, frameon=False, loc="upper center")
        fig.tight_layout()
        fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return output_path

    def plot_seasonal_html(self, metric: str, output_path: str | Path) -> Path:
        data, config = self._seasonal_data(metric)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        figure = go.Figure()
        for year in self.years:
            yearly = data[data["year"] == year].sort_values("seasonal_date")
            if yearly.empty:
                continue
            figure.add_trace(
                go.Scatter(
                    x=yearly["seasonal_date"],
                    y=yearly[config["column"]],
                    name=str(year),
                    mode="lines",
                    line={
                        "color": YEAR_COLORS.get(year),
                        "width": 3 if year == max(self.years) else 2,
                    },
                    hovertemplate=(
                        "%{fullData.name}　%{y:.3f} 吨"
                        "<extra></extra>"
                    ),
                )
            )

        figure.update_layout(
            title=config["title"],
            template="plotly_white",
            width=1100,
            height=620,
            hovermode="x unified",
            legend_title="年份",
            xaxis={
                "title": "月-日",
                "tickformat": "%m-%d",
                "hoverformat": "%m-%d",
                "dtick": "M1",
                "range": ["2000-01-01", "2000-12-31"],
            },
            yaxis={"title": config["ylabel"], "rangemode": "tozero"},
            margin={"l": 80, "r": 30, "t": 80, "b": 70},
        )
        figure.write_html(
            output_path,
            include_plotlyjs="cdn",
            full_html=True,
        )
        return output_path

    def _recent_delivery_data(self) -> pd.DataFrame:
        frame = self._require_data()
        latest = frame["date"].max()
        start = latest - pd.DateOffset(years=1)
        data = frame.loc[
            frame["date"].between(start, latest),
            ["date", "pt_delivery_contracts", "pd_delivery_contracts"],
        ].copy()
        data[["pt_delivery_contracts", "pd_delivery_contracts"]] = data[
            ["pt_delivery_contracts", "pd_delivery_contracts"]
        ].fillna(0)
        if data.empty:
            raise ValueError("最近一年没有交割量数据")
        return data

    def plot_delivery_png(self, output_path: str | Path) -> Path:
        data = self._recent_delivery_data()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, axis = plt.subplots(figsize=(14, 6.8))
        axis.plot(
            data["date"],
            data["pt_delivery_contracts"],
            color="#3B82F6",
            linewidth=2.0,
            label="铂金交割量",
        )
        axis.plot(
            data["date"],
            data["pd_delivery_contracts"],
            color="#F59E0B",
            linewidth=2.0,
            label="钯金交割量",
        )
        axis.set_title("NYMEX铂钯最近一年每日交割量", fontsize=17, fontweight="bold")
        axis.set_xlabel("日期")
        axis.set_ylabel("交割量（手）")
        axis.xaxis.set_major_locator(mdates.MonthLocator())
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        axis.tick_params(axis="x", rotation=35)
        axis.grid(axis="y", color="#CBD5E1", linewidth=0.8, alpha=0.65)
        axis.spines[["top", "right"]].set_visible(False)
        axis.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return output_path

    def plot_delivery_html(self, output_path: str | Path) -> Path:
        data = self._recent_delivery_data()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["pt_delivery_contracts"],
                name="铂金交割量",
                mode="lines",
                line={"color": "#3B82F6", "width": 2},
                hovertemplate="铂金　%{y:,.0f} 手<extra></extra>",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["pd_delivery_contracts"],
                name="钯金交割量",
                mode="lines",
                line={"color": "#F59E0B", "width": 2},
                hovertemplate="钯金　%{y:,.0f} 手<extra></extra>",
            )
        )
        figure.update_layout(
            title="NYMEX铂钯最近一年每日交割量",
            template="plotly_white",
            width=1200,
            height=620,
            hovermode="x unified",
            xaxis={
                "title": "日期",
                "hoverformat": "%Y-%m-%d",
                "rangeslider": {"visible": True},
            },
            yaxis={"title": "交割量（手）", "rangemode": "tozero"},
            margin={"l": 80, "r": 30, "t": 80, "b": 80},
        )
        figure.write_html(
            output_path,
            include_plotlyjs="cdn",
            full_html=True,
        )
        return output_path
