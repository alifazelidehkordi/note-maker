# ADR-003: Manifest با نویسنده یکتا

- **وضعیت:** پذیرفته‌شده
- **تاریخ:** 2026-07-10
- **دامنه اجرا:** Resume، Retry و Parallel Runtime

## زمینه

`ManifestStore` فعلی هنگام ساخت Instance فایل را در حافظه بارگذاری می‌کند و `save()` کل JSON را اتمیک جایگزین می‌کند. چند Process نویسنده می‌توانند Update یکدیگر را از بین ببرند، حتی اگر هر Replace به‌تنهایی اتمیک باشد.

## تصمیم

فقط Coordinator مجاز به تغییر Manifest است. Workerها هیچ Instance نویسنده‌ای از `ManifestStore` ندارند و نتیجه کار را به‌صورت Event به Coordinator می‌فرستند.

Transitionهای مجاز شامل Pending، Running، Completed، Failed و Invalidated توسط Coordinator اعمال می‌شوند. Artifact Validation می‌تواند در Worker انجام شود، اما Commit وضعیت فقط در Coordinator است.

## پیامدها

- Lost Update حذف می‌شود.
- ترتیب Eventها و Idempotency باید تعریف شود.
- Worker Crash با Lease و Heartbeat به وضعیت قابل Resume تبدیل می‌شود.
- هر اجرای مستقل باید Claim سراسری داشته باشد تا دو Coordinator روی یک Output رقابت نکنند.

## ممنوعیت

افزودن Lock ساده به هر Worker و حفظ چند Writer، راه‌حل مورد قبول نیست؛ زیرا Merge معنایی وضعیت Job را تضمین نمی‌کند.
