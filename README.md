# Smart Money IR — MVP

داشبورد وب فارسی تحلیل رفتار حقیقی و حقوقی بورس ایران.

## انتخاب‌های پروژه
- محیط: Web
- تاریخچه هدف: ۳۶۵ روز برای نمادهای تحت پیگیری
- به‌روزرسانی: دستی + خودکار روزانه
- انتشار رابط وب: GitHub Pages

## اجرای محلی
نیازمند Node.js 20+، npm 10+ و Docker:
```bash
cp .env.example .env
npm install
docker compose up -d db
npm run db:push
npm run dev
```
رابط کاربری: http://localhost:5173
API: http://localhost:3001/health

برای build محلی: `npm run build`

## انتشار لینک عمومی
مخزن باید Public باشد. در GitHub به Settings → Pages بروید و Source را روی GitHub Actions بگذارید. با push به main، workflow رابط وب را deploy می‌کند.
آدرس نهایی پروژه:
https://bezad081.github.io/Smart-Money-IR-MVP/

## معماری
- apps/web: React + TypeScript + Vite
- apps/api: Fastify + TypeScript
- Database: PostgreSQL + Prisma
- Scheduler: node-cron
- Data provider: مسیرهای شناخته‌شده TSETMC

## مهم: GitHub Pages فقط Frontend را میزبانی می‌کند
GitHub Pages سرویس استاتیک است و Node API یا PostgreSQL را اجرا نمی‌کند. برای داشبورد زنده، API و دیتابیس باید جداگانه روی VPS یا سرویس backend میزبانی شوند. مقدار `VITE_API_URL` را در Settings → Secrets and variables → Actions → Variables به‌عنوان Repository variable بسازید و URL عمومی API را در آن قرار دهید. در تنظیمات backend نیز `CORS_ORIGIN` باید شامل `https://bezad081.github.io` باشد. تا قبل از استقرار backend، صفحه وب منتشر می‌شود ولی داده‌های زنده در دسترس نیستند.

## داده و اعتبار
آداپتر اولیه از مسیرهای CDN مربوط به TSETMC استفاده می‌کند:
- `/Instrument/GetInstrumentSearch/{query}`
- `/ClosingPrice/GetClosingPriceDailyList/{insCode}/0`
- `/ClientType/GetClientTypeHistory/{insCode}`

این مسیرها غیررسمی و وابسته به ساختار فعلی سرویس هستند و ممکن است تغییر کنند یا از بعضی IPها در دسترس نباشند. تطبیق نام فیلدها و کامل‌بودن تاریخچه باید روی سرور نهایی و چند نماد واقعی آزمایش شود. در نسخه فعلی هیچ داده ساختگی به‌عنوان داده بازار نمایش داده نمی‌شود.

## تحلیل
- خالص خرید حقوقی = حجم خرید حقوقی − حجم فروش حقوقی
- نسبت خالص خرید به حجم کل = خالص خرید حقوقی ÷ حجم معاملات × ۱۰۰
- انباشت: سه جلسه خالص خرید حقوقی پیوسته مثبت، نسبت جریان به حجم ≥۲٪ و رشد قیمت محدود
- توزیع: سه جلسه خالص فروش حقوقی پیوسته و قیمت در محدوده ۴٪ سقف ۶۰ جلسه اخیر

امتیاز الگو امتیاز قواعد است، نه احتمال آماری. آزمون تاریخی فعلی مقدماتی است و به کنترل توقف، تعدیلات قیمت، کارمزد و سوگیری بقا نیاز دارد. داده تجمیعی حقوقی هویت حقوقی‌های منفرد را نشان نمی‌دهد. این پروژه توصیه سرمایه‌گذاری نیست.

## امنیت
این MVP فعلاً احراز هویت ندارد. API را بدون HTTPS و لایه احراز هویت/Access Proxy در اینترنت عمومی قرار ندهید. قبل از استفاده چندکاربره، احراز هویت، نقش‌ها، rate limit و audit log اضافه شود.
