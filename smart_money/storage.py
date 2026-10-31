from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WORKBOOK_PATH = DATA_DIR / "SmartMoneyData.xlsx"
SETTINGS_PATH = DATA_DIR / "settings.json"

SHEET_COLUMNS: dict[str, list[str]] = {
    "Symbols": ["InsCode", "Symbol", "Name", "Market", "AddedAt"],
    "Portfolio": ["InsCode", "Symbol", "Quantity", "AverageCost", "UpdatedAt"],
    "DailyData": [
        "InsCode", "Symbol", "Date", "ClosePrice", "PreviousClose",
        "OpenPrice", "HighPrice", "LowPrice", "TotalVolume", "TotalTrades",
        "LegalBuyVolume", "LegalSellVolume", "LegalBuyValue", "LegalSellValue",
        "LegalBuyCount", "LegalSellCount", "RetailBuyVolume", "RetailSellVolume",
        "RetailBuyValue", "RetailSellValue", "RetailBuyCount", "RetailSellCount",
        "ClientDataAvailable", "Source", "FetchedAt",
    ],
    "Signals": [
        "InsCode", "Symbol", "Date", "Type", "Streak", "NetLegalVolume",
        "NetLegalPctVolume", "PriceChangePct", "Score", "Explanation",
    ],
    "SyncLog": [
        "StartedAt", "FinishedAt", "Trigger", "Status",
        "SymbolsProcessed", "RecordsUpserted", "Message",
    ],
}


def _empty_book() -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame(columns=columns) for name, columns in SHEET_COLUMNS.items()}


def load_book(path: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Load the local Excel workbook and guarantee the expected sheets/columns."""
    workbook = Path(path) if path else WORKBOOK_PATH
    if not workbook.exists():
        return _empty_book()

    try:
        existing = pd.read_excel(workbook, sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise RuntimeError(
            f"فایل اکسل قابل خواندن نیست: {workbook}\n"
            "اگر فایل در Excel باز است، آن را ببند و دوباره تلاش کن."
        ) from exc

    result: dict[str, pd.DataFrame] = {}
    for sheet, columns in SHEET_COLUMNS.items():
        frame = existing.get(sheet, pd.DataFrame())
        if frame is None:
            frame = pd.DataFrame()
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        result[sheet] = frame[columns].copy()

    if "Date" in result["DailyData"]:
        result["DailyData"]["Date"] = pd.to_datetime(result["DailyData"]["Date"], errors="coerce")
    return result


def save_book(book: dict[str, pd.DataFrame], path: Path | str | None = None) -> Path:
    """Write all managed sheets atomically to avoid corrupting the only data file."""
    workbook = Path(path) if path else WORKBOOK_PATH
    workbook.parent.mkdir(parents=True, exist_ok=True)
    prepared = _empty_book()
    for sheet, columns in SHEET_COLUMNS.items():
        frame = book.get(sheet, pd.DataFrame()).copy()
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        prepared[sheet] = frame[columns]

    fd, temp_name = tempfile.mkstemp(
        prefix=workbook.stem + "_", suffix=".tmp.xlsx", dir=str(workbook.parent)
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with pd.ExcelWriter(temp_path, engine="openpyxl", datetime_format="yyyy-mm-dd hh:mm:ss") as writer:
            for sheet, frame in prepared.items():
                frame.to_excel(writer, sheet_name=sheet, index=False)
        os.replace(temp_path, workbook)
    except PermissionError as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "فایل Excel در برنامه دیگری باز است یا اجازه نوشتن ندارد. "
            "فایل SmartMoneyData.xlsx را ببند و دوباره تلاش کن."
        ) from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return workbook


def upsert_rows(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    if incoming.empty:
        return existing.copy()
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=keys, keep="last")
    if "Date" in combined.columns:
        combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    return combined.sort_values(keys, kind="stable").reset_index(drop=True)


def add_instrument(
    instrument: dict[str, Any],
    quantity: float = 0,
    average_cost: float = 0,
    path: Path | str | None = None,
) -> None:
    book = load_book(path)
    ins_code = str(instrument["insCode"])
    symbol = str(instrument["symbol"])

    symbols = book["Symbols"]
    if ins_code in symbols["InsCode"].astype(str).values:
        idx = symbols.index[symbols["InsCode"].astype(str) == ins_code][0]
        for col, key in [("Symbol", "symbol"), ("Name", "name"), ("Market", "market")]:
            symbols.loc[idx, col] = instrument.get(key, "")
    else:
        symbols = pd.concat([symbols, pd.DataFrame([{
            "InsCode": ins_code,
            "Symbol": symbol,
            "Name": instrument.get("name", ""),
            "Market": instrument.get("market", ""),
            "AddedAt": datetime.now().astimezone().replace(tzinfo=None),
        }])], ignore_index=True)
    book["Symbols"] = symbols

    portfolio = book["Portfolio"]
    if ins_code in portfolio["InsCode"].astype(str).values:
        idx = portfolio.index[portfolio["InsCode"].astype(str) == ins_code][0]
        portfolio.loc[idx, ["Symbol", "Quantity", "AverageCost", "UpdatedAt"]] = [
            symbol, quantity, average_cost, datetime.now().astimezone().replace(tzinfo=None)
        ]
    else:
        portfolio = pd.concat([portfolio, pd.DataFrame([{
            "InsCode": ins_code, "Symbol": symbol, "Quantity": quantity,
            "AverageCost": average_cost,
            "UpdatedAt": datetime.now().astimezone().replace(tzinfo=None),
        }])], ignore_index=True)
    book["Portfolio"] = portfolio
    save_book(book, path)


def remove_instrument(ins_code: str, path: Path | str | None = None) -> None:
    book = load_book(path)
    code = str(ins_code)
    book["Symbols"] = book["Symbols"][book["Symbols"]["InsCode"].astype(str) != code]
    book["Portfolio"] = book["Portfolio"][book["Portfolio"]["InsCode"].astype(str) != code]
    book["DailyData"] = book["DailyData"][book["DailyData"]["InsCode"].astype(str) != code]
    book["Signals"] = book["Signals"][book["Signals"]["InsCode"].astype(str) != code]
    save_book(book, path)


def append_sync_log(
    trigger: str,
    status: str,
    symbols_processed: int,
    records_upserted: int,
    message: str = "",
    started_at: datetime | None = None,
    path: Path | str | None = None,
) -> None:
    book = load_book(path)
    now = datetime.now().astimezone().replace(tzinfo=None)
    row = {
        "StartedAt": started_at or now,
        "FinishedAt": now,
        "Trigger": trigger,
        "Status": status,
        "SymbolsProcessed": symbols_processed,
        "RecordsUpserted": records_upserted,
        "Message": message[:2000],
    }
    book["SyncLog"] = pd.concat([book["SyncLog"], pd.DataFrame([row])], ignore_index=True)
    book["SyncLog"] = book["SyncLog"].tail(500).reset_index(drop=True)
    save_book(book, path)


def merge_uploaded_workbook(uploaded_bytes: bytes, path: Path | str | None = None) -> None:
    """Merge a user backup with current rows, keeping the newest row per key."""
    import io

    try:
        incoming = pd.read_excel(io.BytesIO(uploaded_bytes), sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise RuntimeError("فایل انتخاب‌شده Excel معتبر نیست.") from exc

    current = load_book(path)
    key_map = {
        "Symbols": ["InsCode"],
        "Portfolio": ["InsCode"],
        "DailyData": ["InsCode", "Date"],
        "Signals": ["InsCode", "Date", "Type"],
        "SyncLog": ["StartedAt", "Trigger"],
    }
    for sheet, keys in key_map.items():
        frame = incoming.get(sheet)
        if frame is None or frame.empty:
            continue
        for column in SHEET_COLUMNS[sheet]:
            if column not in frame.columns:
                frame[column] = pd.NA
        current[sheet] = upsert_rows(current[sheet], frame[SHEET_COLUMNS[sheet]], keys)
    save_book(current, path)


def load_settings(path: Path | str | None = None) -> dict[str, Any]:
    import json

    settings_path = Path(path) if path else SETTINGS_PATH
    defaults: dict[str, Any] = {"auto_sync_hour": 18, "auto_sync_minute": 30}
    if not settings_path.exists():
        return defaults
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        return {**defaults, **loaded}
    except (OSError, ValueError, TypeError):
        return defaults


def save_settings(settings: dict[str, Any], path: Path | str | None = None) -> None:
    import json

    settings_path = Path(path) if path else SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
