# گزارش پیاده‌سازی مرحله پنجم پایداری Note Maker

## موضوع مرحله

پیاده‌سازی **Manifest نسخه‌دار و Resume واقعی** برای هر دو Batch Runner پروژه، به‌گونه‌ای که وضعیت هر Job، Hash منبع و Prompt، تعداد Attemptها، خروجی نهایی و خطاهای آخر به‌شکل Atomic ثبت شوند و اجرای مجدد فقط Jobهای لازم را پردازش کند.

## تغییرات انجام‌شده

### ۱. ماژول مستقل Manifest

فایل جدید `scripts/manifest.py` اضافه شد. این ماژول مسئول موارد زیر است:

- Schema نسخه‌دار با `schema_version: 1`
- محاسبه SHA-256 فایل، متن Section، Prompt و خروجی
- تعریف `JobSpec` برای فایل‌ها و Sectionهای Markdown
- تصمیم‌گیری Resume با خروجی‌های `run`، `skip` و `adopt`
- ثبت وضعیت‌های:
  - `pending`
  - `running`
  - `completed`
  - `failed`
  - `invalidated`
- نوشتن Atomic فایل `manifest.json`
- نگه‌داری نسخه قبلی سالم در `manifest.json.bak`
- اعتبارسنجی خروجی Completed پیش از Skip
- تشخیص خروجی مفقود، نامعتبر یا دست‌کاری‌شده با Hash

مسیر پیش‌فرض Manifest:

```text
<output-dir>/manifest.json
```

### ۲. ساختار هر Job در Manifest

هر رکورد اطلاعات زیر را نگه می‌دارد:

```json
{
  "source": "/path/source.pdf",
  "source_hash": "sha256:...",
  "prompt": "/path/prompt.md",
  "prompt_hash": "sha256:...",
  "output": "/path/output.md",
  "output_hash": "sha256:...",
  "expected_extensions": [".md"],
  "mode": "pdf-md",
  "model": null,
  "status": "completed",
  "attempts": 2,
  "started_at": "...",
  "finished_at": "...",
  "last_error": null,
  "diagnostics": null,
  "adopted": false
}
```

### ۳. Resume واقعی در `batch_pdf.py`

پیش از بازشدن مرورگر، برای تمام فایل‌ها `JobSpec` ساخته و Manifest بررسی می‌شود.

رفتار جدید:

- خروجی Completed با Source Hash، Prompt Hash و Output Hash معتبر: `skip`
- فایل Source تغییرکرده: `invalidated` و اجرای مجدد
- محتوای Prompt تغییرکرده: `invalidated` و اجرای مجدد
- مدل، نوع خروجی یا مسیر Output تغییرکرده: اجرای مجدد
- خروجی حذف‌شده، نامعتبر یا دارای Hash متفاوت: اجرای مجدد
- Job با وضعیت `failed`: Retry در اجرای بعدی
- Job با وضعیت `running`: بازیابی به‌عنوان اجرای قطع‌شده
- فایل خروجی قدیمی بدون Manifest: به‌صورت پیش‌فرض دوباره ساخته می‌شود
- اگر هیچ Job قابل اجرایی وجود نداشته باشد، مرورگر اصلاً باز نمی‌شود

Job Key فایل‌ها:

```text
<relative-source-path>::<extension>
```

نمونه:

```text
03_lipid.pdf::md
```

### ۴. Resume مستقل در سطح Section

در `batch_markdown.py` Hash هر Section از متن همان Section محاسبه می‌شود، نه از کل فایل Markdown.

Job Key Sectionها:

```text
<markdown-file>::section-<index>::<extension>
```

نمونه:

```text
lecture.md::section-0002::md
```

نتیجه:

- تغییر Section دوم فقط Section دوم را Invalid می‌کند.
- Sectionهای بدون تغییر Skip می‌شوند.
- اجرای دوم بدون تغییر، هیچ درخواست جدیدی به ChatGPT ارسال نمی‌کند.

### ۵. ثبت دقیق Attemptها و بازیابی Crash

تابع `run_with_retries()` در `scripts/batch_common.py` یک Callback جدید برای شروع Attempt دریافت می‌کند.

پیش از هر Attempt:

- وضعیت Job برابر `running` می‌شود.
- شمار Attemptها افزایش می‌یابد.
- `run_id` و شماره Attempt فعلی ثبت می‌شوند.

اگر برنامه یا مرورگر پس از این مرحله قطع شود، رکورد `running` باقی می‌ماند و اجرای بعدی آن را به‌عنوان Job قطع‌شده دوباره اجرا می‌کند.

در پایان:

- موفقیت: `completed` همراه با Output Hash
- شکست نهایی: `failed` همراه با نوع خطا، پیام و مسیر Diagnostics

### ۶. مهاجرت خروجی‌های موجود

فلگ جدید:

```bash
--adopt-existing
```

این فلگ خروجی‌های موجود بدون Manifest را:

1. اعتبارسنجی می‌کند.
2. Hash می‌گیرد.
3. با `attempts: 0` و `adopted: true` ثبت می‌کند.
4. بدون بازکردن مرورگر Skip می‌کند.

خروجی نامعتبر Adopt نمی‌شود و برای بازسازی برنامه‌ریزی خواهد شد.

### ۷. فلگ‌های جدید CLI

فلگ‌های زیر به `batch_pdf.py`، `batch_markdown.py` و `pipeline.py` اضافه شدند:

```text
--manifest PATH
--no-resume
--retry-failed
--adopt-existing
```

رفتار:

- `--manifest PATH`: استفاده از مسیر سفارشی Manifest
- `--no-resume`: نادیده‌گرفتن تصمیم Resume و اجرای مجدد Jobهای انتخاب‌شده؛ نتیجه همچنان ثبت می‌شود
- `--retry-failed`: فقط Jobهای Failed، Running، Pending یا Invalidated قبلی را اجرا می‌کند
- `--adopt-existing`: خروجی‌های معتبر قدیمی را ثبت می‌کند
- `--overwrite`: بر تصمیم Resume اولویت دارد و همه Jobهای انتخاب‌شده را دوباره اجرا می‌کند

### ۸. توسعه Batch Summary

`logs/last_batch_summary.json` اکنون اطلاعات زیر را نیز ثبت می‌کند:

```json
{
  "manifest": "/.../manifest.json",
  "resume_enabled": true,
  "retry_failed_only": false,
  "skipped": {
    "source.pdf": "completed output is valid"
  },
  "adopted": []
}
```

### ۹. رفتار Atomic و Backup

هنگام ذخیره Manifest:

1. JSON کامل در فایل Temp نوشته می‌شود.
2. فایل `fsync` می‌شود.
3. نسخه فعلی در `manifest.json.bak` کپی می‌شود.
4. Temp با `os.replace` جایگزین Manifest اصلی می‌شود.
5. در شکست Replace، Manifest قبلی دست‌نخورده باقی می‌ماند.

## فایل‌های تغییرکرده یا اضافه‌شده

- `scripts/manifest.py` — جدید
- `scripts/batch_pdf.py`
- `scripts/batch_markdown.py`
- `scripts/batch_common.py`
- `scripts/pipeline.py`
- `tests/test_manifest.py` — جدید
- `tests/test_resume_integration.py` — جدید
- `README.md`
- `implementation-report-step5-fa.md` — جدید

## آزمون‌های اضافه‌شده

۱۶ تست جدید اضافه شد که موارد زیر را پوشش می‌دهند:

1. اجرای Job جدید و Skip خروجی Completed معتبر
2. Invalid شدن با تغییر Source Hash
3. Invalid شدن با تغییر Prompt Hash
4. عدم Invalid شدن صرفاً با جابه‌جایی Prompt هم‌محتوا
5. تشخیص خروجی مفقود، نامعتبر و دارای Hash تغییرکرده
6. بازیابی وضعیت `running`
7. اجرای مجدد وضعیت `failed`
8. عدم اعتماد پیش‌فرض به خروجی بدون Manifest
9. Adopt خروجی موجود معتبر
10. فیلتر `--retry-failed`
11. Hash مستقل Sectionها
12. حفظ Manifest قبلی در شکست Atomic Replace
13. بررسی Schema و شمار Attempt
14. اجرای دوم PDF بدون بازشدن مرورگر
15. اجرای مجدد فقط PDF تغییرکرده
16. اجرای مجدد فقط Section تغییرکرده و Adopt بدون مرورگر

## نتایج آزمون

- تعداد تست‌های قبلی: ۶۱
- تعداد تست‌های جدید: ۱۶
- مجموع تست‌ها: **۷۷**
- نتیجه: **تمام ۷۷ تست موفق**
- `py_compile` برای همه فایل‌های Python موفق بود.
- Help سه CLI بررسی شد و هر چهار فلگ جدید در آن‌ها موجود است.

## Smoke Test کنترل‌شده

یک چرخه سه‌مرحله‌ای اجرا شد:

1. اجرای اول یک PDF ساختگی: Artifact تولید و Manifest Completed شد.
2. اجرای دوم بدون تغییر: Job Skip شد و `bootstrap_session` فراخوانی نشد.
3. وضعیت Manifest به‌صورت مصنوعی `running` شد تا Crash شبیه‌سازی شود؛ اجرای بعدی Job را بازیابی و تکمیل کرد.

نتیجه نهایی:

```text
SMOKE_OK completed 2
```

یعنی Job پس از بازیابی Crash با وضعیت Completed و دو Attempt ثبت شد.

## محدودیت بررسی

آزمون زنده با مرورگر واقعی، حساب واردشده ChatGPT و رابط فعلی وب در این محیط انجام نشد. منطق Manifest، Resume، Retry، Migration و اتصال هر دو Batch Runner با Driver جعلی و Smoke Test کنترل‌شده بررسی شده است.

## وضعیت مرحله

مرحله پنجم برنامه پایداری، یعنی **Manifest و Resume واقعی**، تکمیل شده است. مرحله بعدی برنامه، یکپارچه‌سازی نهایی، تست End-to-End کنترل‌شده، مستندات Release و آماده‌سازی نسخه پایدار است.
