# ADR-004: زمان‌بندی با صف پویای Job

- **وضعیت:** پذیرفته‌شده
- **تاریخ:** 2026-07-10
- **دامنه اجرا:** Coordinator

## زمینه

تقسیم ثابت بازه فایل‌ها بین Workerها باعث عدم توازن می‌شود: Worker سبک زودتر بیکار می‌ماند و Worker سنگین Tail طولانی ایجاد می‌کند. Retry و Worker Replacement نیز با بازه‌های ثابت پیچیده و شکننده می‌شوند.

## تصمیم

Coordinator یک صف Job مرکزی نگه می‌دارد. Worker پس از Ready شدن یا اتمام Job، Job بعدی را درخواست می‌کند. نسخه اول FIFO مطابق ترتیب طبیعی ورودی است؛ پس از ثبت Metric کافی، اولویت Largest Estimated Weight First قابل فعال‌سازی است.

Retry، Requeue و Lease Expiry در همان صف مدل می‌شوند و هیچ Worker مالک دائمی یک بازه نیست.

## پیامدها

- Work Distribution با سرعت واقعی Workerها تطبیق می‌یابد.
- تعداد Workerها بدون بازتقسیم دستی تغییر می‌کند.
- Scheduling باید Deterministic و قابل تست باشد.
- Job Claim و Eventهای تکراری باید Idempotent باشند.
