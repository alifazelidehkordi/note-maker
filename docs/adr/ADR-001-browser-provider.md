# ADR-001: انتخاب Patchright/Playwright به‌عنوان Browser Provider اصلی

- **وضعیت:** پذیرفته‌شده
- **تاریخ:** 2026-07-10
- **دامنه اجرا:** فازهای 1 و 2

## زمینه

Browser Automation فعلی Note Maker در یک ماژول بزرگ Selenium قرار دارد و بخشی از Upload و تعامل با سیستم‌عامل به PyAutoGUI و Clipboard وابسته است. این مدل برای چند Browser هم‌زمان قابل اتکا نیست. پروژه مایندمپ یک پیاده‌سازی Patchright/Playwright با Persistent Context، تشخیص بهتر وضعیت پاسخ، بازیابی شبکه و Download Handling قوی‌تر دارد.

## تصمیم

Patchright/Playwright Provider اصلی آینده خواهد بود. Selenium در فاز 0 رفتار مرجع و Provider فعال باقی می‌ماند و در فاز 1 پشت قرارداد `BrowserProvider` قرار می‌گیرد. مهاجرت واقعی Engine در فاز 2 انجام می‌شود.

کد Batch حق دسترسی مستقیم به Selenium Element، Playwright Locator یا Page را نخواهد داشت. تمام تعاملات باید از قرارداد Provider عبور کند.

## پیامدها

- مهاجرت بدون Big Bang Rewrite ممکن می‌شود.
- تست Fake Provider مستقل از Browser قابل ساخت است.
- Selenium تا اثبات برابری رفتاری حذف نمی‌شود.
- در فاز 0 مقدار معتبر `--browser-provider` فقط `selenium` است.

## معیار بازنگری

این تصمیم فقط در صورت شکست اثبات‌شده Patchright در Persistent Context، Download Event یا سازگاری چندسیستم‌عاملی بازنگری می‌شود.
