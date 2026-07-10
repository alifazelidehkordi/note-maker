# ADR-005: Profile، Download و Diagnostics مستقل برای هر Worker

- **وضعیت:** پذیرفته‌شده
- **تاریخ:** 2026-07-10
- **دامنه اجرا:** Browser Runtime و Parallel Runtime

## زمینه

مسیرهای مشترک `chrome_profile/`، `downloads/`، `run.log` و Diagnostics در اجرای هم‌زمان باعث Lock مرورگر، تشخیص اشتباه Download و Overwrite شدن شواهد خطا می‌شوند.

## تصمیم

هر Run دارای `run_id` و هر Worker دارای Runtime Directory مستقل است:

```text
.runtime/runs/<run-id>/workers/<worker-id>/
├── profile/
├── downloads/
├── diagnostics/
└── worker.log
```

Login در یک Profile مرجع انجام می‌شود. Snapshot نشست فقط وقتی ساخته می‌شود که Browser مرجع کاملاً بسته باشد. سپس قبل از شروع Workerها به Profile اختصاصی آن‌ها Clone می‌شود. Copy کردن Profile فعال ممنوع است.

## پیامدها

- Browser Lock و تداخل Download حذف می‌شود.
- Cleanup و نگه‌داری Runهای شکست‌خورده باید Policy مشخص داشته باشد.
- فضای دیسک با تعداد Worker افزایش می‌یابد.
- مسیر هر Artifact و Diagnostic قابل انتساب به Worker و Job خواهد بود.
