from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from smart_money.analytics import HORIZONS, backtest_patterns, detect_latest_patterns, enrich_market_data
from smart_money.scheduler import next_run_time, start_scheduler, update_schedule
from smart_money.storage import (
    WORKBOOK_PATH,
    add_instrument,
    load_book,
    merge_uploaded_workbook,
    remove_instrument,
    save_book,
)
from smart_money.sync import sync_all
from smart_money.tsetmc import search_instruments

st.set_page_config(
    page_title="Smart Money IR",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp {font-family:'Vazirmatn',Tahoma,sans-serif;}
.stApp {background: radial-gradient(circle at 75% -20%, #1c3150 0, #0b1422 42%);}
.block-container {padding-top:1.5rem; padding-bottom:2rem; max-width:1600px;}
[data-testid="stSidebar"] {background:#0b1422; border-left:1px solid #26384f;}
h1,h2,h3 {font-weight:700;}
[data-testid="stMetric"] {background:linear-gradient(145deg,#172a42,#111e31); border:1px solid #2a3d56; padding:16px 18px; border-radius:14px;}
[data-testid="stMetricLabel"] {font-size:0.85rem; color:#9bacc0;}
[data-testid="stMetricValue"] {font-size:1.65rem; color:#f2f6fb;}
div.stButton > button[kind="primary"] {background:#2dd4a7; color:#06251d; border:0; font-weight:700; border-radius:9px;}
div.stButton > button {border-radius:9px;}
[data-testid="stDataFrame"] {border:1px solid #26384f; border-radius:10px;}
div[data-testid="stExpander"] {border:1px solid #2b3f57; border-radius:10px;}
.small-muted {color:#94a5ba; font-size:0.82rem;}
.kicker {color:#7e91aa; font-size:0.72rem; letter-spacing:1.3px;}
.positive {color:#41d3a2;} .negative {color:#f17d89;}
</style>
""", unsafe_allow_html=True)


def fa_number(value, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return format(float(value), f",.{digits}f").replace(",", "٬").replace(".", "٫")


def date_text(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def percent_text(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{fa_number(value, digits)}٪"


def safe_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def show_empty(message: str) -> None:
    st.info(message)


def get_book() -> dict[str, pd.DataFrame]:
    book = load_book()
    if not WORKBOOK_PATH.exists():
        save_book(book)
    return book


def sync_button(label: str = "همگام‌سازی دستی") -> None:
    if st.button("↻ " + label, type="primary", use_container_width=True):
        try:
            with st.spinner("در حال دریافت تاریخچه قیمت و حقیقی/حقوقی از TSETMC..."):
                result = sync_all("MANUAL")
            if result["status"] == "SUCCESS":
                st.success(
                    f"دریافت پایان یافت؛ {fa_number(result['symbols_processed'])} نماد "
                    f"و {fa_number(result['records_upserted'])} ردیف دریافت/به‌روزرسانی شد."
                )
            elif result["status"] == "PARTIAL":
                st.warning("بخشی از نمادها دریافت شدند. خطاها در گزارش همگام‌سازی ذخیره شده‌اند.")
            elif result["status"] == "EMPTY":
                st.info("ابتدا از بخش «نمادها و پرتفوی» حداقل یک نماد اضافه کن.")
            else:
                st.error("همگام‌سازی انجام نشد. گزارش اجرا را بررسی کن.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def add_symbol_ui() -> None:
    st.subheader("افزودن نماد به فهرست پیگیری")
    with st.form("symbol_search_form"):
        query = st.text_input("نام یا نماد", placeholder="مثلاً فولاد، فملی، شستا")
        submitted = st.form_submit_button("جست‌وجو در TSETMC", type="primary")
    if submitted:
        if len(query.strip()) < 2:
            st.warning("حداقل دو حرف وارد کن.")
        else:
            try:
                st.session_state["symbol_search_results"] = search_instruments(query)
                st.session_state["symbol_search_error"] = ""
            except Exception as exc:
                st.session_state["symbol_search_error"] = str(exc)
                st.session_state["symbol_search_results"] = []

    if st.session_state.get("symbol_search_error"):
        st.error(st.session_state["symbol_search_error"])

    results = st.session_state.get("symbol_search_results", [])
    if results:
        st.caption("نماد موردنظرت را انتخاب کن:")
        for idx, item in enumerate(results[:15]):
            left, middle, right = st.columns([2, 4, 2])
            left.markdown(f"**{item['symbol']}**")
            middle.write(item.get("name", "") + " · " + item.get("market", ""))
            if right.button("افزودن", key=f"add_symbol_{item['insCode']}_{idx}"):
                try:
                    add_instrument(item)
                    st.session_state["symbol_search_results"] = []
                    st.success(f"{item['symbol']} به فهرست اضافه شد.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def fmt_table(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result = result.rename(columns=mapping)
    return result


def price_chart(history: pd.DataFrame, title: str = "روند قیمت") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=history["Date"],
        open=history["OpenPrice"],
        high=history["HighPrice"],
        low=history["LowPrice"],
        close=history["ClosePrice"],
        name="قیمت",
        increasing_line_color="#32c997",
        decreasing_line_color="#ed727e",
    ))
    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=410,
        margin=dict(l=15, r=15, t=55, b=15),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.1, x=1, xanchor="right"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def flow_chart(history: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=history["Date"], y=history["LegalBuyVolume"],
        name="خرید حقوقی", marker_color="#36c99a",
    ))
    fig.add_trace(go.Bar(
        x=history["Date"], y=-history["LegalSellVolume"],
        name="فروش حقوقی", marker_color="#e87583",
    ))
    fig.add_trace(go.Scatter(
        x=history["Date"], y=history["NetLegalVolume"],
        name="خالص خرید حقوقی", mode="lines",
        line=dict(color="#f0c66a", width=2),
    ))
    fig.update_layout(
        title="رفتار خرید و فروش حقوقی",
        template="plotly_dark",
        height=360,
        barmode="relative",
        margin=dict(l=15, r=15, t=55, b=15),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right"),
    )
    return fig


def render_overview(book: dict[str, pd.DataFrame]) -> None:
    st.markdown('<div class="kicker">SMART MONEY / MARKET BEHAVIOUR</div>', unsafe_allow_html=True)
    st.title("داشبورد تحلیل رفتار حقوقی")
    st.caption("نمای کلی نمادهای تحت پیگیری، جریان پول حقوقی و الگوهای احتمالی انباشت و توزیع.")

    data = enrich_market_data(book["DailyData"])
    symbols = book["Symbols"]
    portfolio = book["Portfolio"]
    signals = detect_latest_patterns(data)

    if data.empty:
        latest_day = None
        latest_rows = pd.DataFrame()
    else:
        latest_day = data["Date"].max()
        latest_rows = data[data["Date"] == latest_day].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("نمادهای تحت پیگیری", fa_number(len(symbols)))
    c2.metric("نمادهای دارای تاریخچه", fa_number(data["InsCode"].nunique() if not data.empty else 0))
    c3.metric("هشدار انباشت", fa_number((signals["Type"] == "ACCUMULATION").sum() if not signals.empty else 0))
    c4.metric("هشدار توزیع", fa_number((signals["Type"] == "DISTRIBUTION").sum() if not signals.empty else 0))

    left, right = st.columns([1.6, 1])
    with left:
        st.subheader("بیشترین خالص خرید حقوقی در آخرین روز موجود")
        if latest_rows.empty:
            show_empty("هنوز داده‌ای دریافت نشده است. از بخش نمادها، نماد اضافه و همگام‌سازی را اجرا کن.")
        else:
            top = latest_rows.sort_values("NetLegalVolume", ascending=False).head(12)
            chart = px.bar(
                top.sort_values("NetLegalVolume"),
                x="NetLegalVolume",
                y="Symbol",
                orientation="h",
                color="NetLegalVolume",
                color_continuous_scale=["#e87583", "#263b52", "#35c99a"],
                title=f"آخرین تاریخ موجود: {date_text(latest_day)}",
                labels={"NetLegalVolume": "خالص خرید حقوقی (حجم)", "Symbol": "نماد"},
            )
            chart.update_layout(template="plotly_dark", height=390, coloraxis_showscale=False,
                                margin=dict(l=10, r=10, t=50, b=10),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(chart, use_container_width=True)
    with right:
        st.subheader("آخرین الگوهای شناسایی‌شده")
        if signals.empty:
            show_empty("در آخرین داده نمادها الگوی فعالی شناسایی نشده است.")
        else:
            for _, signal in signals.head(8).iterrows():
                label = "🟢 انباشت احتمالی" if signal["Type"] == "ACCUMULATION" else "🔴 توزیع احتمالی"
                st.markdown(f"**{signal['Symbol']}** · {label}")
                st.caption(
                    f"خالص جریان: {fa_number(signal['NetLegalVolume'])} | "
                    f"تغییر قیمت: {percent_text(signal['PriceChangePct'], 2)} | "
                    f"امتیاز قواعد: {fa_number(signal['Score'])}/100"
                )
                st.divider()

    st.subheader("خلاصه آخرین روز معاملات")
    if latest_rows.empty:
        show_empty("پس از دریافت داده، خلاصه روزانه در این قسمت نمایش داده می‌شود.")
    else:
        display = latest_rows[[
            "Symbol", "ClosePrice", "DailyChangePct", "TotalVolume",
            "LegalBuyVolume", "LegalSellVolume", "NetLegalVolume",
            "NetLegalPctVolume", "LegalBuySharePct", "LegalSellSharePct",
        ]].copy()
        display = display.rename(columns={
            "Symbol": "نماد", "ClosePrice": "قیمت پایانی",
            "DailyChangePct": "تغییر قیمت٪", "TotalVolume": "حجم معاملات",
            "LegalBuyVolume": "خرید حقوقی", "LegalSellVolume": "فروش حقوقی",
            "NetLegalVolume": "خالص خرید حقوقی", "NetLegalPctVolume": "خالص/حجم٪",
            "LegalBuySharePct": "سهم حقوقی از خرید٪", "LegalSellSharePct": "سهم حقوقی از فروش٪",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)


def render_symbols(book: dict[str, pd.DataFrame]) -> None:
    st.title("نمادها و پرتفوی")
    st.caption("نمادها را به فهرست پیگیری اضافه کن. دریافت تاریخچه یک‌ساله برای همین نمادها انجام می‌شود.")
    add_symbol_ui()
    st.divider()

    symbols = book["Symbols"].copy()
    portfolio = book["Portfolio"].copy()
    if symbols.empty:
        show_empty("فهرست نمادها خالی است.")
        return

    st.subheader("نمادهای تحت پیگیری")
    for _, item in symbols.iterrows():
        ins_code = str(item["InsCode"])
        symbol = str(item["Symbol"])
        left, mid, right = st.columns([2, 4, 1])
        left.markdown(f"**{symbol}**")
        mid.write(str(item.get("Name", "") or "") + " · " + str(item.get("Market", "") or ""))
        if right.button("حذف", key=f"remove_{ins_code}"):
            try:
                remove_instrument(ins_code)
                st.warning(f"{symbol} از فهرست و تاریخچه محلی حذف شد.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("جزئیات پرتفوی")
    current = portfolio.set_index("InsCode") if not portfolio.empty else pd.DataFrame()
    with st.form("portfolio_edit_form"):
        edits = []
        for _, item in symbols.iterrows():
            code = str(item["InsCode"])
            sym = str(item["Symbol"])
            old = current.loc[code] if not current.empty and code in current.index else None
            quantity = float(old["Quantity"]) if old is not None and pd.notna(old["Quantity"]) else 0.0
            cost = float(old["AverageCost"]) if old is not None and pd.notna(old["AverageCost"]) else 0.0
            a, b, c = st.columns([2, 2, 2])
            a.write(sym)
            q = b.number_input(f"تعداد {sym}", min_value=0.0, value=quantity, step=100.0, key=f"qty_{code}")
            p = c.number_input(f"میانگین خرید {sym}", min_value=0.0, value=cost, step=100.0, key=f"cost_{code}")
            edits.append({"InsCode": code, "Symbol": sym, "Quantity": q, "AverageCost": p,
                          "UpdatedAt": datetime.now().astimezone().replace(tzinfo=None)})
        if st.form_submit_button("ذخیره پرتفوی", type="primary"):
            updated = pd.DataFrame(edits)
            book_now = load_book()
            book_now["Portfolio"] = updated
            save_book(book_now)
            st.success("اطلاعات پرتفوی ذخیره شد.")
            st.rerun()


def render_scanner(book: dict[str, pd.DataFrame]) -> None:
    st.title("اسکنر رفتار حقوقی")
    st.caption("رتبه‌بندی نمادها بر اساس جریان حقوقی در آخرین تاریخ موجود یا بازه انتخابی.")
    data = enrich_market_data(book["DailyData"])
    if data.empty:
        show_empty("برای شروع، نماد اضافه کن و تاریخچه را همگام‌سازی کن.")
        return

    max_date = data["Date"].max()
    min_date = data["Date"].min()
    end_default = max_date.date() if not pd.isna(max_date) else date.today()
    start_default = max(min_date.date(), end_default - timedelta(days=20)) if not pd.isna(min_date) else end_default
    c1, c2, c3 = st.columns([1, 1, 2])
    start_date = c1.date_input("از تاریخ", value=start_default)
    end_date = c2.date_input("تا تاریخ", value=end_default)
    ranking = c3.selectbox("مرتب‌سازی", ["بیشترین خالص خرید حقوقی", "بیشترین سهم خرید حقوقی", "بیشترین خالص فروش حقوقی"])
    filtered = data[(data["Date"].dt.date >= start_date) & (data["Date"].dt.date <= end_date)].copy()
    if filtered.empty:
        show_empty("در این بازه داده‌ای وجود ندارد.")
        return
    grouped = filtered.groupby(["InsCode", "Symbol"], as_index=False).agg({
        "LegalBuyVolume": "sum", "LegalSellVolume": "sum",
        "RetailBuyVolume": "sum", "RetailSellVolume": "sum",
        "TotalVolume": "sum", "ClientDataAvailable": "sum",
    })
    grouped["NetLegalVolume"] = grouped["LegalBuyVolume"] - grouped["LegalSellVolume"]
    grouped["NetLegalPctVolume"] = (
        grouped["NetLegalVolume"] / grouped["TotalVolume"].where(grouped["TotalVolume"] > 0) * 100
    )
    total_buy = grouped["LegalBuyVolume"] + grouped["RetailBuyVolume"]
    total_sell = grouped["LegalSellVolume"] + grouped["RetailSellVolume"]
    grouped["LegalBuySharePct"] = grouped["LegalBuyVolume"].div(total_buy.where(total_buy > 0)) * 100
    grouped["LegalSellSharePct"] = grouped["LegalSellVolume"].div(total_sell.where(total_sell > 0)) * 100

    sort_col = "NetLegalVolume"
    ascending = False
    if ranking == "بیشترین سهم خرید حقوقی":
        sort_col = "LegalBuySharePct"
    elif ranking == "بیشترین خالص فروش حقوقی":
        sort_col = "NetLegalVolume"
        ascending = True
    ranked = grouped.sort_values(sort_col, ascending=ascending).head(30)
    st.dataframe(ranked.rename(columns={
        "Symbol": "نماد", "LegalBuyVolume": "خرید حقوقی",
        "LegalSellVolume": "فروش حقوقی", "TotalVolume": "حجم کل",
        "NetLegalVolume": "خالص خرید حقوقی", "NetLegalPctVolume": "خالص/حجم٪",
        "LegalBuySharePct": "سهم خرید حقوقی٪", "LegalSellSharePct": "سهم فروش حقوقی٪",
        "ClientDataAvailable": "روزهای دارای داده حقوقی",
    }), use_container_width=True, hide_index=True)

    plot = px.bar(
        ranked.sort_values("NetLegalVolume"),
        x="NetLegalVolume", y="Symbol", orientation="h",
        color="NetLegalVolume", color_continuous_scale=["#e87583", "#2b4058", "#35c99a"],
        labels={"NetLegalVolume": "خالص خرید حقوقی", "Symbol": "نماد"},
    )
    plot.update_layout(template="plotly_dark", height=520, coloraxis_showscale=False,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(plot, use_container_width=True)


def render_analysis(book: dict[str, pd.DataFrame]) -> None:
    st.title("تحلیل نماد")
    data = enrich_market_data(book["DailyData"])
    symbols = book["Symbols"]
    if data.empty or symbols.empty:
        show_empty("ابتدا نماد اضافه و تاریخچه آن را همگام‌سازی کن.")
        return

    options = dict(zip(symbols["Symbol"].astype(str), symbols["InsCode"].astype(str)))
    selected_symbol = st.selectbox("انتخاب نماد", list(options.keys()))
    ins_code = options[selected_symbol]
    history = data[data["InsCode"].astype(str) == ins_code].sort_values("Date").copy()
    if history.empty:
        show_empty("برای این نماد هنوز تاریخچه‌ای ثبت نشده است.")
        return

    min_day = history["Date"].min().date()
    max_day = history["Date"].max().date()
    c1, c2 = st.columns(2)
    start_date = c1.date_input("شروع نمودار", value=max(min_day, max_day - timedelta(days=180)), key="analysis_start")
    end_date = c2.date_input("پایان نمودار", value=max_day, key="analysis_end")
    history = history[(history["Date"].dt.date >= start_date) & (history["Date"].dt.date <= end_date)]
    if history.empty:
        show_empty("در بازه انتخابی داده‌ای وجود ندارد.")
        return

    latest = history.iloc[-1]
    a, b, c, d = st.columns(4)
    a.metric("آخرین قیمت پایانی", fa_number(latest["ClosePrice"]))
    b.metric("تغییر روزانه", percent_text(latest["DailyChangePct"], 2))
    c.metric("خالص خرید حقوقی", fa_number(latest["NetLegalVolume"]))
    d.metric("سهم خرید حقوقی", percent_text(latest["LegalBuySharePct"], 1))
    st.plotly_chart(price_chart(history, f"نمودار قیمت {selected_symbol}"), use_container_width=True)
    st.plotly_chart(flow_chart(history), use_container_width=True)

    st.subheader("جدول روزانه حقیقی و حقوقی")
    view = history[[
        "Date", "ClosePrice", "DailyChangePct", "TotalVolume",
        "LegalBuyVolume", "LegalSellVolume", "NetLegalVolume",
        "LegalBuySharePct", "LegalSellSharePct", "ClientDataAvailable",
    ]].copy()
    view = view.rename(columns={
        "Date": "تاریخ", "ClosePrice": "قیمت پایانی", "DailyChangePct": "تغییر٪",
        "TotalVolume": "حجم معاملات", "LegalBuyVolume": "خرید حقوقی",
        "LegalSellVolume": "فروش حقوقی", "NetLegalVolume": "خالص خرید حقوقی",
        "LegalBuySharePct": "سهم حقوقی از خرید٪", "LegalSellSharePct": "سهم حقوقی از فروش٪",
        "ClientDataAvailable": "داده حقیقی/حقوقی",
    }).sort_values("تاریخ", ascending=False)
    st.dataframe(view, use_container_width=True, hide_index=True)


def render_patterns(book: dict[str, pd.DataFrame]) -> None:
    st.title("الگوهای انباشت و توزیع")
    st.caption("قواعد فعلی برای پیدا کردن رفتارهای تکرارشونده است؛ هیچ الگویی تضمین رشد یا افت قیمت نیست.")
    data = enrich_market_data(book["DailyData"])
    patterns = detect_latest_patterns(data)
    if patterns.empty:
        show_empty("در آخرین جلسه داده‌شده الگوی فعالی پیدا نشد. بعد از دریافت داده جدید این صفحه دوباره محاسبه می‌شود.")
    else:
        accum = patterns[patterns["Type"] == "ACCUMULATION"]
        distrib = patterns[patterns["Type"] == "DISTRIBUTION"]
        c1, c2 = st.columns(2)
        c1.metric("انباشت احتمالی", fa_number(len(accum)))
        c2.metric("توزیع احتمالی", fa_number(len(distrib)))
        for title, rows in [("انباشت حقوقی", accum), ("توزیع حقوقی", distrib)]:
            st.subheader(title)
            if rows.empty:
                st.caption("موردی شناسایی نشده است.")
            else:
                show = rows.rename(columns={
                    "Symbol": "نماد", "Date": "تاریخ", "Streak": "تداوم",
                    "NetLegalVolume": "خالص خرید حقوقی", "NetLegalPctVolume": "نسبت خالص به حجم٪",
                    "PriceChangePct": "تغییر قیمت سه‌روزه٪", "Score": "امتیاز قواعد",
                    "Explanation": "توضیح",
                })
                st.dataframe(show, use_container_width=True, hide_index=True)

    with st.expander("قواعد نسخه فعلی را ببین"):
        st.markdown("""
        **انباشت:** سه جلسه معاملاتی متوالی با خالص خرید حقوقی مثبت؛ نسبت خالص خرید به حجم حداقل ۲٪ در هر جلسه؛ بازده تجمعی سه جلسه بین ۸٪- و ۱٫۵٪+ و میانگین بازده روزانه حداکثر ۰٫۸٪.

        **توزیع:** سه جلسه متوالی با خالص فروش حقوقی؛ نسبت جریان به حجم حداکثر ۲٪- در هر جلسه؛ قیمت پایانی حداقل ۹۶٪ سقف بیشینه ۶۰ جلسه اخیر.

        فقط روزهایی وارد قاعده می‌شوند که داده حقیقی/حقوقی واقعاً در منبع موجود باشد. امتیاز قدرت قواعد است، نه احتمال موفقیت.
        """)


def render_backtest(book: dict[str, pd.DataFrame]) -> None:
    st.title("آزمون تاریخی")
    st.caption("رفتار قیمت بعد از سیگنال‌های گذشته را روی تاریخچه محلی بررسی کن.")
    data = book["DailyData"]
    if data.empty:
        show_empty("ابتدا داده یک‌ساله نمادها را دریافت کن.")
        return

    horizon = st.selectbox("افق بررسی", list(HORIZONS), index=2, format_func=lambda x: f"{x} جلسه معاملاتی بعد")
    results = backtest_patterns(data, horizons=(horizon,))
    if results.empty or results["Samples"].sum() == 0:
        show_empty("در داده فعلی نمونه‌ای از این الگوها برای آزمون تاریخی پیدا نشد.")
        return

    for p_type, label in [("ACCUMULATION", "انباشت"), ("DISTRIBUTION", "توزیع")]:
        st.subheader(f"نتایج الگوی {label}")
        subset = results[results["Type"] == p_type].copy()
        if subset.empty:
            st.caption("نمونه‌ای برای بررسی وجود ندارد.")
            continue
        st.dataframe(subset.rename(columns={
            "Symbol": "نماد", "Samples": "تعداد نمونه",
            "SuccessRatePct": "درصد دفعات موفقیت",
            "AverageReturnPct": "میانگین بازده٪",
            "MedianReturnPct": "میانه بازده٪",
            "BestReturnPct": "بهترین بازده٪",
            "WorstReturnPct": "بدترین بازده٪",
        }), use_container_width=True, hide_index=True)
        valid = subset.dropna(subset=["SuccessRatePct"])
        if not valid.empty:
            fig = px.bar(valid.sort_values("SuccessRatePct"), x="SuccessRatePct", y="Symbol",
                         orientation="h", title=f"درصد موفقیت تاریخی الگوی {label}",
                         labels={"SuccessRatePct": "درصد موفقیت", "Symbol": "نماد"})
            fig.update_layout(template="plotly_dark", height=max(300, 32 * len(valid)),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

    st.warning(
        "این نتیجه، آزمون مقدماتی است. قیمت‌های تعدیل‌نشده، توقف نماد، تغییر سرمایه، دامنه نوسان، "
        "کارمزد، نقدشوندگی و سوگیری بقا می‌توانند نتیجه را منحرف کنند. درصد موفقیت گذشته پیش‌بینی آینده نیست."
    )


def render_data_settings(book: dict[str, pd.DataFrame]) -> None:
    st.title("داده‌ها و تنظیمات")
    st.subheader("فایل اصلی اطلاعات")
    st.code(str(WORKBOOK_PATH), language="text")
    st.caption("این فایل روی همین لپ‌تاپ ذخیره می‌شود. هنگام به‌روزرسانی آن را در Excel باز نگذار.")
    if WORKBOOK_PATH.exists():
        st.download_button(
            "دانلود نسخه پشتیبان Excel",
            data=WORKBOOK_PATH.read_bytes(),
            file_name="SmartMoneyData_backup.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    uploaded = st.file_uploader("بازیابی یا ادغام نسخه پشتیبان Excel", type=["xlsx"])
    if uploaded is not None and st.button("ادغام فایل انتخاب‌شده با داده‌های فعلی"):
        try:
            merge_uploaded_workbook(uploaded.getvalue())
            st.success("اطلاعات فایل پشتیبان ادغام شد.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("به‌روزرسانی خودکار")
    st.write("زمان پیش‌فرض دریافت روزانه پس از پایان بازار، ساعت ۱۸:۳۰ به وقت تهران است.")
    current_hour = st.number_input("ساعت (تهران)", min_value=0, max_value=23, value=18, step=1)
    current_minute = st.number_input("دقیقه", min_value=0, max_value=59, value=30, step=5)
    if st.button("ذخیره ساعت به‌روزرسانی"):
        update_schedule(int(current_hour), int(current_minute))
        st.success("زمان‌بندی برای اجرای بعدی برنامه به‌روزرسانی شد.")
    next_run = next_run_time()
    st.caption("اجرای بعدی: " + (str(next_run) if next_run else "زمان‌بندی فعال نیست"))

    st.divider()
    st.subheader("گزارش دریافت داده")
    logs = book["SyncLog"].sort_values("StartedAt", ascending=False) if not book["SyncLog"].empty else book["SyncLog"]
    if logs.empty:
        show_empty("هنوز عملیات همگام‌سازی انجام نشده است.")
    else:
        st.dataframe(logs.rename(columns={
            "StartedAt": "شروع", "FinishedAt": "پایان", "Trigger": "نوع اجرا",
            "Status": "وضعیت", "SymbolsProcessed": "نماد پردازش‌شده",
            "RecordsUpserted": "ردیف دریافت/به‌روزرسانی", "Message": "پیام",
        }), use_container_width=True, hide_index=True)


def main() -> None:
    try:
        settings = load_settings()\n        start_scheduler(hour=int(settings["auto_sync_hour"]), minute=int(settings["auto_sync_minute"]))
    except Exception as exc:
        st.sidebar.warning(f"زمان‌بندی خودکار فعال نشد: {exc}")

    st.sidebar.markdown("## 📊 Smart Money IR")
    st.sidebar.caption("نسخه شخصی · Python + Excel + Plotly")
    page = st.sidebar.radio(
        "بخش‌ها",
        ["نمای کلی", "نمادها و پرتفوی", "اسکنر رفتار حقوقی", "تحلیل نماد", "الگوهای پول هوشمند", "آزمون تاریخی", "داده‌ها و تنظیمات"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.markdown("**ذخیره‌سازی**")
    st.sidebar.caption("محلی روی لپ‌تاپ · فایل Excel")
    st.sidebar.markdown("**به‌روزرسانی**")
    st.sidebar.caption("دستی + خودکار (شنبه تا پنجشنبه)")
    if st.sidebar.button("همگام‌سازی دستی", type="primary", use_container_width=True):
        try:
            with st.spinner("دریافت داده از TSETMC..."):
                result = sync_all("MANUAL")
            if result["status"] == "SUCCESS":
                st.sidebar.success(f"{result['symbols_processed']} نماد، {result['records_upserted']} رکورد")
            elif result["status"] == "EMPTY":
                st.sidebar.info("ابتدا نماد اضافه کن.")
            else:
                st.sidebar.warning("همگام‌سازی کامل نبود؛ گزارش را ببین.")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(str(exc))
    st.sidebar.caption("آخرین اجرای ذخیره‌شده: " + (
        date_text(load_book()["SyncLog"]["FinishedAt"].dropna().max())
        if not load_book()["SyncLog"].empty and load_book()["SyncLog"]["FinishedAt"].notna().any()
        else "—"
    ))

    book = get_book()
    if page == "نمای کلی":
        render_overview(book)
    elif page == "نمادها و پرتفوی":
        render_symbols(book)
    elif page == "اسکنر رفتار حقوقی":
        render_scanner(book)
    elif page == "تحلیل نماد":
        render_analysis(book)
    elif page == "الگوهای پول هوشمند":
        render_patterns(book)
    elif page == "آزمون تاریخی":
        render_backtest(book)
    elif page == "داده‌ها و تنظیمات":
        render_data_settings(book)

    st.divider()
    st.caption("Smart Money IR · ابزار تحلیل شخصی · سیگنال‌ها توصیه خرید یا فروش نیستند.")


if __name__ == "__main__":
    main()
