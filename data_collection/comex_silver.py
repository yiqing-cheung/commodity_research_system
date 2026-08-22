"""Incrementally update COMEX silver stock and settlement history CSV files.

The two input files are Wind exports with five metadata rows and GBK encoding.
This updater deliberately preserves that layout so the historical files remain
usable in Wind/Excel and by the existing HTML generator.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pandas as pd


CME_PAGE_URL = (
    "https://www.cmegroup.com/solutions/clearing/"
    "operations-and-deliveries/nymex-delivery-notices.html"
)
CME_STOCK_URL = "https://www.cmegroup.com/delivery_reports/Silver_stocks.xls"
CME_SETTLEMENT_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/458/FUT"
)
CME_SETTLEMENT_PAGE = (
    "https://www.cmegroup.com/markets/metals/precious/silver.settlements.html"
)

BASE_MONTHS = (3, 5, 7, 9, 12)
MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass(frozen=True)
class SilverStock:
    report_date: date
    total_oz: float
    registered_oz: float

    def validate(self) -> None:
        if self.total_oz < 0 or self.registered_oz < 0:
            raise ValueError("CME silver stock values cannot be negative")
        if self.registered_oz > self.total_oz:
            raise ValueError("Registered silver stock exceeds total stock")


@dataclass(frozen=True)
class SilverSettlement:
    trade_date: date
    month_values: dict[int, float]
    active_value: float
    active_delivery: int


def _curl_requests():
    try:
        from curl_cffi import requests
    except ImportError as error:
        raise RuntimeError("curl_cffi is required: pip install curl_cffi") from error
    return requests


def _proxies(proxy: str | None):
    return {"http": proxy, "https": proxy} if proxy else None


def _download(url: str, referer: str, proxy: str | None, timeout: int) -> bytes:
    requests = _curl_requests()
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                url,
                proxies=_proxies(proxy),
                impersonate="chrome",
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "Referer": referer,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            response.raise_for_status()
            return response.content
        except Exception as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"CME request failed: {last_error}") from last_error


def _normalise(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", "", str(value)).upper()


def _number(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def download_silver_stock_report(
    proxy: str | None = None,
    timeout: int = 60,
) -> bytes:
    content = _download(CME_STOCK_URL, CME_PAGE_URL, proxy, timeout)
    if len(content) < 1_000 or content[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("CME returned an invalid silver stock workbook")
    return content


def parse_silver_stock_report(content: bytes) -> SilverStock:
    try:
        frame = pd.read_excel(
            BytesIO(content), sheet_name=0, header=None, dtype=object, engine="xlrd"
        )
    except ImportError as error:
        raise RuntimeError("xlrd is required: pip install xlrd>=2.0.1") from error

    report_date = None
    date_pattern = re.compile(
        r"REPORTDATE:?\s*(\d{1,2})/(\d{1,2})/(20\d{2})", re.I
    )
    for value in frame.to_numpy().ravel():
        match = date_pattern.search(re.sub(r"\s+", "", str(value or "")))
        if match:
            month, day, year = map(int, match.groups())
            report_date = date(year, month, day)
            break
    if report_date is None:
        raise ValueError("CME silver stock report date was not found")

    total_today_column = None
    for row in range(len(frame)):
        for column in range(frame.shape[1]):
            if _normalise(frame.iat[row, column]) == "TOTALTODAY":
                total_today_column = column
                break
        if total_today_column is not None:
            break
    if total_today_column is None:
        raise ValueError("CME silver TOTAL TODAY column was not found")

    registered = None
    total = None
    for row in range(len(frame)):
        label = _normalise(frame.iat[row, 0])
        if label == "TOTALREGISTERED":
            registered = _number(frame.iat[row, total_today_column])
        elif label == "COMBINEDTOTAL":
            total = _number(frame.iat[row, total_today_column])
    if registered is None or total is None:
        raise ValueError("CME silver summary rows were not found")

    result = SilverStock(report_date, total, registered)
    result.validate()
    return result


def fetch_silver_stock(
    proxy: str | None = None,
    timeout: int = 60,
) -> SilverStock:
    return parse_silver_stock_report(
        download_silver_stock_report(proxy=proxy, timeout=timeout)
    )


def _settlement_payload(
    trade_date: date,
    proxy: str | None,
    timeout: int,
) -> dict:
    requests = _curl_requests()
    response = requests.get(
        CME_SETTLEMENT_URL,
        params={
            "tradeDate": trade_date.strftime("%m/%d/%Y"),
            "pageSize": 500,
            "strategy": "DEFAULT",
        },
        proxies=_proxies(proxy),
        impersonate="chrome",
        timeout=timeout,
        headers={"Referer": CME_SETTLEMENT_PAGE},
    )
    response.raise_for_status()
    payload = response.json()
    if "Silver" not in str(payload.get("dsHeader", "")):
        raise RuntimeError(f"Unexpected CME product: {payload.get('dsHeader')!r}")
    returned = datetime.strptime(payload.get("tradeDate", ""), "%m/%d/%Y").date()
    if returned != trade_date:
        raise RuntimeError(f"CME returned {returned} for requested {trade_date}")
    if payload.get("empty") or not payload.get("settlements"):
        raise RuntimeError("CME returned no silver settlements")
    if str(payload.get("reportType", "")).casefold() != "final":
        raise RuntimeError(
            f"CME settlement is not final ({payload.get('reportType')!r})"
        )
    return payload


def _contract_identity(month_text: object) -> tuple[int, int] | None:
    match = re.fullmatch(r"([A-Z]{3})\s+(\d{2})", str(month_text).strip())
    if not match or match.group(1) not in MONTH_NAMES:
        return None
    month = MONTH_NAMES[match.group(1)]
    year = 2000 + int(match.group(2))
    return year * 100 + month, month


def fetch_silver_settlement(
    trade_date: date,
    proxy: str | None = None,
    timeout: int = 60,
) -> SilverSettlement:
    payload = _settlement_payload(trade_date, proxy=proxy, timeout=timeout)
    contracts = []
    for item in payload.get("settlements", []):
        identity = _contract_identity(item.get("month"))
        settle = _number(item.get("settle"))
        if identity is None or settle is None:
            continue
        delivery, month = identity
        contracts.append(
            {
                "delivery": delivery,
                "month": month,
                "settle": settle,
                "volume": int(_number(item.get("volume")) or 0),
                "open_interest": int(_number(item.get("openInterest")) or 0),
            }
        )
    if not contracts:
        raise RuntimeError("No usable CME silver contracts were returned")

    month_values = {}
    for month in BASE_MONTHS:
        candidates = sorted(
            (item for item in contracts if item["month"] == month),
            key=lambda item: item["delivery"],
        )
        if not candidates:
            raise RuntimeError(f"CME silver {month} month settlement is missing")
        month_values[month] = candidates[0]["settle"]

    active = sorted(
        contracts,
        key=lambda item: (
            -item["volume"], -item["open_interest"], item["delivery"]
        ),
    )[0]
    return SilverSettlement(
        trade_date=trade_date,
        month_values=month_values,
        active_value=active["settle"],
        active_delivery=active["delivery"],
    )


def _read_wind_lines(path: Path, expected_columns: int) -> tuple[list[str], dict[date, list[str]]]:
    raw = path.read_text(encoding="gb18030")
    lines = raw.splitlines()
    if len(lines) < 5:
        raise ValueError(f"Wind CSV has fewer than five metadata rows: {path}")
    metadata = lines[:5]
    rows: dict[date, list[str]] = {}
    for line in lines[5:]:
        fields = line.split(",")
        if len(fields) < expected_columns:
            continue
        parsed = pd.to_datetime(fields[0].strip(), errors="coerce")
        if pd.isna(parsed):
            continue
        rows[parsed.date()] = fields[:expected_columns]
    return metadata, rows


def _format_number(value: float) -> str:
    return format(Decimal(str(value)), "f")


def _format_wind_date(value: date) -> str:
    return f"{value.year}/{value.month}/{value.day}"


def _write_wind_csv(
    path: Path,
    metadata: list[str],
    rows: dict[date, list[str]],
    backup: bool,
) -> None:
    if backup and path.exists():
        shutil.copy2(path, path.with_name(f"{path.stem}.bak{path.suffix}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    output = metadata + [
        ",".join(rows[item]) for item in sorted(rows)
    ]
    encoded = ("\r\n".join(output) + "\r\n").encode("gb18030")
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f"{path.stem}_", suffix=".tmp",
        dir=path.parent, delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    try:
        check_metadata, check_rows = _read_wind_lines(
            temporary, len(next(iter(rows.values())))
        )
        if check_metadata != metadata or len(check_rows) != len(rows):
            raise ValueError("Temporary Wind CSV verification failed")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def update_silver_stock_csv(
    csv_path: str | Path = "data/comex_ag_stock.csv",
    proxy: str | None = None,
    timeout: int = 60,
    backup: bool = True,
) -> SilverStock:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Historical silver stock CSV not found: {path}")
    stock = fetch_silver_stock(proxy=proxy, timeout=timeout)
    metadata, rows = _read_wind_lines(path, 4)
    old_delivery = rows.get(stock.report_date, ["", "", "", ""])[3]
    rows[stock.report_date] = [
        _format_wind_date(stock.report_date),
        _format_number(stock.total_oz),
        _format_number(stock.registered_oz),
        old_delivery,
    ]
    _write_wind_csv(path, metadata, rows, backup=backup)
    print(
        f"COMEX silver stocks {stock.report_date:%Y-%m-%d}: "
        f"total={stock.total_oz:.4f}, registered={stock.registered_oz:.4f}"
    )
    return stock


def update_silver_settlement_csv(
    csv_path: str | Path = "data/comex_ag_settle.csv",
    start_date: str | None = None,
    end_date: str | None = None,
    proxy: str | None = None,
    timeout: int = 60,
    backup: bool = True,
) -> list[SilverSettlement]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Historical silver settlement CSV not found: {path}")
    metadata, rows = _read_wind_lines(path, 7)
    if not rows:
        raise ValueError("Historical silver settlement CSV contains no data")
    latest = max(rows)
    start = (
        datetime.strptime(start_date, "%Y-%m-%d").date()
        if start_date else latest + timedelta(days=1)
    )
    end = (
        datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_date else date.today()
    )
    if start > end:
        print(f"COMEX silver settlements already current through {latest}")
        return []

    fetched = []
    for trade_date in _weekdays(start, end):
        try:
            result = fetch_silver_settlement(
                trade_date, proxy=proxy, timeout=timeout
            )
        except Exception as error:
            print(f"{trade_date}: COMEX silver settlement skipped ({error})")
            continue
        rows[trade_date] = [
            _format_wind_date(trade_date),
            *[_format_number(result.month_values[month]) for month in BASE_MONTHS],
            _format_number(result.active_value),
        ]
        fetched.append(result)
        print(
            f"{trade_date}: active={result.active_delivery} "
            f"settle={result.active_value:.3f}"
        )

    if fetched:
        _write_wind_csv(path, metadata, rows, backup=backup)
        print(
            f"Updated {path}: {len(fetched)} settlement rows, "
            f"latest {max(item.trade_date for item in fetched)}"
        )
    else:
        print("No new final COMEX silver settlements; CSV was not changed")
    return fetched


def update_comex_silver_csvs(
    stock_csv: str | Path = "data/comex_ag_stock.csv",
    settle_csv: str | Path = "data/comex_ag_settle.csv",
    proxy: str | None = None,
    timeout: int = 60,
    backup: bool = True,
) -> None:
    proxy = proxy or os.environ.get("NYMEX_PROXY")
    errors = []
    try:
        update_silver_stock_csv(
            stock_csv, proxy=proxy, timeout=timeout, backup=backup
        )
    except Exception as error:
        errors.append(f"stock: {error}")
        print(f"COMEX silver stock update failed; existing CSV retained: {error}")
    try:
        update_silver_settlement_csv(
            settle_csv, proxy=proxy, timeout=timeout, backup=backup
        )
    except Exception as error:
        errors.append(f"settlement: {error}")
        print(f"COMEX silver settlement update failed; existing CSV retained: {error}")
    if len(errors) == 2:
        raise RuntimeError("; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update COMEX silver Wind-history CSV files from CME"
    )
    parser.add_argument("--stock-csv", default="data/comex_ag_stock.csv")
    parser.add_argument("--settle-csv", default="data/comex_ag_settle.csv")
    parser.add_argument("--start", help="First settlement date, YYYY-MM-DD")
    parser.add_argument("--end", help="Last settlement date, YYYY-MM-DD")
    parser.add_argument(
        "--proxy",
        default=os.environ.get("NYMEX_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY"),
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    update_silver_stock_csv(
        args.stock_csv,
        proxy=args.proxy,
        timeout=args.timeout,
        backup=not args.no_backup,
    )
    update_silver_settlement_csv(
        args.settle_csv,
        start_date=args.start,
        end_date=args.end,
        proxy=args.proxy,
        timeout=args.timeout,
        backup=not args.no_backup,
    )


if __name__ == "__main__":
    main()
