from __future__ import annotations

import threading
import time
from datetime import datetime

import pandas as pd

from .analytics import build_signal_history
from .storage import append_sync_log, load_book, save_book, upsert_rows
from .tsetmc import fetch_symbol_history

_sync_lock = threading.Lock()


def sync_all(trigger: str = "MANUAL") -> dict:
    """Fetch the latest one-year price/client history for every tracked instrument."""
    if not _sync_lock.acquire(blocking=False):
        raise RuntimeError("یک همگام‌سازی دیگر در حال اجراست؛ کمی بعد دوباره تلاش کن.")

    started = datetime.now().astimezone().replace(tzinfo=None)
    symbols_processed = 0
    records_upserted = 0
    errors: list[str] = []

    try:
        book = load_book()
        symbols = book["Symbols"].copy()
        if symbols.empty:
            append_sync_log(trigger, "EMPTY", 0, 0, "هنوز نمادی برای دریافت اطلاعات انتخاب نشده است.", started)
            return {"status": "EMPTY", "symbols_processed": 0, "records_upserted": 0, "errors": []}

        for _, item in symbols.iterrows():
            ins_code = str(item.get("InsCode", "")).strip()
            symbol = str(item.get("Symbol", "")).strip()
            if not ins_code or ins_code.lower() == "nan":
                continue
            try:
                incoming = fetch_symbol_history(ins_code, symbol, days=365)
                book["DailyData"] = upsert_rows(
                    book["DailyData"], incoming, ["InsCode", "Date"]
                )
                symbols_processed += 1
                records_upserted += len(incoming)
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
            time.sleep(0.65)

        # Recompute historical patterns from the saved, deduplicated workbook history.
        book["Signals"] = build_signal_history(book["DailyData"])
        save_book(book)

        if errors and symbols_processed:
            status = "PARTIAL"
        elif errors:
            status = "FAILED"
        else:
            status = "SUCCESS"
        append_sync_log(
            trigger=trigger,
            status=status,
            symbols_processed=symbols_processed,
            records_upserted=records_upserted,
            message=" | ".join(errors) if errors else "دریافت و ذخیره تاریخچه با موفقیت انجام شد.",
            started_at=started,
        )
        return {
            "status": status,
            "symbols_processed": symbols_processed,
            "records_upserted": records_upserted,
            "errors": errors,
        }
    finally:
        _sync_lock.release()
