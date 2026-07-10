# گزارش پیاده‌سازی مرحله چهارم پایداری Note Maker

## موضوع مرحله

ذخیره خودکار Diagnostics در شکست نهایی هر Job، بدون نیاز به فعال‌کردن فلگ، همراه با ثبت ساختاریافته اطلاعات خطا و حفظ قابلیت ذخیره Diagnostics برای Retryهای میانی.

## تغییرات انجام‌شده

### ۱. ماژول مستقل Diagnostics

فایل جدید `scripts/diagnostics.py` اضافه شد و مسئولیت‌های زیر را بر عهده دارد:

- ساخت `run_id` یکتا برای هر Batch
- محاسبه SHA-256 متن Prompt
- ساخت مسیر امن برای هر Job
- نوشتن Atomic فایل‌های متنی و JSON
- ذخیره `metadata.json`
- ذخیره آخرین پاسخ Assistant در `last_response.txt`
- ذخیره Screenshot در `last_state.png`
- ذخیره اختیاری `page_source.html`
- کپی Artifact ردشده در Diagnostics هنگام خطای Validation
- ثبت خطاهای ثانویه Capture بدون مخفی‌کردن خطای اصلی

### ۲. Diagnostics خودکار شکست نهایی

تابع `run_with_retries()` در `scripts/batch_common.py` گسترش یافت.

رفتار جدید:

- شکست نهایی همیشه Callback مربوط به Diagnostics را اجرا می‌کند.
- برای فعال‌شدن این رفتار نیازی به `--save-diagnostics` نیست.
- `--save-diagnostics` اکنون شکست تمام Retryها را ذخیره می‌کند.
- اگر ذخیره Diagnostics شکست بخورد، Retry Loop و نتیجه اصلی Batch تغییر نمی‌کند.
- در Attempt نهایی، Chat جدید بی‌دلیل باز نمی‌شود.

### ۳. تشخیص Stage خطا

خطاها در Metadata به سه Stage تقسیم می‌شوند:

- `download`: هیچ Artifact معتبری دریافت نشده است.
- `validation`: Artifact دریافت شده ولی Validation را نگذرانده است.
- `automation`: خطاهای Selenium، مرورگر، آپلود، Timeout یا سایر Exceptionها.

در خطای Validation موارد زیر نیز ثبت می‌شوند:

- فهرست خطاهای Validation
- مسیر Candidate نگه‌داری‌شده در `_rejected`
- یک کپی از Candidate در پوشه Diagnostics، در صورت دسترس‌بودن

### ۴. ساختار پوشه Diagnostics

شکست نهایی:

```text
<output-dir>/diagnostics/<run-id>/<job>/
├── metadata.json
├── last_response.txt
├── last_state.png
└── downloaded_candidate.<ext>   # فقط در خطای Validation، در صورت وجود
```

Retryهای میانی هنگام استفاده از `--save-diagnostics`:

```text
<output-dir>/diagnostics/<run-id>/<job>/attempts/attempt-01/
```

### ۵. Page Source با سیاست Opt-in

فلگ جدید زیر به `batch_pdf.py`، `batch_markdown.py` و `pipeline.py` اضافه شد:

```bash
--save-page-source
```

به‌صورت پیش‌فرض `page_source.html` ذخیره نمی‌شود، زیرا ممکن است شامل اطلاعات حساس Session یا محتوای رابط کاربری باشد.

### ۶. اتصال به Batch Runnerها

هر دو Runner اکنون موارد زیر را ثبت می‌کنند:

- `run_id`
- Hash متن Prompt
- Source مربوط به Job
- پسوند Artifact مورد انتظار
- شماره Attempt و حداکثر Attempt
- مسیر Diagnostics شکست نهایی

### ۷. توسعه گزارش Batch

`logs/last_batch_summary.json` اکنون در بخش Extra شامل موارد زیر است:

```json
{
  "run_id": "...",
  "diagnostics": {
    "source.pdf": "/.../diagnostics/<run-id>/source.pdf"
  }
}
```

به این ترتیب مسیر عیب‌یابی هر Job شکست‌خورده مستقیماً از Summary قابل دستیابی است.

## فایل‌های تغییرکرده یا اضافه‌شده

- `scripts/diagnostics.py` — جدید
- `scripts/batch_common.py`
- `scripts/batch_pdf.py`
- `scripts/batch_markdown.py`
- `scripts/pipeline.py`
- `tests/test_diagnostics.py` — جدید
- `tests/test_batch_diagnostics_integration.py` — جدید
- `README.md`

## آزمون‌های اضافه‌شده

۱۰ تست جدید اضافه شد که موارد زیر را پوشش می‌دهند:

1. ساخت Metadata، Response و Screenshot برای شکست نهایی
2. مسیر مجزای Attempt میانی
3. حفظ Metadata و Response هنگام شکست Screenshot
4. ذخیره‌نشدن Page Source به‌صورت پیش‌فرض
5. ذخیره Page Source با فلگ صریح
6. کپی Candidate ردشده در Diagnostics
7. ذخیره فقط Attempt نهایی در حالت پیش‌فرض
8. ذخیره تمام شکست‌ها با `--save-diagnostics`
9. مخفی‌نشدن نتیجه اصلی هنگام خطای Callback
10. اتصال واقعی Batch، Summary و پوشه Diagnostics

## نتایج آزمون

- تعداد تست‌های قبلی: ۵۱
- تعداد تست‌های جدید: ۱۰
- مجموع تست‌ها: **۶۱**
- نتیجه: **تمام ۶۱ تست موفق**
- `py_compile` برای فایل‌های Python موفق بود.
- Help مربوط به سه CLI بررسی شد و فلگ `--save-page-source` در هر سه موجود است.

## Smoke Test کنترل‌شده

یک Batch ساختگی با یک فایل PDF و دو Attempt اجرا شد:

- هر دو Attempt بدون Artifact پایان یافتند.
- Exit Code برابر `2` بود.
- فقط شکست Attempt نهایی به‌صورت خودکار ذخیره شد.
- `metadata.json` دارای Stage برابر `download` و Attempt برابر `2` بود.
- مسیر نهایی Diagnostics در `last_batch_summary.json` ثبت شد.

## محدودیت بررسی

آزمون زنده با مرورگر واقعی، حساب واردشده ChatGPT و رابط فعلی وب در این محیط انجام نشد. منطق Retry، Diagnostics و اتصال Batch با Driver جعلی و تست‌های یکپارچه کنترل‌شده بررسی شده است.

## وضعیت مرحله

مرحله چهارم از برنامه پایداری تکمیل شده است. مرحله بعدی برنامه، پیاده‌سازی **Manifest و Resume واقعی** است.
