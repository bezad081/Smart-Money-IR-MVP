from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

PatternType = Literal["ACCUMULATION", "DISTRIBUTION"]
HORIZONS = (1, 3, 4, 5, 10)


def enrich_market_data(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data.copy()
    frame = data.copy()
    numeric = [
        "ClosePrice", "PreviousClose", "OpenPrice", "HighPrice", "LowPrice",
        "TotalVolume", "LegalBuyVolume", "LegalSellVolume", "LegalBuyValue",
        "LegalSellValue", "RetailBuyVolume", "RetailSellVolume",
        "RetailBuyValue", "RetailSellValue",
    ]
    for col in numeric:
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame["NetLegalVolume"] = frame["LegalBuyVolume"].fillna(0) - frame["LegalSellVolume"].fillna(0)
    frame["NetLegalValue"] = frame.get("LegalBuyValue", 0) - frame.get("LegalSellValue", 0)
    frame["NetLegalPctVolume"] = np.where(
        frame["TotalVolume"].fillna(0) > 0,
        frame["NetLegalVolume"] / frame["TotalVolume"] * 100,
        np.nan,
    )
    total_buy = frame["LegalBuyVolume"].fillna(0) + frame["RetailBuyVolume"].fillna(0)
    total_sell = frame["LegalSellVolume"].fillna(0) + frame["RetailSellVolume"].fillna(0)
    frame["LegalBuySharePct"] = np.where(total_buy > 0, frame["LegalBuyVolume"] / total_buy * 100, np.nan)
    frame["LegalSellSharePct"] = np.where(total_sell > 0, frame["LegalSellVolume"] / total_sell * 100, np.nan)
    frame["DailyChangePct"] = np.where(
        (frame["ClosePrice"].fillna(0) > 0) & (frame["PreviousClose"].fillna(0) > 0),
        (frame["ClosePrice"] / frame["PreviousClose"] - 1) * 100,
        np.nan,
    )
    if "ClientDataAvailable" in frame.columns:
        def _parse_available(value) -> bool:
            if pd.isna(value):
                return False
            if isinstance(value, (bool, np.bool_)):
                return bool(value)
            return str(value).strip().lower() in {"true", "1", "yes", "y"}

        frame["ClientDataAvailable"] = frame["ClientDataAvailable"].map(_parse_available)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame.sort_values(["InsCode", "Date"]).reset_index(drop=True)


def _pattern_at(history: pd.DataFrame, end_index: int, pattern_type: PatternType, streak: int = 3) -> bool:
    if end_index < streak - 1:
        return False
    window = history.iloc[end_index - streak + 1 : end_index + 1]
    required = ["ClosePrice", "PreviousClose", "TotalVolume", "NetLegalVolume", "NetLegalPctVolume"]
    if any(col not in window.columns for col in required):
        return False
    if window[required].isna().any().any() or (window["TotalVolume"] <= 0).any():
        return False
    if "ClientDataAvailable" in window.columns:
        available = window["ClientDataAvailable"].fillna(False).astype(bool)
        if not available.all():
            return False

    daily_returns = (window["ClosePrice"] / window["PreviousClose"] - 1) * 100
    net_volume = window["NetLegalVolume"]
    flow_ratio = window["NetLegalPctVolume"]

    if pattern_type == "ACCUMULATION":
        price_return = (window["ClosePrice"].iloc[-1] / window["PreviousClose"].iloc[0] - 1) * 100
        return bool(
            (net_volume > 0).all()
            and (flow_ratio >= 2.0).all()
            and price_return >= -8.0
            and price_return <= 1.5
            and daily_returns.mean() <= 0.8
        )

    prior = history.iloc[max(0, end_index - 59) : end_index + 1]
    if "HighPrice" in prior.columns:
        highs = pd.to_numeric(prior["HighPrice"], errors="coerce")
    else:
        highs = pd.to_numeric(prior["ClosePrice"], errors="coerce")
    rolling_high = highs.max(skipna=True)
    close = float(window["ClosePrice"].iloc[-1])
    near_high = pd.notna(rolling_high) and rolling_high > 0 and close >= rolling_high * 0.96
    return bool(
        (net_volume < 0).all()
        and (flow_ratio <= -2.0).all()
        and near_high
        and daily_returns.mean() <= 0.8
    )


def detect_latest_patterns(data: pd.DataFrame, streak: int = 3) -> pd.DataFrame:
    frame = enrich_market_data(data)
    rows: list[dict] = []
    if frame.empty:
        return pd.DataFrame(rows)

    for ins_code, history in frame.groupby("InsCode", sort=False):
        history = history.sort_values("Date").reset_index(drop=True)
        if len(history) < streak:
            continue
        end = len(history) - 1
        p_type: PatternType | None = None
        if _pattern_at(history, end, "ACCUMULATION", streak):
            p_type = "ACCUMULATION"
        elif _pattern_at(history, end, "DISTRIBUTION", streak):
            p_type = "DISTRIBUTION"
        if p_type is None:
            continue

        window = history.iloc[-streak:]
        net = float(window["NetLegalVolume"].sum())
        volume = float(window["TotalVolume"].sum())
        net_ratio = net / volume * 100 if volume > 0 else np.nan
        first_prev = float(window["PreviousClose"].iloc[0])
        last_close = float(window["ClosePrice"].iloc[-1])
        price_change = (last_close / first_prev - 1) * 100 if first_prev > 0 else np.nan
        average_intensity = float(window["NetLegalPctVolume"].abs().mean())
        score = int(min(100, 55 + (streak / 3) * 20 + min(25, average_intensity * 1.2)))
        symbol = str(history["Symbol"].iloc[-1])
        rows.append({
            "InsCode": str(ins_code),
            "Symbol": symbol,
            "Date": history["Date"].iloc[-1],
            "Type": p_type,
            "Streak": streak,
            "NetLegalVolume": net,
            "NetLegalPctVolume": net_ratio,
            "PriceChangePct": price_change,
            "Score": score,
            "Explanation": (
                "حقوقی در چند جلسه متوالی خالص خریدار بوده و قیمت رشد محدودی داشته است."
                if p_type == "ACCUMULATION"
                else "حقوقی در چند جلسه متوالی خالص فروشنده بوده و قیمت نزدیک سقف اخیر است."
            ),
        })

    return pd.DataFrame(rows).sort_values(["Score", "Symbol"], ascending=[False, True]).reset_index(drop=True) if rows else pd.DataFrame(rows)


def backtest_patterns(data: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS, streak: int = 3) -> pd.DataFrame:
    frame = enrich_market_data(data)
    results: list[dict] = []
    if frame.empty:
        return pd.DataFrame(results)

    for ins_code, history in frame.groupby("InsCode", sort=False):
        history = history.sort_values("Date").reset_index(drop=True)
        symbol = str(history["Symbol"].iloc[-1])
        for p_type in ("ACCUMULATION", "DISTRIBUTION"):
            for horizon in horizons:
                returns: list[float] = []
                last_signal = -10
                for index in range(streak - 1, len(history) - horizon):
                    if index - last_signal < streak:
                        continue
                    if not _pattern_at(history, index, p_type, streak):
                        continue
                    entry = pd.to_numeric(pd.Series([history.loc[index, "ClosePrice"]]), errors="coerce").iloc[0]
                    exit_price = pd.to_numeric(pd.Series([history.loc[index + horizon, "ClosePrice"]]), errors="coerce").iloc[0]
                    if pd.isna(entry) or pd.isna(exit_price) or entry <= 0:
                        continue
                    returns.append((float(exit_price) / float(entry) - 1) * 100)
                    last_signal = index

                values = np.asarray(returns, dtype=float)
                success = values > 0 if p_type == "ACCUMULATION" else values < 0
                results.append({
                    "Symbol": symbol,
                    "Type": p_type,
                    "Horizon": horizon,
                    "Samples": len(values),
                    "SuccessRatePct": float(success.mean() * 100) if len(values) else np.nan,
                    "AverageReturnPct": float(values.mean()) if len(values) else np.nan,
                    "MedianReturnPct": float(np.median(values)) if len(values) else np.nan,
                    "BestReturnPct": float(values.max()) if len(values) else np.nan,
                    "WorstReturnPct": float(values.min()) if len(values) else np.nan,
                })
    return pd.DataFrame(results)


def build_signal_history(data: pd.DataFrame) -> pd.DataFrame:
    """Build all historical pattern occurrences for inspection/backtest audit."""
    frame = enrich_market_data(data)
    records: list[dict] = []
    for ins_code, history in frame.groupby("InsCode", sort=False):
        history = history.sort_values("Date").reset_index(drop=True)
        for index in range(2, len(history)):
            for p_type in ("ACCUMULATION", "DISTRIBUTION"):
                if _pattern_at(history, index, p_type, 3):
                    window = history.iloc[index - 2 : index + 1]
                    volume = float(window["TotalVolume"].sum())
                    net = float(window["NetLegalVolume"].sum())
                    records.append({
                        "InsCode": str(ins_code),
                        "Symbol": str(history["Symbol"].iloc[index]),
                        "Date": history["Date"].iloc[index],
                        "Type": p_type,
                        "Streak": 3,
                        "NetLegalVolume": net,
                        "NetLegalPctVolume": net / volume * 100 if volume else np.nan,
                        "PriceChangePct": (
                            float(window["ClosePrice"].iloc[-1]) /
                            float(window["PreviousClose"].iloc[0]) - 1
                        ) * 100,
                        "Score": 0,
                        "Explanation": "الگو بر اساس قواعد نسخه فعلی ثبت شده است.",
                    })
    return pd.DataFrame(records)
