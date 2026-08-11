"""
广州期货交易所仓单日报数据接口。

支持品种：
SI  工业硅
LC  碳酸锂
PS  多晶硅
PT  铂
PD  钯
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


GFEX_PAGE_URL = (
    "http://www.gfex.com.cn"
    "/gfex/cdrb/hqsj_tjsj.shtml"
)

GFEX_API_URL = (
    "http://www.gfex.com.cn"
    "/u/interfacesWebTdWbillWeeklyQuotes/loadList"
)

SUPPORTED_METALS = {
    "SI": "工业硅",
    "LC": "碳酸锂",
    "PS": "多晶硅",
    "PT": "铂",
    "PD": "钯",
}


def _empty_dataframe():
    """返回结构固定的空表。"""

    return pd.DataFrame(
        columns=[
            "date",
            "metal",
            "warehouse",
            "yesterday_receipt",
            "today_receipt",
            "change",
        ]
    )


def _validate_date(date):
    """检查日期并转换为 YYYYMMDD。"""

    if isinstance(date, datetime):
        return date.strftime("%Y%m%d")

    date = str(date).strip()

    # 兼容 YYYY-MM-DD
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(
                date,
                date_format
            ).strftime("%Y%m%d")
        except ValueError:
            continue

    raise ValueError(
        f"日期格式错误：{date}，应使用 YYYYMMDD 或 YYYY-MM-DD"
    )


def fetch_gfex_warehouse_receipt(
    date,
    metal,
    retries=4,
    timeout=30,
):
    """
    获取广期所某个品种的单日仓单数据。

    Parameters
    ----------
    date:
        查询日期，支持 YYYYMMDD 或 YYYY-MM-DD。

    metal:
        品种代码：
        SI、LC、PS、PT、PD。

    retries:
        请求失败时的最大尝试次数。

    timeout:
        单次请求超时时间，单位为秒。

    Returns
    -------
    pandas.DataFrame

    返回字段：
        date
        metal
        warehouse
        yesterday_receipt
        today_receipt
        change
    """

    metal = str(metal).upper().strip()
    date = _validate_date(date)

    if metal not in SUPPORTED_METALS:
        supported = ", ".join(SUPPORTED_METALS)

        raise ValueError(
            f"不支持的品种：{metal}；"
            f"目前支持：{supported}"
        )

    request_body = urlencode(
        {
            "gen_date": date,
            "variety": metal.lower(),
        }
    ).encode("utf-8")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "Chrome/126.0 Safari/537.36"
        ),
        "Referer": GFEX_PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": (
            "application/json, text/javascript, "
            "*/*; q=0.01"
        ),
        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),
    }

    payload = None
    last_error = None

    for attempt in range(1, retries + 1):
        request = Request(
            GFEX_API_URL,
            data=request_body,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=timeout,
            ) as response:
                response_text = response.read().decode(
                    "utf-8"
                )

            payload = json.loads(response_text)
            break

        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            last_error = error

            if attempt >= retries:
                break

            # 指数退避，避免连续快速请求
            time.sleep(0.8 * (2 ** (attempt - 1)))

    if payload is None:
        print(
            f"GFEX request failed: "
            f"{metal} {date}: {last_error}"
        )
        return _empty_dataframe()

    if str(payload.get("code")) != "0":
        print(
            f"GFEX interface error: "
            f"{metal} {date}: {payload.get('msg')}"
        )
        return _empty_dataframe()

    rows = payload.get("data") or []

    # 接口同时返回“总计”和“品种小计”。
    # 仓库明细行具有 genDate，并且 varietyOrder 是品种代码。
    detail_rows = [
        row
        for row in rows
        if str(row.get("genDate") or "") == date
        and str(
            row.get("varietyOrder") or ""
        ).lower() == metal.lower()
        and str(row.get("whAbbr") or "").strip()
    ]

    if not detail_rows:
        print(
            f"GFEX has no warehouse data: "
            f"{metal} {date}"
        )
        return _empty_dataframe()

    raw = pd.DataFrame(detail_rows)

    result = pd.DataFrame(
        {
            "date": date,
            "metal": metal,
            "warehouse": raw["whAbbr"].astype(str),
            "yesterday_receipt": pd.to_numeric(
                raw["lastWbillQty"],
                errors="coerce",
            ).fillna(0),
            "today_receipt": pd.to_numeric(
                raw["wbillQty"],
                errors="coerce",
            ).fillna(0),
        }
    )

    # 自行计算变化，避免依赖接口的 diff 字段
    result["change"] = (
        result["today_receipt"]
        - result["yesterday_receipt"]
    )

    numeric_columns = [
        "yesterday_receipt",
        "today_receipt",
        "change",
    ]

    # 仓单数量一般是整数
    result[numeric_columns] = (
        result[numeric_columns].astype("int64")
    )

    result = result.drop_duplicates(
        subset=[
            "date",
            "metal",
            "warehouse",
        ],
        keep="last",
    )

    return result.reset_index(drop=True)


if __name__ == "__main__":
    # 单独测试这个文件
    data = fetch_gfex_warehouse_receipt(
        date="20260729",
        metal="PT",
    )

    print(data)