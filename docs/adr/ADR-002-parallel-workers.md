# ADR-002: اجرای Workerها در Processهای مستقل

- **وضعیت:** پذیرفته‌شده
- **تاریخ:** 2026-07-10
- **دامنه اجرا:** Parallel Runtime

## زمینه

Browser Contextها، Event Loopها و وابستگی‌های UI برای اجرای Thread-based قابل اتکای کافی نیستند. Crash یا Hang یک Browser نیز نباید Coordinator یا Workerهای دیگر را آلوده کند.

## تصمیم

هر Browser Worker در Process مستقل اجرا می‌شود. ساخت Process با `multiprocessing.get_context("spawn")` انجام خواهد شد تا رفتار Windows و Linux هم‌راستا باشد.

Coordinator تنها مالک صف، Manifest و چرخه عمر Workerها است. Worker فقط یک Browser Session بلندعمر و در هر لحظه یک Job فعال دارد.

## پیامدها

- Profile، Environment، Download و Log هر Worker ایزوله می‌شود.
- Crash یک Worker قابل تشخیص، Terminate و Respawn است.
- داده‌های بین Processها باید Serializable و قراردادمحور باشند.
- هزینه Startup بیشتر از Thread است، اما با Session بلندعمر جبران می‌شود.

## Guardrail فاز 0

تا زمان آماده‌شدن Coordinator، `--parallel-runs` فقط مقدار `1` را می‌پذیرد و مقادیر بالاتر با خطای صریح متوقف می‌شوند.
