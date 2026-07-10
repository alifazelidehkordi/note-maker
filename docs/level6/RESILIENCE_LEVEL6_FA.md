# معماری Resilience در Level 6

این سند خلاصه قراردادهای فنی لایه پایداری اجرای موازی Note Maker در نسخه `0.8.0` است.

## مرز مالکیت

```text
Worker Process ── typed event ──▶ Coordinator ──▶ GlobalRuntimeController
      │                                  │
      ├─ RetryTracker محلی               ├─ Global Cooldown
      ├─ Browser Session                 ├─ Auth / Rate Circuits
      └─ بدون دسترسی نوشتن Manifest      ├─ Adaptive Dispatch Limit
                                         └─ Single-writer Manifest
```

- Worker فقط Retry محلی و اجرای Job را مدیریت می‌کند.
- Coordinator تنها مالک وضعیت سراسری Rate Limit، Circuit، Dispatch و Manifest است.
- یک Worker نمی‌تواند مستقیماً تعداد Worker فعال یا وضعیت Run را تغییر دهد؛ فقط Event نوع‌دار می‌فرستد.

## بودجه‌های Retry

| دسته | پیش‌فرض | رفتار |
|---|---:|---|
| Content attempt | 3 attempt | خطای پاسخ/محتوا؛ تعداد کل Attempt است |
| Network | 4 retry | Backoff نمایی 3، 6، 12، 24 ثانیه پیش از Jitter |
| Browser | 3 retry | خطای Startup/Crash/Profile |
| Download | 2 retry | خطای دریافت Artifact |
| Rate limit | 2 retry | `retry_after` Provider اولویت دارد |
| Authentication | 0 | بدون Retry محلی؛ ارتقا به Circuit سراسری |

Jitter به‌صورت Deterministic از شناسه Job، دسته و شماره Retry ساخته می‌شود تا تست‌پذیر باشد و Workerها هم‌زمان بیدار نشوند.

## Cooldown و Circuit Breaker

- هر Rate-limit Event، زمان توقف تخصیص Job جدید را حداقل تا `global_rate_limit_cooldown` جلو می‌برد.
- Jobهای در حال اجرا به‌صورت پیش‌فرض قطع نمی‌شوند.
- Startup ابتدا یک Worker را تا `READY` عبور می‌دهد؛ در صورت Auth Failure، Workerهای دیگر ساخته نمی‌شوند.
- Auth Circuit و Severe Rate Circuit پس از عبور از Threshold، Dispatch جدید را متوقف می‌کنند.
- نتیجه‌های تکمیل‌شده حفظ و Jobهای ناتمام Resumeable باقی می‌مانند.

## Adaptive Concurrency

این قابلیت پیش‌فرض خاموش است. پس از فعال‌سازی:

1. Eventهای Rate Limit در Window مشاهده می‌شوند؛
2. پس از Threshold، `active_limit` یک واحد کاهش می‌یابد؛
3. Process سالم کشته نمی‌شود و فقط Dispatch Slot کاهش می‌یابد؛
4. پس از Quiet Period، ظرفیت یک واحد افزایش می‌یابد؛
5. ظرفیت هرگز از `parallel-runs` بیشتر یا از یک کمتر نمی‌شود.

## Worker Recycling

Worker بعد از `worker_max_jobs` یا عبور RSS کل Process Tree از `worker_memory_limit_mb` Recycle می‌شود. Recycle فقط پس از پایان Job انجام می‌شود و Worker جایگزین Profile نسل جدید می‌گیرد:

```text
worker-001 → worker-001-g002 → worker-001-g003
```

## Process Hygiene و Claim

- پیش از توقف Worker، PID فرزندان شناخته‌شده ثبت می‌شود.
- پس از خروج Parent، Childهای باقی‌مانده ابتدا `SIGTERM` و سپس در صورت نیاز `SIGKILL` دریافت می‌کنند.
- Claim تا پایان Cleanup نگه داشته می‌شود.
- Startup، Claimهای Stale را فقط طبق قواعد ایمن PID/Host/Token بازیابی می‌کند.

## معیارهای Gate

- Regression: 169 تست؛
- Acceptance اختصاصی Level 6: 11 تست؛
- Acceptance پایدار قدیمی: 3 سناریو؛
- Compile و Smoke واقعی Patchright: موفق.
