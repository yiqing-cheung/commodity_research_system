import os
import pandas as pd
import akshare as ak
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib

import plotly.graph_objects as go

# 中文字体设置
matplotlib.rcParams['font.sans-serif'] = [
    'SimHei'
]

# 解决负号显示问题
matplotlib.rcParams['axes.unicode_minus'] = False

from data_collection.gfex import (
    fetch_gfex_warehouse_receipt
)

class GFEXInventory:


    def __init__(
        self,
        data_folder="data"
    ):
        """
        Parameters
        ----------
        data_folder:
            数据保存目录
        """

        self.data_folder = data_folder

    # =====================================================
    # 根据品种生成文件路径
    # =====================================================
    def get_csv_path(
        self,
        metal
    ):
        """
        根据品种返回CSV路径

        PT:
            data/gfex_PT_warehouse_receipt.csv

        PD:
            data/gfex_PD_warehouse_receipt.csv

        """

        metal = metal.upper()
        return os.path.join(
            self.data_folder,
            f"gfex_{metal}_warehouse_receipt.csv"
        )

    # =====================================================
    # 获取交易日
    # =====================================================

    def get_trade_dates(
        self,
        start_date,
        end_date
    ):

        """
        获取交易日

        """

        calendar = ak.tool_trade_date_hist_sina()
        calendar["trade_date"] = pd.to_datetime(
            calendar["trade_date"]
        )

        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        dates = calendar[(calendar["trade_date"] >= start)&(calendar["trade_date"] <= end)]

        return [
            x.strftime("%Y%m%d")
            for x in dates["trade_date"]
        ]

    # =====================================================
    # 获取单日仓单
    # =====================================================

    def get_single_day(self, date, metal):
        """获取某一天某品种仓单
        metal:
            PT / PD
        """
        metal = metal.upper()
        data = ak.futures_gfex_warehouse_receipt(date=date)
        if metal not in data:
            return pd.DataFrame()
        df = data[metal].copy()
        df["date"] = date
        df["metal"] = metal
        df = df.rename(columns={
            "仓库/分库":"warehouse",
            "昨日仓单量":"yesterday_receipt",
            "今日仓单量":"today_receipt",
            "增减":"change"
        })
        df['change'] = df['today_receipt'] - df['yesterday_receipt']
        return df[["date","metal","warehouse","yesterday_receipt","today_receipt","change"]]

    # =====================================================
    # 保存CSV
    # =====================================================

    def save_data(self, df, metal):
        path = self.get_csv_path(metal)
        os.makedirs(self.data_folder, exist_ok=True)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print("Saved:", path)

    # =====================================================
    # 函数1：
    # 获取指定时间段历史数据
    # =====================================================

    def download_history(
        self,
        start_date,
        end_date,
        metal
    ):

        """
        下载历史仓单
        """
        metal = metal.upper()
        all_data = []
        dates = self.get_trade_dates(
            start_date,
            end_date
        )

        for date in dates:
            print(f"Downloading {metal} {date}")
            try:
                df = self.get_single_day(date, metal)
                if not df.empty:
                    all_data.append(df)
            except Exception as e:
                print(date,e)

        if not all_data:
            print("No data")
            return

        new_history = pd.concat(all_data,ignore_index=True)
        path = self.get_csv_path(metal)

        # 如果已有历史
        if os.path.exists(path):
            old = pd.read_csv(path)
            new_history = pd.concat([old,new_history],ignore_index=True)

        # 日期+仓库去重
        new_history = new_history.drop_duplicates(
            subset=["date","warehouse"],
            keep="last"
        )

        self.save_data(new_history,metal)
    # =====================================================
    # 函数2：
    # 更新某一天数据
    # =====================================================
    def update_daily(
        self,
        metal,
        date=None,
        source="akshare",
    ):
        """
        更新某一天的仓单数据。

        Parameters
        ----------
        metal:
            品种代码，支持：
            SI、LC、PS、PT、PD。

        date:
            查询日期，格式 YYYYMMDD。
            默认使用当天日期。

        source:
            akshare:
                默认先使用 AkShare。
                如果 AkShare 报错或没有数据，
                自动回退到广期所接口。

            gfex:
                跳过 AkShare，直接请求广期所。
        """

        supported_metals = {
            "SI",
            "LC",
            "PS",
            "PT",
            "PD",
        }

        metal = str(metal).upper().strip()
        source = str(source).lower().strip()

        if metal not in supported_metals:
            raise ValueError(
                f"不支持的品种：{metal}；"
                f"目前支持：{', '.join(sorted(supported_metals))}"
            )

        if source not in {"akshare", "gfex"}:
            raise ValueError(
                "source 只能是 'akshare' 或 'gfex'"
            )

        if date is None:
            date = datetime.today().strftime("%Y%m%d")
        else:
            date = str(date).strip()

            # 兼容 YYYY-MM-DD
            try:
                date = datetime.strptime(
                    date,
                    "%Y%m%d",
                ).strftime("%Y%m%d")
            except ValueError:
                try:
                    date = datetime.strptime(
                        date,
                        "%Y-%m-%d",
                    ).strftime("%Y%m%d")
                except ValueError as error:
                    raise ValueError(
                        f"日期格式错误：{date}"
                    ) from error

        new_data = pd.DataFrame()
        actual_source = source

        # =========================================
        # 1. 默认优先使用 AkShare
        # =========================================

        if source == "akshare":
            print(
                f"Trying AkShare: {metal} {date}"
            )

            try:
                new_data = self.get_single_day(
                    date=date,
                    metal=metal,
                )
            except Exception as error:
                print(
                    f"AkShare failed: "
                    f"{metal} {date}: {error}"
                )
                new_data = pd.DataFrame()

            # AkShare 当日数据尚未更新时，回退广期所
            if new_data.empty:
                print(
                    f"AkShare has no data, "
                    f"switching to GFEX: "
                    f"{metal} {date}"
                )

                actual_source = "gfex"

                new_data = (
                    fetch_gfex_warehouse_receipt(
                        date=date,
                        metal=metal,
                    )
                )

        # =========================================
        # 2. 直接使用广期所
        # =========================================

        elif source == "gfex":
            print(
                f"Downloading from GFEX: "
                f"{metal} {date}"
            )

            new_data = (
                fetch_gfex_warehouse_receipt(
                    date=date,
                    metal=metal,
                )
            )

        # =========================================
        # 3. 判断是否取得数据
        # =========================================

        if new_data.empty:
            print(
                f"No data: {metal} {date}"
            )
            return

        # 确保字段类型统一
        new_data["date"] = (
            new_data["date"].astype(str)
        )

        new_data["metal"] = (
            new_data["metal"]
            .astype(str)
            .str.upper()
        )

        path = self.get_csv_path(metal)

        # =========================================
        # 4. 合并历史数据
        # =========================================

        if os.path.exists(path):
            old = pd.read_csv(path)

            old["date"] = old["date"].astype(str)

            if "metal" not in old.columns:
                old["metal"] = metal

            old["metal"] = (
                old["metal"]
                .astype(str)
                .str.upper()
            )

            # 删除历史文件中当天数据。
            # 这样当 AkShare 后续更新，或手动重新抓取时，
            # 可以用最新数据完整覆盖当天旧数据。
            old = old[
                ~(
                    (old["date"] == date)
                    & (old["metal"] == metal)
                )
            ]

            df = pd.concat(
                [old, new_data],
                ignore_index=True,
            )

        else:
            df = new_data.copy()

        # =========================================
        # 5. 去重并排序
        # =========================================

        df = df.drop_duplicates(
            subset=[
                "date",
                "metal",
                "warehouse",
            ],
            keep="last",
        )

        df = df.sort_values(
            [
                "date",
                "warehouse",
            ]
        ).reset_index(drop=True)

        # =========================================
        # 6. 保存数据
        # =========================================

        self.save_data(
            df=df,
            metal=metal,
        )

        print(
            f"{metal} {date} updated "
            f"using {actual_source}"
        )

class InventoryAnalyzer:
    def __init__(
        self,
        file_path,
        metal
    ):

        self.file_path = file_path
        self.metal = metal

        # 三个仓库定义为仓库仓单
        self.warehouse_list = [
            "中工美上海虹桥",
            "外运华东上海虹桥",
            "深圳威豹",
            "中储吴淞",
        ]

    # =========================================
    # 读取数据
    # =========================================

    def load_data(self):

        df = pd.read_csv(self.file_path)

        # 将 YYYYMMDD 转换为日期
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")

        df = df.sort_values("date")
        self.df = df

        return df

    # =========================================
    # 通用变化计算函数
    # =========================================

    def calculate_change(
        self,
        df,
        column
    ):
        """
        计算：
        1. 日变化
        2. 月累计变化

        column:
            库存字段

        返回:
            change
            monthly_change
        """

        # 日变化
        daily_change = (df[column].diff())

        # 月份
        month = (df["date"].dt.to_period("M"))
        monthly_base = []
        for m in month.unique():
            current_month = df[month == m]
            first_date = (current_month["date"].iloc[0])

            # 找上个月最后交易日库存
            previous = df[df["date"] < first_date]

            if len(previous) > 0:
                base = (previous[column].iloc[-1])
            else:
                # 如果没有历史数据
                # 第一日作为基准
                base = (current_month[column].iloc[0])

            monthly_base.extend([base for _ in range(len(current_month))])

        monthly_change = (df[column]-pd.Series(monthly_base,index=df.index))

        return (daily_change,monthly_change)

    # =========================================
    # 生成库存分析表
    # =========================================

    def calculate_inventory(self):
        df = self.df.copy()
        # --------------------------
        # 总仓单
        # --------------------------

        total = (df.groupby("date")["today_receipt"].sum().reset_index())
        total.columns = ["date","仓单量"]

        # --------------------------
        # 仓库仓单
        # --------------------------
        warehouse = (
            df[df["warehouse"].isin(self.warehouse_list)].groupby("date")["today_receipt"].sum().reset_index()
        )
        warehouse.columns = ["date","仓库仓单量"]

        result = total.merge(warehouse,on="date",how="left")
        result["仓库仓单量"] = (result["仓库仓单量"].fillna(0))

        # --------------------------
        # 厂库
        # --------------------------
        result["厂库仓单量"] = (result["仓单量"]-result["仓库仓单量"])

        # --------------------------
        # 三类库存计算变化
        # --------------------------
        columns = ["仓单量","仓库仓单量","厂库仓单量"]

        for col in columns:
            daily, monthly = self.calculate_change(result,col)
            result[f"{col.replace('量','')}变化量"] = daily
            result[f"{col.replace('量','')}累计变化量"] = monthly

        # 调整列名
        result = result[
            [
            "date",
            "仓单量",
            "仓单变化量",
            "仓单累计变化量",
            "仓库仓单量",
            "仓库仓单变化量",
            "仓库仓单累计变化量",
            "厂库仓单量",
            "厂库仓单变化量",
            "厂库仓单累计变化量"
            ]
        ]

        result = result.rename(columns={"date":"日期"})
        self.result = result

        return result

    # =========================================
    # 保存分析表
    # =========================================

    def save_table(
        self,
        path
    ):
        self.result.to_csv(path,index=False,encoding="utf-8-sig")

    # =========================================
    # 季节图
    # =========================================

    def plot_seasonal_chart(self, column, save_path):
        df = self.result.copy()
        df["month"] = df["日期"].dt.month
        df["day"] = df["日期"].dt.day
        plt.figure(figsize=(12, 6))
        for month, data in df.groupby("month"):
            plt.plot(data["day"], data[column], marker="o", markersize=4, label=f"{month}")
            last_row = data.iloc[-1]
            plt.annotate(f"{last_row[column]:,.0f}", xy=(last_row["day"], last_row[column]), xytext=(5, 5), textcoords="offset points", fontsize=8)
        plt.xticks(range(1, 32))
        plt.xlabel("Day")
        plt.ylabel(column)
        plt.title(f"{self.metal} {column}")
        plt.legend(title="Month")
        plt.grid(True)
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close()

    def plot_seasonal_chart_interactive(self, column, save_path):
        """生成交互式季节图

        Parameters
        ----------
        column:
            指标名称，例如: 仓单量、仓库仓单量、厂库仓单量
        save_path:
            html保存路径，例如: output/PT_inventory_seasonal.html
        """
        df = self.result.copy()
        df["month"] = df["日期"].dt.month
        df["day"] = df["日期"].dt.day
        fig = go.Figure()
        for month, data in df.groupby("month"):
            last_row = data.iloc[-1]
            fig.add_trace(go.Scatter(x=data["day"], y=data[column], mode="lines+markers", name=f"{month}月", marker=dict(size=6), hovertemplate="日期: %{x}日<br>库存: %{y:,.0f}<extra></extra>"))
            fig.add_annotation(x=last_row["day"], y=last_row[column], text=f"{last_row[column]:,.0f}", showarrow=True, arrowhead=1, ax=20, ay=-20)
        fig.update_layout(title=f"{self.metal} {column} Seasonal Chart", xaxis=dict(title="Day", tickmode="linear", tick0=1, dtick=1), yaxis=dict(title=column), hovermode="closest", width=1000, height=600, legend_title="Month")
        fig.write_html(save_path)