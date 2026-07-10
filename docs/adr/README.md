# Architecture Decision Records

این پوشه تصمیم‌های معماری الزام‌آور برای مهاجرت Browser Runtime و اجرای موازی Note Maker را نگه می‌دارد.

| ADR | تصمیم | وضعیت |
|---|---|---|
| [ADR-001](ADR-001-browser-provider.md) | Patchright/Playwright به‌عنوان Provider اصلی آینده | پذیرفته‌شده |
| [ADR-002](ADR-002-parallel-workers.md) | Workerهای مبتنی بر Process | پذیرفته‌شده |
| [ADR-003](ADR-003-manifest-writer.md) | Manifest با نویسنده یکتا | پذیرفته‌شده |
| [ADR-004](ADR-004-job-scheduling.md) | صف پویای Job | پذیرفته‌شده |
| [ADR-005](ADR-005-worker-profiles.md) | Profile و Download مستقل برای هر Worker | پذیرفته‌شده |

هر تغییری که با این تصمیم‌ها ناسازگار باشد باید ADR جدیدی ایجاد کند که تصمیم قبلی را صریحاً جایگزین یا اصلاح کند.
