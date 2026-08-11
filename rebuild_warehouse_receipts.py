#!/usr/bin/env python3
"""全量重建广期所 PT、PD 仓单历史 CSV。"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from analysis.inventory import GFEXInventory
from data_collection.gfex import fetch_gfex_warehouse_receipt


METALS = ("PT", "PD")
OUTPUT_COLUMNS = (
    "date",
    "metal",
    "warehouse",
    "yesterday_receipt",
    "today_receipt",
    "change",
)


def parse_date(value: str) -> str:
    """将 YYYYMMDD 或 YYYY-MM-DD 统一为 YYYYMMDD。"""
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y%m%d")
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"日期格式错误：{value}，请使用 YYYYMMDD 或 YYYY-MM-DD"
    )


def clean_rows(df: pd.DataFrame, metal: str, date: str) -> pd.DataFrame:
    """统一字段、删除汇总行并去重。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = df.copy()
    result["date"] = date
    result["metal"] = metal
    result["warehouse"] = (
        result["warehouse"].fillna("").astype(str).str.strip()
    )
    result = result[
        result["warehouse"].ne("")
        & ~result["warehouse"].str.contains("总计|小计|合计", na=False)
    ].copy()

    for column in ("yesterday_receipt", "today_receipt"):
        result[column] = pd.to_numeric(
            result[column], errors="coerce"
        ).fillna(0)

    # 统一自行计算，避免不同来源的 change 口径不一致。
    result["change"] = (
        result["today_receipt"] - result["yesterday_receipt"]
    )
    result = result.drop_duplicates(
        subset=["date", "metal", "warehouse"], keep="last"
    )
    return result[list(OUTPUT_COLUMNS)].reset_index(drop=True)


def fetch_one_day(
    inventory: GFEXInventory,
    metal: str,
    date: str,
    source: str,
) -> tuple[pd.DataFrame, str]:
    """按指定来源抓取；auto 模式下 AkShare 为空时回退广期所。"""
    if source in {"auto", "akshare"}:
        try:
            data = clean_rows(
                inventory.get_single_day(date=date, metal=metal), metal, date
            )
        except Exception as error:
            print(f"  AkShare failed: {error}")
            data = pd.DataFrame(columns=OUTPUT_COLUMNS)

        if not data.empty:
            return data, "akshare"
        if source == "akshare":
            return data, "akshare"

    try:
        data = fetch_gfex_warehouse_receipt(date=date, metal=metal)
        return clean_rows(data, metal, date), "gfex"
    except Exception as error:
        print(f"  GFEX failed: {error}")
        return pd.DataFrame(columns=OUTPUT_COLUMNS), "gfex"


def get_trade_dates(
    inventory: GFEXInventory, start_date: str, end_date: str
) -> list[str]:
    """优先使用交易日历，日历不可用时退回工作日。"""
    try:
        return inventory.get_trade_dates(start_date, end_date)
    except Exception as error:
        print(f"交易日历获取失败，改用周一至周五：{error}")
        dates = pd.date_range(start=start_date, end=end_date, freq="B")
        return [date.strftime("%Y%m%d") for date in dates]


def save_atomically(df: pd.DataFrame, output_file: Path) -> None:
    """备份旧文件，通过临时文件原子替换，避免留下半成品。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(output_file.suffix + ".tmp")

    df.to_csv(temporary_file, index=False, encoding="utf-8-sig")

    if output_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = output_file.with_name(
            f"{output_file.stem}_{timestamp}.bak{output_file.suffix}"
        )
        shutil.copy2(output_file, backup_file)
        print(f"Backup: {backup_file}")

    os.replace(temporary_file, output_file)
    print(f"Saved:  {output_file}")


def rebuild_metal(
    inventory: GFEXInventory,
    metal: str,
    trade_dates: list[str],
    data_folder: Path,
    source: str,
    request_interval: float,
) -> bool:
    all_rows = []
    source_count = {"akshare": 0, "gfex": 0}

    print(f"\n{'=' * 60}\nRebuilding {metal}\n{'=' * 60}")
    for index, date in enumerate(trade_dates, start=1):
        print(f"[{index}/{len(trade_dates)}] {metal} {date}")
        data, actual_source = fetch_one_day(inventory, metal, date, source)
        if data.empty:
            print("  No data")
        else:
            all_rows.append(data)
            source_count[actual_source] += 1
            print(f"  {actual_source}: {len(data)} warehouse rows")
        if request_interval > 0:
            time.sleep(request_interval)

    if not all_rows:
        print(f"{metal}: no data was collected; original CSV is unchanged")
        return False

    result = pd.concat(all_rows, ignore_index=True)
    result = result.drop_duplicates(
        subset=["date", "metal", "warehouse"], keep="last"
    ).sort_values(["date", "warehouse"]).reset_index(drop=True)

    output_file = data_folder / f"gfex_{metal}_warehouse_receipt.csv"
    save_atomically(result, output_file)
    print(
        f"{metal}: {len(result)} rows, "
        f"{result['date'].nunique()} trading days; "
        f"AkShare {source_count['akshare']} days, "
        f"GFEX {source_count['gfex']} days"
    )
    return True


def main() -> int:
    project_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="重新生成 gfex_PT/PD_warehouse_receipt.csv"
    )
    parser.add_argument("--start", type=parse_date, default="20260506")
    parser.add_argument(
        "--end",
        type=parse_date,
        default=datetime.today().strftime("%Y%m%d"),
    )
    parser.add_argument(
        "--source",
        choices=("auto", "akshare", "gfex"),
        default="auto",
        help="auto=优先AkShare，取不到则回退广期所",
    )
    parser.add_argument(
        "--data-folder",
        type=Path,
        default=project_root / "data",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.15,
        help="每次请求后的等待秒数",
    )
    args = parser.parse_args()

    if args.start > args.end:
        parser.error("--start 不能晚于 --end")

    inventory = GFEXInventory(data_folder=str(args.data_folder))
    trade_dates = get_trade_dates(inventory, args.start, args.end)
    if not trade_dates:
        print("指定日期范围内没有交易日")
        return 1

    results = [
        rebuild_metal(
            inventory=inventory,
            metal=metal,
            trade_dates=trade_dates,
            data_folder=args.data_folder,
            source=args.source,
            request_interval=max(args.interval, 0),
        )
        for metal in METALS
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
