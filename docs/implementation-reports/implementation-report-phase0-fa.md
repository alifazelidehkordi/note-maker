# گزارش اجرای فاز صفر: Baseline، Freeze و ADR

## دامنه انجام‌شده

فاز صفر برنامه مهاجرت Browser Runtime و Parallel Runtime به‌طور کامل اجرا شد، بدون تغییر Engine یا فعال‌کردن اجرای موازی واقعی.

## تغییرات کد

1. ماژول `scripts/runtime_flags.py` اضافه شد.
2. گزینه‌های زیر به `batch_pdf.py`، `batch_markdown.py` و `pipeline.py` افزوده شدند:

```text
--browser-provider selenium
--parallel-runs 1
```

3. Pipeline این تنظیمات را به Batch زیرمجموعه منتقل می‌کند.
4. `run_batch`های PDF و Markdown نیز برای فراخوانی مستقیم Python همین قرارداد را Validate می‌کنند.
5. درخواست `parallel-runs > 1` با پیام روشن رد می‌شود؛ اجرای موازی جعلی یا ناامن انجام نمی‌شود.
6. Browser Provider ناشناخته در فاز صفر رد می‌شود.
7. تنظیمات Runtime در Batch Summary ثبت می‌شوند.

## مستندات معماری

پنج ADR الزام‌آور در `docs/adr/` ایجاد شد:

- Patchright/Playwright Provider اصلی آینده؛
- Workerهای Process-based؛
- Single-writer Manifest؛
- Dynamic Job Queue؛
- Profile-per-worker.

## Baseline و Freeze

در `docs/baseline/` موارد زیر ثبت شد:

- خروجی کامل 78 تست پیش از تغییر؛
- گزارش Acceptance پیش از تغییر؛
- Help رابط‌های خط فرمان پیش از تغییر؛
- Public API inventory؛
- SHA-256 فایل‌های کلیدی.

## Guardrail اصلی

فاز صفر عمداً Parallel Runtime را پیاده‌سازی نمی‌کند. پذیرش مقدار 2 یا بیشتر بدون Coordinator و Manifest نویسنده یکتا، یک نقص ایمنی محسوب می‌شد؛ بنابراین سیستم Fail-Closed طراحی شد.

## نتیجه تأیید نهایی

- Unit/Integration: **86/86 Pass**
- Browser-free Phase 1 Acceptance: **3/3 Pass**
- Python bytecode compilation: **Pass**
- CLI help snapshot/diff: **ثبت شد**
- Live Browser Smoke Test: **در این محیط اجرا نشد**؛ Engine فعال همچنان Selenium و بدون تغییر است.
