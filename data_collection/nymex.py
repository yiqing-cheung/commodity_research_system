"""Update NYMEX platinum/palladium inventory and delivery data in CSV.

Data sources
------------
* CME platinum/palladium stock report (legacy XLS)
* CME daily metals issues and stops report (PDF)

The module can also perform the one-time migration from the original seven-
column Excel workbook to the standard CSV schema used by this project.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from curl_cffi import requests as curl_requests
from pypdf import PdfReader


CME_PAGE_URL = (
    "https://www.cmegroup.com/solutions/clearing/"
    "operations-and-deliveries/nymex-delivery-notices.html"
)
CME_STOCK_URL = (
    "https://www.cmegroup.com/delivery_reports/PA-PL_Stck_Rprt.xls"
)
CME_DELIVERY_URL = (
    "https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsReport.pdf"
)

DEFAULT_CSV_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "pgm_receipt_nymex.csv"
)

CSV_COLUMNS = [
    "date",
    "pd_total_oz",
    "pt_total_oz",
    "pd_registered_oz",
    "pt_registered_oz",
    "pd_delivery_contracts",
    "pt_delivery_contracts",
]

STOCK_COLUMNS = [
    "pd_total_oz",
    "pt_total_oz",
    "pd_registered_oz",
    "pt_registered_oz",
]

DELIVERY_COLUMNS = [
    "pd_delivery_contracts",
    "pt_delivery_contracts",
]


@dataclass(frozen=True)
class NymexStock:
    report_date: date
    pd_total: float
    pt_total: float
    pd_registered: float
    pt_registered: float

    def validate(self) -> None:
        values = (
            self.pd_total,
            self.pt_total,
            self.pd_registered,
            self.pt_registered,
        )
        if any(value < 0 for value in values):
            raise ValueError("CME stock values cannot be negative")
        if self.pd_registered > self.pd_total:
            raise ValueError("Palladium registered stock exceeds total stock")
        if self.pt_registered > self.pt_total:
            raise ValueError("Platinum registered stock exceeds total stock")


@dataclass(frozen=True)
class NymexDelivery:
    report_date: date
    pd_delivery: int
    pt_delivery: int

    def validate(self) -> None:
        if self.pd_delivery < 0 or self.pt_delivery < 0:
            raise ValueError("CME delivery volume cannot be negative")


def _normalise_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", "", str(value)).strip().casefold()


def _as_number(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def _request_headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": CME_PAGE_URL,
    }


def _download_cme_file(
    url: str,
    accept: str,
    timeout: int,
    proxy: str | None,
) -> bytes:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    last_error: Exception | None = None

    for attempt in range(4):
        try:
            response = curl_requests.get(
                url,
                headers=_request_headers(accept),
                proxies=proxies,
                impersonate="chrome",
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            return response.content
        except Exception as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)

    raise RuntimeError(f"CME request failed: {last_error}") from last_error


def download_cme_stock_report(
    timeout: int = 60,
    proxy: str | None = None,
) -> bytes:
    content = _download_cme_file(
        CME_STOCK_URL,
        "application/vnd.ms-excel,application/octet-stream,*/*;q=0.8",
        timeout,
        proxy,
    )
    if len(content) < 1_000:
        raise ValueError("CME stock report is unexpectedly small")
    if content[:200].lstrip().lower().startswith((b"<html", b"<!doctype html")):
        raise ValueError("CME returned HTML instead of the stock workbook")
    return content


def download_cme_delivery_report(
    timeout: int = 60,
    proxy: str | None = None,
) -> bytes:
    content = _download_cme_file(
        CME_DELIVERY_URL,
        "application/pdf,application/octet-stream,*/*;q=0.8",
        timeout,
        proxy,
    )
    if len(content) < 1_000 or not content.lstrip().startswith(b"%PDF"):
        raise ValueError("CME returned an invalid delivery PDF")
    return content


def _read_stock_sheets(content: bytes) -> dict[str, pd.DataFrame]:
    try:
        excel = pd.ExcelFile(BytesIO(content), engine="xlrd")
    except ImportError as error:
        raise RuntimeError("Run: pip install xlrd>=2.0.1") from error
    return {
        sheet_name: pd.read_excel(
            excel,
            sheet_name=sheet_name,
            header=None,
            dtype=object,
        )
        for sheet_name in excel.sheet_names
    }


def _parse_date_from_label(frame: pd.DataFrame, label: str) -> date | None:
    pattern = re.compile(
        rf"{re.escape(label)}\s*:?\s*(\d{{1,2}})[/-](\d{{1,2}})[/-](20\d{{2}})",
        flags=re.IGNORECASE,
    )
    for value in frame.to_numpy().ravel():
        match = pattern.search(str(value or ""))
        if match:
            month, day, year = (int(item) for item in match.groups())
            return date(year, month, day)
    return None


def _parse_stock_block(
    frame: pd.DataFrame,
    metal_name: str,
) -> tuple[float, float]:
    start = None
    for row in range(len(frame)):
        if _normalise_text(frame.iat[row, 0]) == metal_name.casefold():
            start = row
            break
    if start is None:
        raise ValueError(f"CME {metal_name} block was not found")

    end = len(frame)
    for row in range(start + 1, len(frame)):
        value = _normalise_text(frame.iat[row, 0])
        if value in {"platinum", "palladium"}:
            end = row
            break

    total_today_column = None
    for row in range(start, min(start + 15, end)):
        for column in range(frame.shape[1]):
            if _normalise_text(frame.iat[row, column]) == "totaltoday":
                total_today_column = column
                break
        if total_today_column is not None:
            break
    if total_today_column is None:
        raise ValueError(f"CME {metal_name} TOTAL TODAY column was not found")

    registered = None
    total = None
    for row in range(start, end):
        label = _normalise_text(frame.iat[row, 0])
        if label == "totalregistered":
            registered = _as_number(frame.iat[row, total_today_column])
        elif label == "combinedtotal":
            total = _as_number(frame.iat[row, total_today_column])

    if registered is None or total is None:
        raise ValueError(f"CME {metal_name} summary rows were not found")
    if total < registered:
        raise ValueError(f"CME {metal_name} total is below registered stock")
    return total, registered


def parse_cme_stock_report(content: bytes) -> NymexStock:
    sheets = _read_stock_sheets(content)
    report_date = None
    for frame in sheets.values():
        report_date = report_date or _parse_date_from_label(frame, "Report Date")
    if report_date is None:
        raise ValueError("CME stock report date was not found")

    frames = list(sheets.values())
    pt_result = None
    pd_result = None
    for frame in frames:
        if pt_result is None:
            try:
                pt_result = _parse_stock_block(frame, "PLATINUM")
            except ValueError:
                pass
        if pd_result is None:
            try:
                pd_result = _parse_stock_block(frame, "PALLADIUM")
            except ValueError:
                pass
    if pt_result is None or pd_result is None:
        raise ValueError("CME platinum/palladium stock blocks were not found")

    pt_total, pt_registered = pt_result
    pd_total, pd_registered = pd_result
    result = NymexStock(
        report_date=report_date,
        pd_total=pd_total,
        pt_total=pt_total,
        pd_registered=pd_registered,
        pt_registered=pt_registered,
    )
    result.validate()
    return result


def _extract_delivery_date(text: str) -> date:
    for label in ("INTENT DATE", "BUSINESS DATE", "RUN DATE"):
        match = re.search(
            rf"{label}\s*:?\s*(\d{{1,2}})[/-](\d{{1,2}})[/-](20\d{{2}})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            month, day, year = (int(item) for item in match.groups())
            return date(year, month, day)
    raise ValueError("CME delivery report date was not found")


def _delivery_total(text: str, metal_name: str) -> int:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    total = 0
    commodities = ("GOLD", "SILVER", "COPPER", "PLATINUM", "PALLADIUM")

    for start, line in enumerate(lines):
        upper = line.upper()
        if metal_name not in upper or "FUTURE" not in upper:
            continue

        end = len(lines)
        for row in range(start + 1, len(lines)):
            candidate = lines[row].upper()
            if "FUTURE" in candidate and any(item in candidate for item in commodities):
                end = row
                break

        block_value = 0
        for row in range(start, end):
            if "TOTAL:" not in lines[row].upper():
                continue
            numbers = [
                int(item.replace(",", ""))
                for item in re.findall(r"\d[\d,]*", lines[row])
            ]
            if len(numbers) >= 2 and numbers[0] == numbers[1]:
                block_value = numbers[0]
                break
            if numbers:
                block_value = numbers[0]
                break
        total += block_value

    # Absence of a metal block means no delivery notice for that metal today.
    return total


def parse_cme_delivery_report(content: bytes) -> NymexDelivery:
    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError("CME delivery PDF contains no extractable text")

    result = NymexDelivery(
        report_date=_extract_delivery_date(text),
        pd_delivery=_delivery_total(text, "PALLADIUM"),
        pt_delivery=_delivery_total(text, "PLATINUM"),
    )
    result.validate()
    return result


def fetch_nymex_stock(
    timeout: int = 60,
    proxy: str | None = None,
) -> NymexStock:
    return parse_cme_stock_report(
        download_cme_stock_report(timeout=timeout, proxy=proxy)
    )


def fetch_nymex_delivery(
    timeout: int = 60,
    proxy: str | None = None,
) -> NymexDelivery:
    return parse_cme_delivery_report(
        download_cme_delivery_report(timeout=timeout, proxy=proxy)
    )


def _clean_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in CSV_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("CSV is missing columns: " + ", ".join(missing))

    result = frame[CSV_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    result = result.dropna(subset=["date"])

    for column in STOCK_COLUMNS + DELIVERY_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    # Merge duplicate dates without losing values that may exist in different
    # rows, taking the last non-null observation for each field.
    result = (
        result.sort_values("date")
        .groupby("date", as_index=False)
        .agg({column: "last" for column in STOCK_COLUMNS + DELIVERY_COLUMNS})
        .sort_values("date")
        .reset_index(drop=True)
    )
    return result


def read_nymex_csv(csv_path: str | Path) -> pd.DataFrame:
    path = Path(csv_path).expanduser().resolve()
    if not path.exists():
        return pd.DataFrame(columns=CSV_COLUMNS)
    return _clean_dataframe(pd.read_csv(path, encoding="utf-8-sig"))


def convert_excel_to_csv(
    excel_path: str | Path,
    csv_path: str | Path = DEFAULT_CSV_FILE,
) -> pd.DataFrame:
    """Convert the original seven-column NYMEX workbook to standard CSV."""

    source = Path(excel_path).expanduser().resolve()
    destination = Path(csv_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Excel workbook does not exist: {source}")

    frame = pd.read_excel(source, sheet_name=0, header=0, usecols="A:G")
    if frame.shape[1] != 7:
        raise ValueError(f"Expected 7 Excel columns, found {frame.shape[1]}")

    # The supplied historical workbook is ordered PT first, then PD:
    # date, PT total, PD total, PT registered, PD registered,
    # PT delivery, PD delivery.  The standard CSV deliberately uses PD first.
    frame.columns = [
        "date",
        "pt_total_oz",
        "pd_total_oz",
        "pt_registered_oz",
        "pd_registered_oz",
        "pt_delivery_contracts",
        "pd_delivery_contracts",
    ]
    frame = _clean_dataframe(frame[CSV_COLUMNS])
    _write_csv_atomic(frame, destination, backup=False)
    return frame


def _upsert_values(
    frame: pd.DataFrame,
    target_date: date,
    values: dict[str, float | int],
) -> tuple[pd.DataFrame, str]:
    timestamp = pd.Timestamp(target_date)
    mask = frame["date"] == timestamp
    action = "updated" if mask.any() else "appended"

    if not mask.any():
        new_row = {column: pd.NA for column in CSV_COLUMNS}
        new_row["date"] = timestamp
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
        mask = frame["date"] == timestamp

    for column, value in values.items():
        frame.loc[mask, column] = value
    return _clean_dataframe(frame), action


def _write_csv_atomic(
    frame: pd.DataFrame,
    csv_path: str | Path,
    backup: bool,
) -> None:
    path = Path(csv_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        backup_path = path.with_name(f"{path.stem}.bak{path.suffix}")
        shutil.copy2(path, backup_path)

    output = frame.copy()
    output["date"] = output["date"].dt.strftime("%Y-%m-%d")
    for column in DELIVERY_COLUMNS:
        output[column] = output[column].astype("Int64")

    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=f"{path.stem}_",
        suffix=".csv",
        dir=path.parent,
        encoding="utf-8-sig",
        newline="",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        output.to_csv(handle, index=False, float_format="%.6f")

    try:
        check = pd.read_csv(temporary_path, encoding="utf-8-sig")
        if list(check.columns) != CSV_COLUMNS or len(check) != len(output):
            raise ValueError("Temporary CSV verification failed")
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def update_nymex_csv(
    csv_path: str | Path = DEFAULT_CSV_FILE,
    timeout: int = 60,
    proxy: str | None = None,
    backup: bool = True,
) -> pd.DataFrame:
    """Fetch both CME reports and update the standard CSV atomically."""

    proxy = proxy or os.environ.get("NYMEX_PROXY")
    # Fetch and parse everything first, so failures cannot partially update CSV.
    stock = fetch_nymex_stock(timeout=timeout, proxy=proxy)
    delivery = fetch_nymex_delivery(timeout=timeout, proxy=proxy)

    frame = read_nymex_csv(csv_path)
    frame, stock_action = _upsert_values(
        frame,
        stock.report_date,
        {
            "pd_total_oz": stock.pd_total,
            "pt_total_oz": stock.pt_total,
            "pd_registered_oz": stock.pd_registered,
            "pt_registered_oz": stock.pt_registered,
        },
    )
    frame, delivery_action = _upsert_values(
        frame,
        delivery.report_date,
        {
            "pd_delivery_contracts": delivery.pd_delivery,
            "pt_delivery_contracts": delivery.pt_delivery,
        },
    )
    _write_csv_atomic(frame, csv_path, backup=backup)

    print(
        f"NYMEX stocks {stock.report_date:%Y-%m-%d} {stock_action}: "
        f"PD total={stock.pd_total:.3f}, PT total={stock.pt_total:.3f}, "
        f"PD registered={stock.pd_registered:.3f}, "
        f"PT registered={stock.pt_registered:.3f}"
    )
    print(
        f"NYMEX delivery {delivery.report_date:%Y-%m-%d} {delivery_action}: "
        f"PD={delivery.pd_delivery}, PT={delivery.pt_delivery}"
    )
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update NYMEX platinum/palladium CSV from CME"
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_CSV_FILE),
        help="Output CSV path",
    )
    parser.add_argument(
        "--proxy",
        default=os.environ.get("NYMEX_PROXY"),
        help="For example http://127.0.0.1:7890",
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument(
        "--migrate-excel",
        default=None,
        help="One-time source XLSX path to convert before updating",
    )
    args = parser.parse_args()

    if args.migrate_excel:
        converted = convert_excel_to_csv(args.migrate_excel, args.file)
        print(f"Converted {len(converted)} rows to {Path(args.file).resolve()}")

    update_nymex_csv(
        csv_path=args.file,
        timeout=args.timeout,
        proxy=args.proxy,
        backup=not args.no_backup,
    )


if __name__ == "__main__":
    main()
