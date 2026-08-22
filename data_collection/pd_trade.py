from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


OUTPUT_COLUMNS = [
    "数据年月",
    "商品编码",
    "商品名称",
    "贸易方式编码",
    "贸易方式名称",
    "贸易伙伴编码",
    "贸易伙伴名称",
    "注册地编码",
    "注册地名称",
    "第一数量",
    "第一计量单位",
    "数量（吨）",
    "人民币",
]

SOURCE_COLUMNS = [
    "商品编码",
    "商品名称",
    "贸易方式编码",
    "贸易方式名称",
    "贸易伙伴编码",
    "贸易伙伴名称",
    "注册地编码",
    "注册地名称",
    "第一数量",
    "第一计量单位",
    "人民币",
]


@dataclass(frozen=True)
class TradeFile:
    name: str
    source_prefix: str
    target_name: str


TRADE_FILES = (
    TradeFile("进口", "钯进口", "pd_cn_import.csv"),
    TradeFile("出口", "钯出口", "pd_cn_export.csv"),
)


def _read_csv(path: Path) -> pd.DataFrame:
    last_error = None
    for encoding in ("gb18030", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(f"无法识别CSV编码：{path}") from last_error


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise_month(value: str) -> str:
    month = re.sub(r"[^0-9]", "", str(value))
    if not re.fullmatch(r"\d{6}", month):
        raise ValueError("trade_month必须是YYYYMM格式，例如202606")
    datetime.strptime(month, "%Y%m")
    return month


def _next_month(month: str) -> str:
    value = datetime.strptime(month, "%Y%m")
    if value.month == 12:
        return f"{value.year + 1}01"
    return f"{value.year}{value.month + 1:02d}"


def _latest_month(path: Path) -> str:
    frame = _read_csv(path)
    if "数据年月" not in frame.columns or frame.empty:
        raise ValueError(f"历史文件缺少有效的数据年月：{path}")
    months = frame["数据年月"].astype(str).str.replace(r"\D", "", regex=True)
    months = months[months.str.fullmatch(r"\d{6}", na=False)]
    if months.empty:
        raise ValueError(f"历史文件没有有效月份：{path}")
    return months.max()


def _month_from_source_name(path: Path, prefix: str) -> str | None:
    match = re.fullmatch(rf"{re.escape(prefix)}(\d{{4}}|\d{{6}})\.csv", path.name)
    if not match:
        return None
    value = match.group(1)
    if len(value) == 4:
        value = "20" + value
    return _normalise_month(value)


def _find_sources(data_folder: Path, trade_month: str | None) -> tuple[str, dict[str, Path]]:
    available: dict[str, dict[str, Path]] = {}
    for item in TRADE_FILES:
        matches = {}
        for path in data_folder.glob(f"{item.source_prefix}*.csv"):
            month = _month_from_source_name(path, item.source_prefix)
            if month:
                matches[month] = path
        available[item.name] = matches

    if trade_month is not None:
        month = _normalise_month(trade_month)
    else:
        common_months = set.intersection(
            *(set(available[item.name]) for item in TRADE_FILES)
        )
        if not common_months:
            raise FileNotFoundError(
                "没有找到月份一致的钯进口YYYYMM.csv和钯出口YYYYMM.csv"
            )
        month = max(common_months)

    sources = {}
    for item in TRADE_FILES:
        source = available[item.name].get(month)
        if source is None:
            raise FileNotFoundError(
                f"缺少{month}对应的{item.source_prefix}YYMM.csv"
            )
        sources[item.name] = source
    return month, sources


def _source_signature(sources: dict[str, Path]) -> dict[str, str]:
    return {path.name: _file_hash(path) for path in sources.values()}


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _prepare_source(path: Path, month: str) -> pd.DataFrame:
    frame = _read_csv(path)
    frame = frame.loc[:, ~frame.columns.astype(str).str.startswith("Unnamed:")]

    missing = [column for column in SOURCE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}缺少字段：{', '.join(missing)}")
    if frame.empty:
        raise ValueError(f"{path.name}没有数据")

    frame = frame[SOURCE_COLUMNS].copy()
    for column in ("商品编码", "贸易方式编码", "贸易伙伴编码", "注册地编码"):
        frame[column] = frame[column].astype(str).str.strip()

    quantity = pd.to_numeric(
        frame["第一数量"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    if quantity.isna().any():
        bad_rows = int(quantity.isna().sum())
        raise ValueError(f"{path.name}有{bad_rows}行第一数量无法转换为数字")

    units = set(frame["第一计量单位"].dropna().astype(str).str.strip())
    if units != {"克"}:
        raise ValueError(f"{path.name}第一计量单位不是统一的克：{sorted(units)}")

    rmb = pd.to_numeric(
        frame["人民币"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    if rmb.isna().any():
        bad_rows = int(rmb.isna().sum())
        raise ValueError(f"{path.name}有{bad_rows}行人民币金额无法转换为数字")

    frame.insert(0, "数据年月", month)
    frame["第一数量"] = quantity.map(lambda value: format(value, ".15g"))
    frame["数量（吨）"] = quantity / 1_000_000
    frame["人民币"] = rmb.map(lambda value: format(value, ".15g"))

    if not frame["商品编码"].str.startswith("71102").all():
        raise ValueError(f"{path.name}包含非钯商品编码，请检查海关查询条件")

    return frame[OUTPUT_COLUMNS]


def _merge_month(history_path: Path, new_rows: pd.DataFrame, month: str) -> pd.DataFrame:
    history = _read_csv(history_path)
    missing = [column for column in OUTPUT_COLUMNS if column not in history.columns]
    if missing:
        raise ValueError(f"{history_path.name}缺少字段：{', '.join(missing)}")

    history = history[OUTPUT_COLUMNS].copy()
    history["数据年月"] = history["数据年月"].astype(str).str.replace(
        r"\D", "", regex=True
    )
    history = history[history["数据年月"] != month]
    merged = pd.concat([history, new_rows], ignore_index=True)

    sort_columns = [
        "数据年月",
        "商品编码",
        "贸易方式编码",
        "贸易伙伴编码",
        "注册地编码",
    ]
    merged = merged.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    return merged


def update_pd_trade_csv(
    data_folder: str | os.PathLike = "data",
    trade_month: str | None = None,
    backup: bool = True,
) -> dict:
    """Merge month-stamped Customs downloads into palladium history CSV files.

    Source filenames must include the month, such as ``钯进口2606.csv`` and
    ``钯出口2606.csv``. Six-digit forms such as ``钯进口202606.csv`` are also
    accepted. If ``trade_month`` is omitted, the latest common source month is
    used. Identical source files are skipped automatically.
    """

    folder = Path(data_folder)
    state_path = folder / ".pd_trade_update_state.json"

    month, sources = _find_sources(folder, trade_month)
    for item in TRADE_FILES:
        target = folder / item.target_name
        if not target.exists():
            raise FileNotFoundError(f"缺少历史数据文件：{target}")

    signature = _source_signature(sources)
    state = _load_state(state_path)
    if trade_month is None and state.get("source_sha256") == signature:
        month = state.get("trade_month")
        print(f"钯进出口下载文件没有变化，跳过更新（已处理月份：{month}）")
        return {"status": "skipped", "trade_month": month}

    prepared = {}
    merged = {}
    for item in TRADE_FILES:
        source_path = sources[item.name]
        target_path = folder / item.target_name
        prepared[item.name] = _prepare_source(source_path, month)
        merged[item.name] = _merge_month(target_path, prepared[item.name], month)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_paths = {}
    try:
        for item in TRADE_FILES:
            target = folder / item.target_name
            temp = folder / f".{item.target_name}.{timestamp}.tmp"
            merged[item.name].to_csv(temp, index=False, encoding="gb18030")
            temp_paths[item.name] = temp

        for item in TRADE_FILES:
            target = folder / item.target_name
            if backup:
                backup_path = folder / f"{target.stem}_{timestamp}.bak.csv"
                shutil.copy2(target, backup_path)
            os.replace(temp_paths[item.name], target)

        state_payload = {
            "trade_month": month,
            "source_sha256": signature,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "rows": {
                item.name: len(prepared[item.name]) for item in TRADE_FILES
            },
        }
        state_path.write_text(
            json.dumps(state_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    finally:
        for temp in temp_paths.values():
            if temp.exists():
                temp.unlink()

    result = {
        "status": "updated",
        "trade_month": month,
        "rows": {item.name: len(prepared[item.name]) for item in TRADE_FILES},
        "totals_tonnes": {
            item.name: float(prepared[item.name]["数量（吨）"].sum())
            for item in TRADE_FILES
        },
    }
    print(
        f"钯进出口数据已更新至{month}："
        f"进口{result['rows']['进口']}行，出口{result['rows']['出口']}行"
    )
    return result
