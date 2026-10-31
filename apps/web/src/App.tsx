import { useCallback, useEffect, useState } from "react";

type View = "dashboard" | "portfolio" | "patterns" | "history";
type Signal = {
  insCode: string; symbol: string; type: "ACCUMULATION" | "DISTRIBUTION"; title: string;
  streak: number; netLegalVolume: number; netLegalRatioPct: number; priceChangePct: number;
  score: number; asOf: string; explanation: string;
};
type PortfolioRow = {
  id: string; insCode: string; symbol: string; quantity: number; averageCost: number;
  latestClose: number | null; changePct: number | null; latestDate: string | null; netLegalVolume: number | null;
};
type Dashboard = {
  metrics: { trackedSymbols: number; symbolsWithData: number; accumulationSignals: number;
    distributionSignals: number; historyDays: number; lastSyncAt: string | null; syncStatus: string };
  portfolio: PortfolioRow[]; patterns: Signal[];
};
type SearchResult = { insCode: string; symbol: string; name: string; market: string };
type TestMetric = { samples: number; successRatePct: number | null; averageReturnPct: number | null };
type Backtest = { symbol: string; accumulation: TestMetric; distribution: TestMetric };

const empty: Dashboard = {
  metrics: { trackedSymbols: 0, symbolsWithData: 0, accumulationSignals: 0, distributionSignals: 0, historyDays: 365, lastSyncAt: null, syncStatus: "NOT_STARTED" },
  portfolio: [], patterns: []
};

const API_BASE = import.meta.env.VITE_API_URL ?? "";\n\nasync function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.message ?? "ارتباط با سرور با خطا مواجه شد.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
function n(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}
function date(value: string | null | undefined): string {
  return value ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium" }).format(new Date(value)) : "—";
}
function volume(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  return abs >= 1e9 ? n(value / 1e9, 2) + " میلیارد" : abs >= 1e6 ? n(value / 1e6, 2) + " میلیون" : n(value);
}
function tone(value: number | null | undefined, inverse = false): string {
  if (value === null || value === undefined || value === 0) return "";
  return (value > 0) !== inverse ? "positive" : "negative";
}

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [data, setData] = useState<Dashboard>(empty);
  const [tests, setTests] = useState<Backtest[]>([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await request<Dashboard>("/api/dashboard"));
      setOnline(true);
      setError("");
    } catch (e) {
      setOnline(false);
      setError(e instanceof Error ? e.message : "API در دسترس نیست.");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const sync = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await request<{ symbolsProcessed: number; recordsUpserted: number }>("/api/sync", { method: "POST" });
      setMessage("همگام‌سازی پایان یافت؛ " + n(result.symbolsProcessed) + " نماد و " + n(result.recordsUpserted) + " رکورد بررسی شد.");
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "همگام‌سازی ناموفق بود.");
    } finally { setBusy(false); }
  };

  const search = async () => {
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      const result = await request<SearchResult[]>("/api/symbols/search?q=" + encodeURIComponent(query.trim()));
      setFound(result);
      setMessage(result.length ? "" : "نمادی با این عبارت پیدا نشد.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "جست‌وجو انجام نشد.");
    } finally { setBusy(false); }
  };
  const add = async (item: SearchResult) => {
    try {
      await request("/api/portfolio", {
        method: "POST",
        body: JSON.stringify({ ...item, quantity: 0, averageCost: 0 })
      });
      setFound([]); setQuery("");
      setMessage(item.symbol + " به فهرست پیگیری اضافه شد.");
      await load();
    } catch (e) { setMessage(e instanceof Error ? e.message : "افزودن نماد ناموفق بود."); }
  };
  const remove = async (id: string) => {
    try { await request("/api/portfolio/" + id, { method: "DELETE" }); await load(); }
    catch (e) { setMessage(e instanceof Error ? e.message : "حذف نماد ناموفق بود."); }
  };

  useEffect(() => {
    if (view !== "history") return;
    void request<{ results: Backtest[] }>("/api/analytics/backtest?horizon=4")
      .then((result) => setTests(result.results))
      .catch(() => setTests([]));
  }, [view]);

  const nav: { id: View; title: string; icon: string }[] = [
    { id: "dashboard", title: "نمای کلی", icon: "◫" },
    { id: "portfolio", title: "پرتفوی من", icon: "▤" },
    { id: "patterns", title: "الگوهای پول هوشمند", icon: "⌁" },
    { id: "history", title: "آزمون تاریخی", icon: "▥" }
  ];

  return <div className="app-shell" dir="rtl">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">SM</div><div><strong>Smart Money IR</strong><span>تحلیل رفتار بازار ایران</span></div></div>
      <div className="workspace-label">فضای کاری</div>
      <nav>{nav.map((item) => <button key={item.id} className={"nav-item " + (view === item.id ? "active" : "")} onClick={() => setView(item.id)}><span className="nav-icon">{item.icon}</span>{item.title}</button>)}</nav>
      <div className="sidebar-bottom"><span className={"status-dot " + (online ? "online" : "offline")}></span><span>{online ? "اتصال به سرور برقرار" : "سرور متصل نیست"}</span><small>نسخه آزمایشی ۰.۱</small></div>
    </aside>

    <main className="main-content">
      <header className="topbar">
        <div><div className="eyebrow">MARKET INTELLIGENCE / IRAN</div><h1>{nav.find((item) => item.id === view)?.title}</h1></div>
        <div className="top-actions">
          <span className="date-chip">{new Intl.DateTimeFormat("fa-IR", { dateStyle: "full" }).format(new Date())}</span>
          <button className="button primary" onClick={sync} disabled={busy || !online}>{busy ? "در حال اجرا…" : "↻ همگام‌سازی دستی"}</button>
        </div>
      </header>

      {error && <div className="alert error"><strong>اتصال برقرار نشد</strong><span>{error}</span><button onClick={load}>تلاش مجدد</button></div>}
      {message && <div className="alert info"><span>{message}</span><button onClick={() => setMessage("")}>×</button></div>}
      <section className="source-note"><span className="note-icon">i</span><span>اطلاعات پس از اتصال API از TSETMC دریافت می‌شود. تا پیش از اولین همگام‌سازی، داده ساختگی نمایش داده نمی‌شود.</span><span className="note-period">تاریخچه هدف: ۳۶۵ روز</span></section>

      {loading ? <div className="empty-state">در حال بارگذاری داشبورد…</div> : <>
        {view === "dashboard" && <>
          <section className="metric-grid">
            <Metric label="نمادهای تحت پیگیری" value={n(data.metrics.trackedSymbols)} foot="در پرتفوی و فهرست رصد" />
            <Metric label="نمادهای دارای داده" value={n(data.metrics.symbolsWithData)} foot="دارای تاریخچه ثبت‌شده" />
            <Metric label="الگوی انباشت" value={n(data.metrics.accumulationSignals)} foot="خرید پیوسته حقوقی با قیمت کم‌تحرک" color="positive" />
            <Metric label="الگوی توزیع" value={n(data.metrics.distributionSignals)} foot="فروش پیوسته حقوقی نزدیک سقف اخیر" color="negative" />
          </section>
          <div className="content-grid">
            <section className="panel wide">
              <PanelHeading title="آخرین هشدارهای رفتاری" subtitle="سیگنال‌ها فقط برای نمادهای دارای داده معتبر محاسبه می‌شوند." action="مشاهده همه" onAction={() => setView("patterns")} />
              <PatternTable rows={data.patterns} />
            </section>
            <section className="panel">
              <PanelHeading title="وضعیت داده" subtitle="پوشش تاریخچه و همگام‌سازی" />
              <div className="coverage-number">{n(data.metrics.symbolsWithData)} <small>از</small> {n(data.metrics.trackedSymbols)}</div>
              <div className="progress-track"><div className="progress-fill" style={{ width: (data.metrics.trackedSymbols ? data.metrics.symbolsWithData / data.metrics.trackedSymbols * 100 : 0) + "%" }} /></div>
              <div className="mini-row"><span>بازه هدف</span><strong>۳۶۵ روز</strong></div>
              <div className="mini-row"><span>آخرین دریافت</span><strong>{date(data.metrics.lastSyncAt)}</strong></div>
              <div className="mini-row"><span>وضعیت اجرا</span><strong>{data.metrics.syncStatus === "SUCCESS" ? "موفق" : data.metrics.syncStatus === "PARTIAL" ? "بخشی از نمادها" : data.metrics.syncStatus === "FAILED" ? "ناموفق" : "شروع نشده"}</strong></div>
            </section>
          </div>
          <section className="panel"><PanelHeading title="نمادهای تحت نظر" subtitle="آخرین وضعیت قیمت و خالص خرید حقوقی" action="مدیریت پرتفوی" onAction={() => setView("portfolio")} /><PortfolioTable rows={data.portfolio} onRemove={remove} /></section>
        </>}

        {view === "portfolio" && <section className="panel">
          <PanelHeading title="مدیریت نمادها" subtitle="نماد را جست‌وجو و به فهرست رصد اضافه کن؛ سپس تاریخچه یک‌ساله را همگام‌سازی کن." />
          <div className="search-row">
            <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="جست‌وجوی نماد؛ مثلاً فولاد" />
            <button className="button primary" onClick={search} disabled={busy}>{busy ? "جست‌وجو…" : "جست‌وجو"}</button>
          </div>
          {found.length > 0 && <div className="search-results">{found.map((item) => <div className="search-result" key={item.insCode}>
            <div><strong>{item.symbol}</strong><span>{item.name} · {item.market}</span></div>
            <button className="button subtle" onClick={() => add(item)}>افزودن به فهرست +</button>
          </div>)}</div>}
          <div className="section-separator" />
          <PortfolioTable rows={data.portfolio} onRemove={remove} />
        </section>}

        {view === "patterns" && <>
          <div className="intro-block"><h2>ردپای پول هوشمند</h2><p>الگوها با سه جلسه متوالی محاسبه می‌شوند. امتیاز، قدرت قواعد را نشان می‌دهد و احتمال رشد یا افت نیست.</p></div>
          <section className="panel"><PanelHeading title="الگوهای فعال" subtitle="خالص جریان حقوقی باید نسبت معناداری از حجم روز باشد." /><PatternTable rows={data.patterns} /></section>
          <div className="method-grid">
            <Method type="accumulation" title="انباشت حقوقی" description="خالص خرید حقوقی در سه روز مثبت، نسبت خالص خرید به حجم حداقل ۲٪ در هر روز و بازده میانگین روزانه محدود." />
            <Method type="distribution" title="توزیع حقوقی" description="خالص فروش حقوقی در سه روز متوالی، حداقل ۲٪ از حجم روز و قیمت در محدوده ۴٪ سقف ۶۰ جلسه اخیر." />
          </div>
        </>}

        {view === "history" && <section className="panel">
          <PanelHeading title="آزمون تاریخی الگوها" subtitle="بازده چهار جلسه معاملاتی پس از سیگنال، روی داده‌های ذخیره‌شده محاسبه می‌شود." />
          <div className="backtest-note">این آزمون نسخه اولیه است؛ برای قضاوت معتبر به نمونه کافی و کنترل توقف نماد، تعدیلات قیمت و سوگیری بقا نیاز داریم.</div>
          <div className="table-wrap"><table><thead><tr><th>نماد</th><th>نمونه انباشت</th><th>موفقیت انباشت</th><th>میانگین بازده</th><th>نمونه توزیع</th><th>موفقیت توزیع</th><th>میانگین بازده</th></tr></thead>
            <tbody>{tests.map((row) => <tr key={row.symbol}>
              <td className="symbol">{row.symbol}</td><td>{n(row.accumulation.samples)}</td>
              <td>{row.accumulation.successRatePct === null ? "—" : n(row.accumulation.successRatePct, 1) + "٪"}</td>
              <td className={tone(row.accumulation.averageReturnPct)}>{row.accumulation.averageReturnPct === null ? "—" : n(row.accumulation.averageReturnPct, 2) + "٪"}</td>
              <td>{n(row.distribution.samples)}</td>
              <td>{row.distribution.successRatePct === null ? "—" : n(row.distribution.successRatePct, 1) + "٪"}</td>
              <td className={tone(row.distribution.averageReturnPct, true)}>{row.distribution.averageReturnPct === null ? "—" : n(row.distribution.averageReturnPct, 2) + "٪"}</td>
            </tr>)}</tbody></table></div>
          {!tests.length && <div className="empty-inline">برای نمایش آزمون تاریخی، ابتدا نماد اضافه و تاریخچه آن را دریافت کن.</div>}
        </section>}
      </>}

      <footer className="footer"><span>Smart Money IR · نسخه اولیه</span><span>تحلیل داده، نه توصیه سرمایه‌گذاری</span></footer>
    </main>
  </div>;
}

function Metric({ label, value, foot, color }: { label: string; value: string; foot: string; color?: string }) {
  return <div className="metric-card"><span className="metric-label">{label}</span><strong className={color ?? ""}>{value}</strong><small>{foot}</small></div>;
}
function PanelHeading({ title, subtitle, action, onAction }: { title: string; subtitle: string; action?: string; onAction?: () => void }) {
  return <div className="panel-heading"><div><h2>{title}</h2><p>{subtitle}</p></div>{action && onAction && <button className="text-button" onClick={onAction}>{action} ←</button>}</div>;
}
function PatternTable({ rows }: { rows: Signal[] }) {
  if (!rows.length) return <div className="empty-inline">فعلاً الگویی برای نمایش وجود ندارد. نماد اضافه کن و تاریخچه را همگام‌سازی کن.</div>;
  return <div className="table-wrap"><table><thead><tr><th>نماد</th><th>نوع الگو</th><th>تداوم</th><th>خالص خرید حقوقی</th><th>نسبت به حجم</th><th>تغییر قیمت</th><th>قدرت قواعد</th><th>تاریخ</th></tr></thead><tbody>{rows.map((item) => <tr key={item.insCode}>
    <td className="symbol">{item.symbol}</td><td><span className={"pill " + (item.type === "ACCUMULATION" ? "green" : "red")}>{item.type === "ACCUMULATION" ? "انباشت" : "توزیع"}</span></td>
    <td>{n(item.streak)} روز</td><td className={tone(item.netLegalVolume)}>{volume(item.netLegalVolume)}</td><td className={tone(item.netLegalRatioPct)}>{n(item.netLegalRatioPct, 1)}٪</td>
    <td className={tone(item.priceChangePct)}>{n(item.priceChangePct, 2)}٪</td><td><div className="score"><div><span style={{ width: item.score + "%" }} /></div><strong>{n(item.score)}</strong></div></td><td>{date(item.asOf)}</td>
  </tr>)}</tbody></table></div>;
}
function PortfolioTable({ rows, onRemove }: { rows: PortfolioRow[]; onRemove: (id: string) => void }) {
  if (!rows.length) return <div className="empty-inline">هنوز نمادی اضافه نشده است. از بخش مدیریت نمادها شروع کن.</div>;
  return <div className="table-wrap"><table><thead><tr><th>نماد</th><th>آخرین قیمت پایانی</th><th>تغییر روزانه</th><th>خالص خرید حقوقی</th><th>آخرین داده</th><th></th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}>
    <td className="symbol">{row.symbol}</td><td>{row.latestClose === null ? "داده موجود نیست" : n(row.latestClose)}</td>
    <td className={tone(row.changePct)}>{row.changePct === null ? "—" : n(row.changePct, 2) + "٪"}</td>
    <td className={tone(row.netLegalVolume)}>{volume(row.netLegalVolume)}</td><td>{date(row.latestDate)}</td><td><button className="remove-button" onClick={() => onRemove(row.id)}>حذف</button></td>
  </tr>)}</tbody></table></div>;
}
function Method({ type, title, description }: { type: "accumulation" | "distribution"; title: string; description: string }) {
  return <div className={"method-card " + type}><span className="method-tag">{type.toUpperCase()}</span><h3>{title}</h3><p>{description}</p></div>;
}
