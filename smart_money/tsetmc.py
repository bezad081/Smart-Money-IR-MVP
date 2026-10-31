from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://cdn.tsetmc.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}

session = requests.Session()
retry = Retry(
    total=3,
    connect=3,
    read=2,
    backoff_factor=0.7,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
session.mount("https://", adapter)
session.headers.update(HEADERS)


def _get_json(path: str) -> dict[str, Any]:
    url = BASE_URL.rstrip("/") + path
    try:
        response = session.get(url, timeout=(8, 25))
    except requests.RequestException as exc:
        raise RuntimeError(
            "ارتباط با TSETMC برقرار نشد. اینترنت و دسترسی شبکه را بررسی کن؛ "
            "ممکن است دسترسی از IP خارج ایران محدود باشد."
        ) from exc

    if response.status_code in (401, 403, 451):
        raise RuntimeError(
            f"دسترسی TSETMC با کد {response.status_code} رد شد. "
            "احتمال محدودیت IP یا User-Agent وجود دارد."
        )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "پاسخ TSETMC به‌جای JSON شامل صفحه خطا بود؛ احتمالاً دسترسی محدود شده است."
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ساختار پاسخ TSETMC قابل‌شناسایی نیست.")
    return payload


def _unwrap_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _as_number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            try:
                number = float(value)
                return number if pd.notna(number) else 0.0
            except (TypeError, ValueError):
                continue
    return 0.0


def _as_optional_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            try:
                number = float(value)
                return number if pd.notna(number) else None
            except (TypeError, ValueError):
                continue
    return None


def _read_gregorian_date(row: dict[str, Any]) -> pd.Timestamp | None:
    # TSETMC dates are Gregorian YYYYMMDD. ClientTypeHistory uses recDate.
    raw = row.get("dEven", row.get("recDate", row.get("deven", row.get("date"))))
    if raw is None or raw == "":
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) >= 8:
        try:
            return pd.Timestamp(datetime.strptime(digits[:8], "%Y%m%d"))
        except ValueError:
            return None
    return None


def search_instruments(query: str) -> list[dict[str, str]]:
    query = query.strip()
    if len(query) < 2:
        return []
    payload = _get_json("/Instrument/GetInstrumentSearch/" + requests.utils.quote(query, safe=""))
    results = _unwrap_rows(payload, "instrumentSearch")
    parsed = []
    seen: set[str] = set()
    for row in results:
        ins_code = str(row.get("insCode", "")).strip()
        symbol = str(row.get("lVal18AFC", row.get("symbol", ""))).strip()
        if not ins_code or not symbol or ins_code in seen:
            continue
        seen.add(ins_code)
        parsed.append({
            "insCode": ins_code,
            "symbol": symbol,
            "name": str(row.get("lVal30", row.get("name", ""))).strip(),
            "market": str(row.get("flowTitle", row.get("flow", ""))).strip(),
        })
    return parsed


def fetch_symbol_history(ins_code: str, symbol: str, days: int = 365) -> pd.DataFrame:
    """Download and align daily closing-price and legal/retail history."""
    price_payload = _get_json(
        f"/ClosingPrice/GetClosingPriceDailyList/{requests.utils.quote(str(ins_code), safe='')}/0"
    )
    client_payload = _get_json(
        f"/ClientType/GetClientTypeHistory/{requests.utils.quote(str(ins_code), safe='')}"
    )

    prices = _unwrap_rows(price_payload, "closingPriceDaily")
    clients = _unwrap_rows(client_payload, "clientType")
    client_by_date: dict[str, dict[str, Any]] = {}
    for row in clients:
        day = _read_gregorian_date(row)
        if day is not None:
            client_by_date[day.strftime("%Y-%m-%d")] = row

    cutoff = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(days=days)
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    output: list[dict[str, Any]] = []

    for price in prices:
        day = _read_gregorian_date(price)
        if day is None or day < cutoff:
            continue
        key = day.strftime("%Y-%m-%d")
        client = client_by_date.get(key)
        client = client or {}

        output.append({
            "InsCode": str(ins_code),
            "Symbol": symbol,
            "Date": day.to_pydatetime(),
            "ClosePrice": _as_optional_number(price, "pClosing", "pc"),
            "PreviousClose": _as_optional_number(price, "priceYesterday", "py"),
            "OpenPrice": _as_optional_number(price, "priceFirst", "pf"),
            "HighPrice": _as_optional_number(price, "priceMax", "pmax"),
            "LowPrice": _as_optional_number(price, "priceMin", "pmin"),
            "TotalVolume": _as_number(price, "qTotTran5J", "tvol", "qTotTran"),
            "TotalTrades": _as_number(price, "zTotTran", "tno"),
            "LegalBuyVolume": _as_number(client, "buy_N_Volume"),
            "LegalSellVolume": _as_number(client, "sell_N_Volume"),
            "LegalBuyValue": _as_number(client, "buy_N_Value"),
            "LegalSellValue": _as_number(client, "sell_N_Value"),
            "LegalBuyCount": _as_number(client, "buy_N_Count", "buy_CountN"),
            "LegalSellCount": _as_number(client, "sell_N_Count", "sell_CountN"),
            "RetailBuyVolume": _as_number(client, "buy_I_Volume"),
            "RetailSellVolume": _as_number(client, "sell_I_Volume"),
            "RetailBuyValue": _as_number(client, "buy_I_Value"),
            "RetailSellValue": _as_number(client, "sell_I_Value"),
            "RetailBuyCount": _as_number(client, "buy_I_Count", "buy_CountI"),
            "RetailSellCount": _as_number(client, "sell_I_Count", "sell_CountI"),
            "ClientDataAvailable": bool(client),
            "Source": "TSETMC CDN",
            "FetchedAt": fetched_at,
        })

    if not output:
        raise RuntimeError(
            f"برای نماد {symbol} تاریخچه قیمت قابل‌استفاده‌ای در بازه {days} روزه دریافت نشد."
        )

    frame = pd.DataFrame(output)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame.sort_values("Date").drop_duplicates(["InsCode", "Date"], keep="last").reset_index(drop=True)
