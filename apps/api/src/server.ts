import dotenv from "dotenv";
dotenv.config({ path: "../../.env" });
import Fastify from "fastify";
import cors from "@fastify/cors";
import cron from "node-cron";
import { Prisma, PrismaClient, type SyncTrigger } from "@prisma/client";
import { z } from "zod";

const env = z.object({
  PORT: z.coerce.number().int().positive().default(3001),
  CORS_ORIGIN: z.string().default("http://localhost:5173"),
  DATABASE_URL: z.string().min(1),
  TSETMC_BASE_URL: z.string().url().default("https://cdn.tsetmc.com/api"),
  TSETMC_USER_AGENT: z.string().default("Mozilla/5.0 (compatible; SmartMoneyIR/0.1)"),
  TSETMC_REQUEST_DELAY_MS: z.coerce.number().int().min(0).default(1200),
  AUTO_SYNC_CRON: z.string().default("30 18 * * 0-4,6"),
  AUTO_SYNC_TIMEZONE: z.string().default("Asia/Tehran")
}).parse(process.env);

const app = Fastify({ logger: true });
const prisma = new PrismaClient();
await app.register(cors, { origin: env.CORS_ORIGIN.split(",").map((item) => item.trim()) });

type Raw = Record<string, unknown>;
type InstrumentResult = { insCode: string; symbol: string; name: string; market: string };
type DailyRow = {
  insCode: string; date: Date; closePrice: number | null; previousClose: number | null;
  openPrice: number | null; highPrice: number | null; lowPrice: number | null;
  totalVolume: number; totalTrades: number; legalBuyVolume: number; legalSellVolume: number;
  legalBuyValue: number; legalSellValue: number; legalBuyCount: number; legalSellCount: number;
  retailBuyVolume: number; retailSellVolume: number; retailBuyValue: number; retailSellValue: number;
  retailBuyCount: number; retailSellCount: number; source: string; fetchedAt: Date;
};
type MarketDay = Pick<DailyRow, "insCode" | "date" | "closePrice" | "previousClose" | "highPrice" | "totalVolume" | "legalBuyVolume" | "legalSellVolume">;

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}
function optNum(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function readDate(row: Raw): Date | null {
  const raw = row.dEven ?? row.deven ?? row.date ?? row.Date;
  const digits = String(raw ?? "").replace(/[^0-9]/g, "");
  if (digits.length === 8) {
    const date = new Date(Date.UTC(Number(digits.slice(0, 4)), Number(digits.slice(4, 6)) - 1, Number(digits.slice(6, 8))));
    return Number.isNaN(date.getTime()) ? null : date;
  }
  if (raw) {
    const date = new Date(String(raw));
    return Number.isNaN(date.getTime()) ? null : date;
  }
  return null;
}
async function getJson(path: string): Promise<Raw> {
  const url = env.TSETMC_BASE_URL.replace(/\/$/, "") + path;
  const response = await fetch(url, {
    headers: { "User-Agent": env.TSETMC_USER_AGENT, Accept: "application/json" },
    signal: AbortSignal.timeout(20000)
  });
  if (!response.ok) throw new Error("TSETMC پاسخ " + response.status + " برگرداند.");
  let payload: unknown;
  try { payload = JSON.parse(await response.text()); }
  catch { throw new Error("پاسخ TSETMC JSON نیست؛ احتمال محدودیت دسترسی IP وجود دارد."); }
  if (!payload || typeof payload !== "object") throw new Error("ساختار پاسخ TSETMC نامعتبر است.");
  return payload as Raw;
}
function unwrap(payload: Raw, key: string): unknown { return payload[key] ?? payload; }

async function searchTsetmc(query: string): Promise<InstrumentResult[]> {
  const payload = await getJson("/Instrument/GetInstrumentSearch/" + encodeURIComponent(query));
  const items = unwrap(payload, "instrumentSearch");
  if (!Array.isArray(items)) return [];
  return (items as Raw[]).map((row) => ({
    insCode: String(row.insCode ?? ""),
    symbol: String(row.lVal18AFC ?? row.symbol ?? ""),
    name: String(row.lVal30 ?? row.name ?? ""),
    market: String(row.flowTitle ?? "")
  })).filter((item) => item.insCode && item.symbol);
}

async function fetchOneYear(insCode: string): Promise<DailyRow[]> {
  const [pricePayload, clientPayload] = await Promise.all([
    getJson("/ClosingPrice/GetClosingPriceDailyList/" + encodeURIComponent(insCode) + "/0"),
    getJson("/ClientType/GetClientTypeHistory/" + encodeURIComponent(insCode))
  ]);
  const priceData = unwrap(pricePayload, "closingPriceDaily");
  const clientData = unwrap(clientPayload, "clientType");
  const prices = Array.isArray(priceData) ? priceData as Raw[] : [];
  const clients = Array.isArray(clientData) ? clientData as Raw[] : [];
  const clientsByDate = new Map<string, Raw>();

  for (const row of clients) {
    const date = readDate(row);
    if (date) clientsByDate.set(date.toISOString().slice(0, 10), row);
  }

  const cutoff = Date.now() - 365 * 86400000;
  const fetchedAt = new Date();
  const rows: DailyRow[] = [];

  for (const price of prices) {
    const date = readDate(price);
    if (!date || date.getTime() < cutoff) continue;
    const client = clientsByDate.get(date.toISOString().slice(0, 10)) ?? {};
    rows.push({
      insCode, date,
      closePrice: optNum(price.pClosing ?? price.pc ?? price.pDrCotVal),
      previousClose: optNum(price.priceYesterday ?? price.py),
      openPrice: optNum(price.priceFirst ?? price.pf),
      highPrice: optNum(price.priceMax ?? price.pmax),
      lowPrice: optNum(price.priceMin ?? price.pmin),
      totalVolume: num(price.qTotTran5J ?? price.tvol ?? price.qTotTran),
      totalTrades: num(price.zTotTran ?? price.tno),
      legalBuyVolume: num(client.buy_N_Volume), legalSellVolume: num(client.sell_N_Volume),
      legalBuyValue: num(client.buy_N_Value), legalSellValue: num(client.sell_N_Value),
      legalBuyCount: num(client.buy_N_Count), legalSellCount: num(client.sell_N_Count),
      retailBuyVolume: num(client.buy_I_Volume), retailSellVolume: num(client.sell_I_Volume),
      retailBuyValue: num(client.buy_I_Value), retailSellValue: num(client.sell_I_Value),
      retailBuyCount: num(client.buy_I_Count), retailSellCount: num(client.sell_I_Count),
      source: "tsetmc-cdn", fetchedAt
    });
  }
  if (!rows.length) throw new Error("برای این نماد در بازه یک‌ساله داده قیمت قابل استفاده دریافت نشد.");
  return rows.sort((a, b) => a.date.getTime() - b.date.getTime());
}

function net(day: MarketDay): number { return day.legalBuyVolume - day.legalSellVolume; }
function dailyReturn(day: MarketDay): number {
  if (!day.closePrice || !day.previousClose) return 0;
  return (day.closePrice / day.previousClose - 1) * 100;
}
function isPattern(days: MarketDay[], end: number, type: "ACCUMULATION" | "DISTRIBUTION"): boolean {
  if (end < 2) return false;
  const window = days.slice(end - 2, end + 1);
  if (window.some((day) => !day.closePrice || day.totalVolume <= 0)) return false;
  const ratios = window.map((day) => net(day) / day.totalVolume);
  const avgReturn = window.map(dailyReturn).reduce((sum, value) => sum + value, 0) / 3;

  if (type === "ACCUMULATION") {
    return window.every((day) => net(day) > 0)
      && ratios.every((value) => value >= 0.02)
      && avgReturn >= -4.5 && avgReturn <= 0.6;
  }
  const recent = days.slice(Math.max(0, end - 60), end + 1);
  const high = Math.max(...recent.map((day) => day.highPrice ?? day.closePrice ?? 0));
  return window.every((day) => net(day) < 0)
    && ratios.every((value) => value <= -0.02)
    && high > 0 && (days[end].closePrice ?? 0) >= high * 0.96
    && avgReturn <= 0.8;
}
function detectPattern(history: MarketDay[]) {
  const days = [...history].sort((a, b) => a.date.getTime() - b.date.getTime());
  if (days.length < 3) return null;
  const end = days.length - 1;
  const type = isPattern(days, end, "ACCUMULATION") ? "ACCUMULATION"
    : isPattern(days, end, "DISTRIBUTION") ? "DISTRIBUTION" : null;
  if (!type) return null;
  const window = days.slice(-3);
  const netVolume = window.reduce((sum, day) => sum + net(day), 0);
  const volume = window.reduce((sum, day) => sum + day.totalVolume, 0);
  const firstPrice = window[0].previousClose ?? window[0].closePrice ?? 0;
  const lastPrice = days[end].closePrice ?? firstPrice;
  const priceChangePct = firstPrice > 0 ? (lastPrice / firstPrice - 1) * 100 : 0;
  const netLegalRatioPct = volume > 0 ? netVolume / volume * 100 : 0;
  const score = Math.round(Math.min(100, 75 + Math.min(25, Math.abs(netLegalRatioPct) * 1.5)));
  return {
    insCode: days[end].insCode, type,
    title: type === "ACCUMULATION" ? "احتمال انباشت حقوقی" : "احتمال توزیع حقوقی",
    streak: 3, netLegalVolume: netVolume, netLegalRatioPct, priceChangePct,
    score, asOf: days[end].date,
    explanation: type === "ACCUMULATION"
      ? "خالص خرید حقوقی در سه جلسه متوالی مثبت بوده و قیمت رشد محدودی داشته است."
      : "خالص فروش حقوقی در سه جلسه متوالی منفی بوده و قیمت نزدیک سقف اخیر قرار دارد."
  };
}
function backtest(history: MarketDay[], type: "ACCUMULATION" | "DISTRIBUTION", horizon: number) {
  const days = [...history].sort((a, b) => a.date.getTime() - b.date.getTime());
  const returns: number[] = [];
  let lastSignal = -10;
  for (let i = 2; i < days.length - horizon; i += 1) {
    if (i - lastSignal < 3 || !isPattern(days, i, type)) continue;
    const entry = days[i].closePrice;
    const exit = days[i + horizon].closePrice;
    if (!entry || !exit) continue;
    returns.push((exit / entry - 1) * 100);
    lastSignal = i;
  }
  const sorted = [...returns].sort((a, b) => a - b);
  const average = returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : null;
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length ? sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2 : null;
  const wins = returns.filter((value) => type === "ACCUMULATION" ? value > 0 : value < 0).length;
  return { samples: returns.length, successRatePct: returns.length ? wins / returns.length * 100 : null, averageReturnPct: average, medianReturnPct: median, horizon };
}

let syncRunning = false;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function syncPortfolio(trigger: SyncTrigger) {
  if (syncRunning) throw new Error("همگام‌سازی دیگری در حال اجراست.");
  syncRunning = true;
  const run = await prisma.syncRun.create({ data: { trigger, status: "RUNNING" } });
  let symbolsProcessed = 0;
  let recordsUpserted = 0;
  const errors: string[] = [];

  try {
    const items = await prisma.portfolioItem.findMany({ orderBy: { symbol: "asc" } });
    for (const item of items) {
      try {
        const history = await fetchOneYear(item.insCode);
        await prisma.instrument.upsert({
          where: { insCode: item.insCode },
          create: { insCode: item.insCode, symbol: item.symbol },
          update: { symbol: item.symbol }
        });
        for (const row of history) {
          await prisma.dailyMarketData.upsert({
            where: { insCode_date: { insCode: row.insCode, date: row.date } },
            create: row,
            update: { ...row, fetchedAt: new Date() }
          });
        }
        symbolsProcessed += 1;
        recordsUpserted += history.length;
      } catch (error) {
        errors.push(item.symbol + ": " + (error instanceof Error ? error.message : "خطای نامشخص"));
      }
      await delay(env.TSETMC_REQUEST_DELAY_MS);
    }
    const status = errors.length === 0 ? "SUCCESS" : symbolsProcessed > 0 ? "PARTIAL" : "FAILED";
    await prisma.syncRun.update({
      where: { id: run.id },
      data: { status, finishedAt: new Date(), symbolsProcessed, recordsUpserted,
        message: errors.length ? errors.join(" | ").slice(0, 1800) : "همگام‌سازی با موفقیت انجام شد." }
    });
    return { id: run.id, status, symbolsProcessed, recordsUpserted, errors };
  } catch (error) {
    await prisma.syncRun.update({
      where: { id: run.id },
      data: { status: "FAILED", finishedAt: new Date(), symbolsProcessed, recordsUpserted,
        message: error instanceof Error ? error.message : "خطای نامشخص" }
    });
    throw error;
  } finally {
    syncRunning = false;
  }
}

app.get("/health", async () => {
  await prisma.$queryRaw(Prisma.sql`SELECT 1`);
  return { status: "ok", database: "connected", syncRunning };
});
app.get("/api/symbols/search", async (request, reply) => {
  const query = (request.query as { q?: string }).q?.trim() ?? "";
  if (query.length < 2) return [];
  try { return await searchTsetmc(query); }
  catch (error) {
    reply.code(502);
    return { message: error instanceof Error ? error.message : "خطا در جست‌وجوی نماد" };
  }
});
app.get("/api/portfolio", async () => prisma.portfolioItem.findMany({ orderBy: { symbol: "asc" } }));
app.post("/api/portfolio", async (request, reply) => {
  const schema = z.object({
    insCode: z.string().min(5), symbol: z.string().min(1), name: z.string().optional(),
    market: z.string().optional(), quantity: z.number().nonnegative().default(0),
    averageCost: z.number().nonnegative().default(0)
  });
  const parsed = schema.safeParse(request.body);
  if (!parsed.success) return reply.code(400).send({ message: "اطلاعات نماد معتبر نیست." });
  const value = parsed.data;
  await prisma.instrument.upsert({
    where: { insCode: value.insCode },
    create: { insCode: value.insCode, symbol: value.symbol, name: value.name, market: value.market },
    update: { symbol: value.symbol, name: value.name, market: value.market }
  });
  return reply.code(201).send(await prisma.portfolioItem.upsert({
    where: { insCode: value.insCode },
    create: { insCode: value.insCode, symbol: value.symbol, quantity: value.quantity, averageCost: value.averageCost },
    update: { symbol: value.symbol, quantity: value.quantity, averageCost: value.averageCost }
  }));
});
app.delete("/api/portfolio/:id", async (request, reply) => {
  const { id } = request.params as { id: string };
  await prisma.portfolioItem.delete({ where: { id } });
  return reply.code(204).send();
});
app.post("/api/sync", async (request, reply) => {
  if (syncRunning) return reply.code(409).send({ message: "همگام‌سازی دیگری در حال اجراست." });
  try { return await syncPortfolio("MANUAL"); }
  catch (error) { return reply.code(502).send({ message: error instanceof Error ? error.message : "خطا در همگام‌سازی" }); }
});

async function loadHistory() {
  const cutoff = new Date(Date.now() - 365 * 86400000);
  const portfolio = await prisma.portfolioItem.findMany();
  const codes = portfolio.map((item) => item.insCode);
  if (!codes.length) return { portfolio, records: [] as MarketDay[] };
  const records = await prisma.dailyMarketData.findMany({
    where: { insCode: { in: codes }, date: { gte: cutoff } },
    orderBy: { date: "asc" }
  });
  return { portfolio, records: records as MarketDay[] };
}
app.get("/api/dashboard", async () => {
  const { portfolio, records } = await loadHistory();
  const grouped = new Map<string, MarketDay[]>();
  for (const row of records) {
    const list = grouped.get(row.insCode) ?? [];
    list.push(row);
    grouped.set(row.insCode, list);
  }
  const portfolioRows = portfolio.map((item) => {
    const history = grouped.get(item.insCode) ?? [];
    const latest = history[history.length - 1];
    const previous = history[history.length - 2];
    return {
      ...item, latestClose: latest?.closePrice ?? null,
      changePct: latest?.closePrice && previous?.closePrice ? (latest.closePrice / previous.closePrice - 1) * 100 : null,
      latestDate: latest?.date ?? null,
      netLegalVolume: latest ? latest.legalBuyVolume - latest.legalSellVolume : null
    };
  });
  const patterns = portfolioRows.flatMap((item) => {
    const signal = detectPattern(grouped.get(item.insCode) ?? []);
    return signal ? [{ ...signal, symbol: item.symbol }] : [];
  });
  const latestSync = await prisma.syncRun.findFirst({ orderBy: { startedAt: "desc" } });
  return {
    metrics: {
      trackedSymbols: portfolio.length,
      symbolsWithData: portfolioRows.filter((item) => item.latestClose !== null).length,
      accumulationSignals: patterns.filter((item) => item.type === "ACCUMULATION").length,
      distributionSignals: patterns.filter((item) => item.type === "DISTRIBUTION").length,
      historyDays: 365, lastSyncAt: latestSync?.finishedAt ?? null,
      syncStatus: latestSync?.status ?? "NOT_STARTED"
    },
    portfolio: portfolioRows, patterns, recentSync: latestSync
  };
});
app.get("/api/analytics/backtest", async (request) => {
  const query = request.query as { horizon?: string };
  const horizon = Math.min(10, Math.max(1, Number(query.horizon ?? 4)));
  const { portfolio, records } = await loadHistory();
  return {
    horizon,
    results: portfolio.map((item) => {
      const history = records.filter((row) => row.insCode === item.insCode);
      return {
        symbol: item.symbol,
        accumulation: backtest(history, "ACCUMULATION", horizon),
        distribution: backtest(history, "DISTRIBUTION", horizon)
      };
    })
  };
});
app.get("/api/sync/history", async () => prisma.syncRun.findMany({ orderBy: { startedAt: "desc" }, take: 20 }));

const address = await app.listen({ port: env.PORT, host: "0.0.0.0" });
app.log.info("Smart Money IR API listening at " + address);
cron.schedule(env.AUTO_SYNC_CRON, async () => {
  if (syncRunning) return;
  try { await syncPortfolio("SCHEDULED"); }
  catch (error) { app.log.error(error); }
}, { timezone: env.AUTO_SYNC_TIMEZONE });

const shutdown = async () => {
  await app.close();
  await prisma.$disconnect();
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
