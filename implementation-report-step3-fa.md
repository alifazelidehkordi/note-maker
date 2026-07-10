# گزارش پیاده‌سازی مرحله سوم پایداری Note Maker

## موضوع مرحله

محدودسازی تشخیص دانلود بر اساس نوع Artifact مورد انتظار و جلوگیری از انتخاب فایل‌های قدیمی، نامرتبط یا متعلق به پاسخ‌های قبلی.

## تغییرات انجام‌شده

### ۱. قرارداد صریح نوع خروجی

تمام مسیرهای اصلی دانلود اکنون `expected_extensions` دریافت می‌کنند. در نتیجه:

- Jobهای یادداشت فقط `.md` و `.markdown` را می‌پذیرند.
- Jobهای Mind Map فقط `.opml` را می‌پذیرند.
- پسوندهای پشتیبانی‌نشده با `ValueError` رد می‌شوند.
- وجود کلمات عمومی `file` یا `notes` دیگر برای معتبرشناختن لینک کافی نیست.

پارامتر نوع خروجی در توابع زیر اعمال شده است:

- `resolve_download`
- `click_new_download_link`
- `click_candidate_and_wait`
- `wait_and_salvage_download`
- `wait_for_download_settled`
- `newest_download`
- `find_artifact_candidates_in_downloads`
- `is_artifact_download_file`
- `is_artifact_download_trigger`

### ۲. Snapshot دقیق پوشه دانلود

Snapshot قبلی فقط مجموعه‌ای از نام فایل‌ها بود. ساختار جدید برای هر مسیر موارد زیر را ثبت می‌کند:

```text
path -> (mtime_ns, size)
```

این تغییر سه حالت را از هم جدا می‌کند:

1. فایل جدید با نام جدید
2. فایل جدیدی که مرورگر روی نام قبلی نوشته است
3. فایل قدیمی و بدون تغییر

بنابراین Overwrite شدن فایلی با همان نام نیز به‌درستی شناسایی می‌شود.

### ۳. محدودیت زمانی دانلود

هر Batch Runner درست پیش از ارسال Prompt مقدار `time.time_ns()` را ثبت می‌کند. فایل Candidate باید:

- بعد از Snapshot ایجاد یا تغییر کرده باشد؛ و
- زمان تغییر آن با زمان شروع درخواست سازگار باشد.

فایلی که بعداً به پوشه کپی شده ولی `mtime` قدیمی خود را حفظ کرده است، انتخاب نمی‌شود.

### ۴. اولویت آخرین پاسخ Assistant

جست‌وجوی Attachment و Download Control ابتدا فقط در آخرین پیام Assistant انجام می‌شود. پاسخ‌های قبلی در مرحله اول Scan نمی‌شوند.

Fallback سراسری صفحه نیز فقط موارد زیر را بررسی می‌کند:

- href دارای پسوند دقیق مورد انتظار
- نام صریح فرمت `OPML`
- نام صریح فرمت `Markdown`

لینک‌های عمومی مانند `Download apps`، `Download file` و `notes` نادیده گرفته می‌شوند.

### ۵. اتصال به Batch Runnerها

در `batch_pdf.py` و `batch_markdown.py`:

- Snapshot با `snapshot_downloads()` گرفته می‌شود.
- زمان شروع درخواست ثبت می‌شود.
- پسوند خروجی همان Job به `resolve_download()` ارسال می‌شود.

برای مثال:

```python
core.resolve_download(
    driver,
    before_downloads,
    expected_extensions={f".{ext}"},
    started_at_ns=download_started_at_ns,
    timeout=download_timeout,
)
```

### ۶. سازگاری توابع قدیمی

Helperهای قدیمی OPML حذف نشده‌اند و اکنون Wrapper نوع‌محدود هستند:

- `is_opml_download_file`
- `is_opml_download_trigger`
- `find_opml_candidates_in_downloads`

این Wrapperها برخلاف Alias قبلی، Markdown را به‌عنوان OPML قبول نمی‌کنند.

## فایل‌های تغییرکرده

```text
README.md
scripts/batch_common.py
scripts/batch_markdown.py
scripts/batch_pdf.py
scripts/run_chatgpt_temporary_test.py
tests/test_download_detection.py
tests/test_download_contract.py
```

## تست‌های اضافه‌شده یا توسعه‌یافته

سناریوهای زیر پوشش داده شدند:

- رد لینک‌های دانلود برنامه ChatGPT
- رد عبارت‌های عمومی `file` و `notes`
- پذیرش فقط پسوند مورد انتظار
- رد OPML در Job Markdown
- رد Markdown در Job OPML
- تشخیص نوع فایل بدون پسوند از روی محتوا
- رد پسوند پشتیبانی‌نشده
- نادیده‌گرفتن فایل قدیمی و بدون تغییر
- نادیده‌گرفتن فایل جدید با نوع اشتباه
- تشخیص Overwrite همان نام فایل
- رد فایل تازه‌کپی‌شده با `mtime` قدیمی
- انتخاب فایل صحیح حتی اگر فایل نوع اشتباه جدیدتر باشد
- اولویت آخرین پیام Assistant
- بررسی ارسال `expected_extensions` و `started_at_ns` از هر دو Batch Runner

## نتایج آزمون

### مجموعه تست پروژه

```text
Ran 51 tests
OK
```

### بررسی Syntax و CLI

```text
python -m compileall -q scripts tests
python scripts/run_chatgpt_temporary_test.py --help
python scripts/batch_pdf.py --help
python scripts/batch_markdown.py --help
```

نتیجه: موفق.

### Smoke Test مستقل پوشه دانلود

در یک پوشه موقت موارد زیر ایجاد و بررسی شد:

1. یک Markdown قدیمی پیش از Snapshot
2. یک OPML جدیدتر ولی نامرتبط
3. یک Markdown جدید و صحیح
4. بازنویسی Markdown صحیح با همان نام

نتیجه:

```text
SMOKE_OK: type filtering, stale rejection, and same-name overwrite detection
```

## محدودیت آزمون

آزمون زنده با حساب واردشده ChatGPT و مرورگر واقعی در این محیط انجام نشد. منطق تشخیص، قرارداد Runnerها، CLI، Syntax، تست‌های واحد و Smoke Test فایل‌سیستم همگی اجرا و تأیید شدند.

## معیار پذیرش مرحله

| معیار | نتیجه |
|---|---|
| Job Markdown فایل OPML را قبول نکند | انجام شد |
| Job OPML فایل Markdown را قبول نکند | انجام شد |
| لینک‌های عمومی `file` و `notes` رد شوند | انجام شد |
| آخرین پیام Assistant در اولویت باشد | انجام شد |
| فایل قدیمی Downloads انتخاب نشود | انجام شد |
| Overwrite همان نام قابل تشخیص باشد | انجام شد |
| Runnerها نوع مورد انتظار را ارسال کنند | انجام شد |
| تست‌های قبلی دچار Regression نشوند | انجام شد؛ ۵۱ تست موفق |
