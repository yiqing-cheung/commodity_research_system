from unittest import result

import pandas as pd
import os

class ReportGenerator:
    def __init__(
        self,
        metal,
        analysis_file,
        inventory_file,
        chart_folder="charts"
    ):

        self.metal = metal.upper()
        self.analysis_file = analysis_file
        self.inventory_file = inventory_file
        self.chart_folder = chart_folder

    # ===============================
    # 读取数据
    # ===============================

    def load_data(self):
        self.analysis = pd.read_csv(
            self.analysis_file
        )

        self.inventory = pd.read_csv(
            self.inventory_file
        )

        # 日期转换
        self.analysis["日期"] = pd.to_datetime(
            self.analysis["日期"]
        )

        self.inventory["date"] = pd.to_datetime(
            self.inventory["date"].astype(str),
            format="%Y%m%d"
        )

    # ===============================
    # 数字格式
    # ===============================

    def format_number(
        self,
        x
    ):
        if pd.isna(x):
            return "-"

        if x > 0:
            return f"+{x:,.0f}"

        return f"{x:,.0f}"

    # ===============================
    # 截取库存表
    # ===============================

    def generate_inventory_table(
        self,
        start_day,
        end_day
    ):

        df = self.analysis.copy()

        df = df[
            (df["日期"] >= start_day)
            &
            (df["日期"] <= end_day)
        ]

        table = "|日期|仓单量|仓单变化量|仓单累计变化量|仓库仓单量|仓库变化量|仓库累计变化量|厂库仓单量|厂库变化量|厂库累计变化量|\n"
        table += "|-|-:|-:|-:|-:|-:|-:|-:|-:|-:|\n"

        for _, row in df.iterrows():

            table += (
                f"|{row['日期'].strftime('%Y-%m-%d')}|"
                f"{row['仓单量']:,.0f}|"
                f"{self.format_number(row['仓单变化量'])}|"
                f"{self.format_number(row['仓单累计变化量'])}|"
                f"{row['仓库仓单量']:,.0f}|"
                f"{self.format_number(row['仓库仓单变化量'])}|"
                f"{self.format_number(row['仓库仓单累计变化量'])}|"
                f"{row['厂库仓单量']:,.0f}|"
                f"{self.format_number(row['厂库仓单变化量'])}|"
                f"{self.format_number(row['厂库仓单累计变化量'])}|\n"
            )

        return table

    # ===============================
    # 插入交互图
    # ===============================

    def generate_chart_section(self):
        charts = [
            ("仓单量季节图", "inventory"),
            ("仓库仓单量季节图", "warehouse"),
            ("厂库仓单量季节图", "factory")
        ]

        text = ""
        for title, name in charts:
            png_path = f"../report_data/charts/{self.metal}_{name}_seasonal.png"
            html_path = f"../report_data/charts/{self.metal}_{name}_seasonal.html"

            text += f"""
## {title}

![{title}]({png_path})

[打开交互式图表]({html_path})

"""
        return text

    # ===============================
    # 今日仓库变化分析
    # ===============================

    def generate_daily_change_analysis(
        self,
        end_day
    ):
        df = self.inventory.copy()

        today = df[
            df["date"]
            ==
            end_day
        ]

        previous_date = (
            df[
                df["date"] < end_day
            ]
            ["date"]
            .max()
        )

        yesterday = df[
            df["date"]
            ==
            previous_date
        ]

        today = today[
            [
                "warehouse",
                "today_receipt"
            ]
        ]

        yesterday = yesterday[
            [
                "warehouse",
                "today_receipt"
            ]
        ]

        result = today.merge(
            yesterday,
            on="warehouse",
            how="outer",
            suffixes=(
                "_today",
                "_yesterday"
            )
        )

        result = result.fillna(0)

        result["change"] = (
            result["today_receipt_today"]
            -
            result["today_receipt_yesterday"]
        )

        result = result.sort_values(
            "change",
            ascending=False
        )

        table = """
|仓库|今日仓单|昨日仓单|变化|
|-|-:|-:|-:|
"""
        print("Daily change analysis:")
        for _, row in result.iterrows():
            table += (
                f"|{row['warehouse']}|"
                f"{row['today_receipt_today']:,.0f}|"
                f"{row['today_receipt_yesterday']:,.0f}|"
                f"{self.format_number(row['change'])}|\n"
            )
        return table

    # ===============================
    # 生成报告
    # ===============================
    def generate_report(
        self,
        start_day,
        end_day,
        output_file
    ):
        self.load_data()
        start_day = pd.to_datetime(start_day)
        end_day = pd.to_datetime(end_day)
        report = f"""

# {self.metal}国内库存分析


报告期间：
{start_day.strftime('%Y-%m-%d')}
~
{end_day.strftime('%Y-%m-%d')}

---

# 1. 库存表

{self.generate_inventory_table(
    start_day,
    end_day
)}

---

# 2. 库存图

{self.generate_chart_section()}

---

# 3. 今日库存变动分析

{self.generate_daily_change_analysis(
    end_day
)}

"""
        os.makedirs(
            os.path.dirname(output_file),
            exist_ok=True
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(report)

        print(
            "Report saved:",
            output_file
        )