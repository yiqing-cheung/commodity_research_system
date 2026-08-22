from datetime import datetime
import argparse
import os

import pandas as pd

from analysis.inventory import GFEXInventory
from data_collection.nymex import update_nymex_csv
from data_collection.nymex_spread import update_spread_csv
from data_collection.comex_silver import update_comex_silver_csvs
from data_collection.pt_trade import update_pt_trade_csv
from data_collection.pd_trade import update_pd_trade_csv
from report.data_generator import InventoryReportData
from report.generator import ReportGenerator
from report.html_generator import HTMLDashboardGenerator
from report.nymex_html_generator import NYMEXHTMLDashboardGenerator
from report.nymex_spread_html_generator import NYMEXSpreadHTMLGenerator
from report.comex_silver_html_generator import COMEXSilverHTMLGenerator
from report.pt_trade_html_generator import PTTradeHTMLGenerator
from report.pt_balance_html_generator import PTBalanceHTMLGenerator
from report.pd_trade_html_generator import PDTradeHTMLGenerator
from report.pd_balance_html_generator import PDBalanceHTMLGenerator


DATA_FOLDER = "data"
REPORT_DATA_FOLDER = "report_data"
REPORT_FOLDER = "reports"

METALS = [
    "PT",
    "PD",
]

START_DATE = "2026-05-06"  # 仓单分析起始日期


def update_nymex_sources(proxy=None):
    """Update NYMEX PGM and COMEX silver source CSV files before reports."""

    proxy = proxy or os.environ.get("NYMEX_PROXY") or "http://127.0.0.1:7890"
    print()
    print("=" * 60)
    print("Updating NYMEX source data")
    print("=" * 60)

    try:
        update_nymex_csv(
            csv_path=os.path.join(DATA_FOLDER, "pgm_receipt_nymex.csv"),
            proxy=proxy,
            timeout=60,
            backup=True,
        )
    except Exception as error:
        print(f"NYMEX inventory update failed; existing CSV retained: {error}")

    try:
        update_spread_csv(
            csv_file=os.path.join(DATA_FOLDER, "PL_main_next_quarter_spread.csv"),
            proxy=proxy,
            timeout=60,
        )
    except Exception as error:
        print(f"NYMEX spread update failed; existing CSV retained: {error}")

    try:
        update_comex_silver_csvs(
            stock_csv=os.path.join(DATA_FOLDER, "comex_ag_stock.csv"),
            settle_csv=os.path.join(DATA_FOLDER, "comex_ag_settle.csv"),
            proxy=proxy,
            timeout=60,
            backup=True,
        )
    except Exception as error:
        print(f"COMEX silver update failed; existing CSV files retained: {error}")

def get_latest_date(csv_file):
    """
    从仓单CSV中取得最新数据日期。

    Returns
    -------
    str
        YYYY-MM-DD 格式日期。
    """

    if not os.path.exists(csv_file):
        raise FileNotFoundError(
            f"仓单文件不存在：{csv_file}"
        )

    df = pd.read_csv(csv_file)

    if df.empty:
        raise ValueError(
            f"仓单文件没有数据：{csv_file}"
        )

    if "date" not in df.columns:
        raise ValueError(
            f"仓单文件缺少 date 字段：{csv_file}"
        )

    dates = pd.to_datetime(
        df["date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    ).dropna()

    if dates.empty:
        raise ValueError(
            f"仓单文件中没有有效日期：{csv_file}"
        )

    return dates.max().strftime("%Y-%m-%d")


def generate_metal_report(
    metal,
    update_date=None,
):
    """
    更新单个品种的仓单数据并生成报告。
    """

    metal = metal.upper()

    raw_file = os.path.join(
        DATA_FOLDER,
        f"gfex_{metal}_warehouse_receipt.csv",
    )

    analysis_file = os.path.join(
        REPORT_DATA_FOLDER,
        f"{metal}_inventory_analysis.csv",
    )

    chart_folder = os.path.join(
        REPORT_DATA_FOLDER,
        "charts",
    )

    report_file = os.path.join(
        REPORT_FOLDER,
        f"report_{metal}.md",
    )

    print("=" * 60)
    print(f"Processing {metal}")
    print("=" * 60)

    # ==========================================
    # 1. 更新最新仓单数据
    # ==========================================

    inventory = GFEXInventory(
        data_folder=DATA_FOLDER
    )

    inventory.update_daily(
        metal=metal,
        date=update_date,
        source="akshare",
    )

    # 即使当天尚未公布数据，也会使用CSV中的最新日期
    latest_date = get_latest_date(
        raw_file
    )

    print(
        f"{metal} latest available date: "
        f"{latest_date}"
    )

    # ==========================================
    # 2. 生成库存分析数据和图表
    # ==========================================

    data_generator = InventoryReportData(
        metal=metal,
        raw_file=raw_file,
        output_folder=REPORT_DATA_FOLDER,
    )

    data_generator.generate()

    # ==========================================
    # 3. 生成Markdown报告
    # ==========================================

    report_generator = ReportGenerator(
        metal=metal,
        analysis_file=analysis_file,
        inventory_file=raw_file,
        chart_folder=chart_folder,
    )

    report_generator.generate_report(
        start_day=START_DATE,
        end_day=latest_date,
        output_file=report_file,
    )

    print(
        f"{metal} report generated: "
        f"{report_file}"
    )


def main(
    update_date=None,
    nymex_proxy=None,
    update_trade=False,
    trade_month=None,
    update_pd_trade=False,
    pd_trade_month=None,
):
    os.makedirs(
        REPORT_FOLDER,
        exist_ok=True,
    )

    if update_trade:
        print()
        print("=" * 60)
        print("Updating China platinum import/export data")
        print("=" * 60)
        update_pt_trade_csv(
            data_folder=DATA_FOLDER,
            trade_month=trade_month,
            backup=True,
        )

    if update_pd_trade:
        print()
        print("=" * 60)
        print("Updating China palladium import/export data")
        print("=" * 60)
        update_pd_trade_csv(
            data_folder=DATA_FOLDER,
            trade_month=pd_trade_month,
            backup=True,
        )

    # Update overseas PGM data plus COMEX silver stocks and settlements first.
    # Failures do not prevent reports from being rebuilt from the existing CSV files.
    update_nymex_sources(proxy=nymex_proxy)

    # update_daily 默认查询当天。
    # 如果 AkShare 没有更新，会自动回退广期所接口。
    if update_date is None:
        update_date = datetime.today().strftime(
            "%Y-%m-%d"
        )

    success = []
    failed = []

    for metal in METALS:
        try:
            generate_metal_report(
                metal=metal,
                update_date=update_date,
            )

            success.append(metal)

        except Exception as error:
            failed.append(
                {
                    "metal": metal,
                    "error": str(error),
                }
            )

            # 一个品种失败时继续处理另一个品种
            print(
                f"{metal} processing failed: "
                f"{error}"
            )

    print()
    print("=" * 60)
    print("Processing completed")
    print("=" * 60)
    print(
        "Success:",
        ", ".join(success) if success else "None",
    )

    if failed:
        print("Failed:")

        for item in failed:
            print(
                f"  {item['metal']}: "
                f"{item['error']}"
            )

    # PT、PD 都完成后，生成一个可直接发布到 GitHub Pages 的交互网页。
    if all(metal in success for metal in METALS):
        dashboard = HTMLDashboardGenerator(
            data_folder=DATA_FOLDER,
            report_data_folder=REPORT_DATA_FOLDER,
        )
        dashboard.generate(
            output_file=os.path.join(
                "site",
                "pgm",
                "index.html",
            ),
            metals=tuple(METALS),
        )
    else:
        print(
            "PT/PD 数据未全部生成成功，"
            "本次跳过 HTML 仪表板，保留上一次网页。"
        )

    # NYMEX 页面直接读取已维护的 CSV，不在这里发起网络更新。
    # 因此即使当天 CME 网络暂时不可用，也可以重新生成现有全部历史数据页面。
    try:
        nymex_dashboard = NYMEXHTMLDashboardGenerator(
            csv_file=os.path.join(DATA_FOLDER, "pgm_receipt_nymex.csv")
        )
        nymex_dashboard.generate(
            output_file=os.path.join("site", "pgm", "nymex.html")
        )
    except Exception as error:
        print(f"NYMEX HTML dashboard generation failed: {error}")

    try:
        spread_dashboard = NYMEXSpreadHTMLGenerator(
            spread_csv=os.path.join(DATA_FOLDER, "PL_main_next_quarter_spread.csv"),
            inventory_csv=os.path.join(DATA_FOLDER, "pgm_receipt_nymex.csv"),
        )
        spread_dashboard.generate(
            output_file=os.path.join("site", "pgm", "nymex_spread.html")
        )
    except Exception as error:
        print(f"NYMEX spread dashboard generation failed: {error}")

    try:
        silver_dashboard = COMEXSilverHTMLGenerator(
            stock_csv=os.path.join(DATA_FOLDER, "comex_ag_stock.csv"),
            settle_csv=os.path.join(DATA_FOLDER, "comex_ag_settle.csv"),
        )
        silver_dashboard.generate(
            output_file=os.path.join("site", "pgm", "comex_silver.html")
        )
    except Exception as error:
        print(f"COMEX silver dashboard generation failed: {error}")

    try:
        trade_dashboard = PTTradeHTMLGenerator(
            import_csv=os.path.join(DATA_FOLDER, "pt_cn_import.csv"),
            export_csv=os.path.join(DATA_FOLDER, "pt_cn_export.csv"),
        )
        trade_dashboard.generate(
            output_file=os.path.join("site", "pgm", "pt_trade.html")
        )
    except Exception as error:
        print(f"China platinum trade dashboard generation failed: {error}")

    try:
        balance_dashboard = PTBalanceHTMLGenerator(
            import_csv=os.path.join(DATA_FOLDER, "pt_cn_import.csv"),
            export_csv=os.path.join(DATA_FOLDER, "pt_cn_export.csv"),
            inventory_csv=os.path.join(DATA_FOLDER, "gfex_PT_warehouse_receipt.csv"),
        )
        balance_dashboard.generate(
            output_file=os.path.join("site", "pgm", "pt_balance.html")
        )
    except Exception as error:
        print(f"China platinum balance dashboard generation failed: {error}")

    try:
        pd_trade_dashboard = PDTradeHTMLGenerator(
            import_csv=os.path.join(DATA_FOLDER, "pd_cn_import.csv"),
            export_csv=os.path.join(DATA_FOLDER, "pd_cn_export.csv"),
        )
        pd_trade_dashboard.generate(
            output_file=os.path.join("site", "pgm", "pd_trade.html")
        )
    except Exception as error:
        print(f"China palladium trade dashboard generation failed: {error}")

    try:
        pd_balance_dashboard = PDBalanceHTMLGenerator(
            import_csv=os.path.join(DATA_FOLDER, "pd_cn_import.csv"),
            export_csv=os.path.join(DATA_FOLDER, "pd_cn_export.csv"),
            inventory_csv=os.path.join(DATA_FOLDER, "gfex_PD_warehouse_receipt.csv"),
        )
        pd_balance_dashboard.generate(
            output_file=os.path.join("site", "pgm", "pd_balance.html")
        )
    except Exception as error:
        print(f"China palladium balance dashboard generation failed: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update PGM data and generate research dashboards."
    )
    parser.add_argument(
        "--update-date",
        help="GFEX update date in YYYY-MM-DD format; defaults to today.",
    )
    parser.add_argument(
        "--nymex-proxy",
        help="Optional proxy, for example http://127.0.0.1:7890.",
    )
    parser.add_argument(
        "--update-trade",
        action="store_true",
        help=(
            "Merge the latest matching month-stamped Customs import/export "
            "CSV files into the platinum history files."
        ),
    )
    parser.add_argument(
        "--trade-month",
        help=(
            "Customs data month in YYYYMM format. If omitted, the latest "
            "month found in the source filenames is used."
        ),
    )
    parser.add_argument(
        "--update-pd-trade",
        action="store_true",
        help=(
            "Merge the latest matching month-stamped Customs palladium "
            "import/export CSV files into the palladium history files."
        ),
    )
    parser.add_argument(
        "--pd-trade-month",
        help=(
            "Palladium Customs data month in YYYYMM format. If omitted, the "
            "latest month found in the source filenames is used."
        ),
    )
    arguments = parser.parse_args()
    if arguments.trade_month and not arguments.update_trade:
        parser.error("--trade-month must be used together with --update-trade")
    if arguments.pd_trade_month and not arguments.update_pd_trade:
        parser.error(
            "--pd-trade-month must be used together with --update-pd-trade"
        )

    main(
        update_date=arguments.update_date,
        nymex_proxy=arguments.nymex_proxy,
        update_trade=arguments.update_trade,
        trade_month=arguments.trade_month,
        update_pd_trade=arguments.update_pd_trade,
        pd_trade_month=arguments.pd_trade_month,
    )
