from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


CME_PRODUCT_ID = 446
CME_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    f"{CME_PRODUCT_ID}/FUT"
)
MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
COLUMNS = [
    "datetime", "main_contract", "main_close", "main_volume", "main_position",
    "next_contract", "next_close", "next_volume", "next_position",
    "spread_main_minus_next", "spread_pct_of_next", "next_source",
]


def _number(value):
    if value is None:
        return None
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def _integer(value):
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _contract(month_text):
    match = re.fullmatch(r"([A-Z]{3})\s+(\d{2})", str(month_text).strip())
    if not match:
        return None
    month = MONTH_NAMES.get(match.group(1))
    if month not in MONTH_CODES:
        return None
    year = 2000 + int(match.group(2))
    return {
        "contract": f"PL_{MONTH_CODES[month]}{year % 100:02d}",
        "delivery": year * 100 + month,
    }


def _next_delivery(delivery):
    year, month = divmod(delivery, 100)
    month += 3
    if month > 12:
        month -= 12
        year += 1
    return year * 100 + month


def _http_get_json(trade_date, proxy=None, timeout=60):
    try:
        from curl_cffi import requests
    except ImportError as error:
        raise RuntimeError(
            "curl_cffi is required: pip install curl_cffi"
        ) from error

    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(
        CME_URL,
        params={
            "tradeDate": trade_date.strftime("%m/%d/%Y"),
            "pageSize": 500,
            "strategy": "DEFAULT",
        },
        proxies=proxies,
        impersonate="chrome",
        timeout=timeout,
        headers={"Referer": "https://www.cmegroup.com/markets/metals/precious/platinum.settlements.html"},
    )
    response.raise_for_status()
    payload = response.json()
    if "Platinum" not in str(payload.get("dsHeader", "")):
        raise RuntimeError(f"Unexpected CME product: {payload.get('dsHeader')!r}")
    return payload


def fetch_trade_date(trade_date, previous_main_delivery=None, proxy=None, timeout=60):
    payload = _http_get_json(trade_date, proxy=proxy, timeout=timeout)
    candidates = []
    for item in payload.get("settlements", []):
        identity = _contract(item.get("month"))
        settlement = _number(item.get("settle"))
        if not identity or settlement is None:
            continue
        if previous_main_delivery and identity["delivery"] < previous_main_delivery:
            continue
        candidates.append({
            **identity,
            "close": settlement,
            "volume": _integer(item.get("volume")) or 0,
            "position": _integer(item.get("openInterest")),
        })

    if not candidates:
        return None

    # Main contract: highest volume; ties use open interest, then nearer delivery.
    main = sorted(
        candidates,
        key=lambda x: (-x["volume"], -(x["position"] or -1), x["delivery"]),
    )[0]
    wanted_delivery = _next_delivery(main["delivery"])
    next_contract = next(
        (item for item in candidates if item["delivery"] == wanted_delivery), None
    )
    if next_contract is None:
        return None

    spread = main["close"] - next_contract["close"]
    return {
        "datetime": trade_date.isoformat(),
        "main_contract": main["contract"],
        "main_close": main["close"],
        "main_volume": main["volume"],
        "main_position": main["position"],
        "next_contract": next_contract["contract"],
        "next_close": next_contract["close"],
        "next_volume": next_contract["volume"],
        "next_position": next_contract["position"],
        "spread_main_minus_next": round(spread, 10),
        "spread_pct_of_next": round(spread / next_contract["close"], 12)
        if next_contract["close"] else None,
        "next_source": "cme_settlement",
    }


def _contract_delivery(contract):
    match = re.fullmatch(r"PL_([FGHJKMNQUVXZ])(\d{2})", str(contract))
    if not match:
        return None
    month = {code: month for month, code in MONTH_CODES.items()}[match.group(1)]
    return (2000 + int(match.group(2))) * 100 + month


def _date_range(start, end):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def update_spread_csv(
    csv_file="data/PL_main_next_quarter_spread.csv",
    start_date=None,
    end_date=None,
    proxy=None,
    timeout=60,
):
    csv_path = Path(csv_file)
    if not csv_path.exists():
        raise FileNotFoundError(f"Historical spread CSV not found: {csv_path}")

    old = pd.read_csv(csv_path)
    missing = [column for column in COLUMNS if column not in old.columns]
    if missing:
        raise ValueError(f"Spread CSV missing columns: {', '.join(missing)}")
    old["datetime"] = pd.to_datetime(old["datetime"], errors="coerce")
    old = old.dropna(subset=["datetime"]).sort_values("datetime")

    latest = old["datetime"].max().date()
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else latest + timedelta(days=1)
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    if start > end:
        print(f"Spread CSV is already current through {latest}")
        return old

    prior = old.loc[old["datetime"] < pd.Timestamp(start)]
    previous_delivery = _contract_delivery(prior.iloc[-1]["main_contract"]) if not prior.empty else None
    rows = []
    for trade_date in _date_range(start, end):
        try:
            row = fetch_trade_date(
                trade_date,
                previous_main_delivery=previous_delivery,
                proxy=proxy,
                timeout=timeout,
            )
        except Exception as error:
            print(f"{trade_date}: CME request skipped ({error})")
            continue
        if row is None:
            print(f"{trade_date}: no complete three-month spread settlement")
            continue
        rows.append(row)
        previous_delivery = _contract_delivery(row["main_contract"])
        print(
            f"{trade_date}: {row['main_contract']} {row['main_close']} - "
            f"{row['next_contract']} {row['next_close']} = "
            f"{row['spread_main_minus_next']:.1f}"
        )

    if not rows:
        print("No new CME settlement rows were available; CSV was not changed")
        return old

    new = pd.DataFrame(rows, columns=COLUMNS)
    new["datetime"] = pd.to_datetime(new["datetime"])
    combined = pd.concat([old[COLUMNS], new], ignore_index=True)
    combined = combined.sort_values("datetime").drop_duplicates("datetime", keep="last")
    combined["datetime"] = combined["datetime"].dt.strftime("%Y-%m-%d")

    backup = csv_path.with_suffix(".bak.csv")
    shutil.copy2(csv_path, backup)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", delete=False, dir=csv_path.parent,
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        combined.to_csv(handle, index=False, lineterminator="\n")
    os.replace(temp_path, csv_path)
    print(f"Updated {csv_path}: {len(new)} fetched rows, latest {combined.iloc[-1]['datetime']}")
    print(f"Backup saved: {backup}")
    return combined


def main():
    parser = argparse.ArgumentParser(description="Update NYMEX platinum three-month calendar spread")
    parser.add_argument("--csv", default="data/PL_main_next_quarter_spread.csv")
    parser.add_argument("--start", help="First trade date, YYYY-MM-DD")
    parser.add_argument("--end", help="Last trade date, YYYY-MM-DD")
    parser.add_argument("--proxy", default=os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    update_spread_csv(
        csv_file=args.csv,
        start_date=args.start,
        end_date=args.end,
        proxy=args.proxy,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
