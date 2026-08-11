from analysis.inventory import InventoryAnalyzer
import os

class InventoryReportData:

    def __init__(
        self,
        metal,
        raw_file,
        output_folder="report_data"
    ):

        self.metal = metal.upper()
        self.raw_file = raw_file
        self.output_folder = output_folder

        os.makedirs(
            output_folder,
            exist_ok=True
        )


    def generate(self):

        analyzer = InventoryAnalyzer(
            file_path=self.raw_file,
            metal=self.metal
        )

        analyzer.load_data()

        analyzer.calculate_inventory()


        # ==========================
        # 1. 生成库存分析CSV
        # ==========================

        csv_path = os.path.join(
            self.output_folder,
            f"{self.metal}_inventory_analysis.csv"
        )


        analyzer.save_table(
            csv_path
        )


        # ==========================
        # 2. 生成交互式季节图
        # ==========================

        chart_folder = os.path.join(
            self.output_folder,
            "charts"
        )

        os.makedirs(
            chart_folder,
            exist_ok=True
        )

        charts = [
            ("仓单量", "inventory"),
            ("仓库仓单量", "warehouse"),
            ("厂库仓单量", "factory")
        ]

        for column, name in charts:
            png_path = os.path.join(chart_folder, f"{self.metal}_{name}_seasonal.png")
            html_path = os.path.join(chart_folder, f"{self.metal}_{name}_seasonal.html")

            analyzer.plot_seasonal_chart(column, png_path)
            analyzer.plot_seasonal_chart_interactive(column, html_path)

        print("Report data generated")
        print(csv_path)
        print(chart_folder)
