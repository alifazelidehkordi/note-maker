# گزارش اجرای مرحله دوم پایداری Note Maker

## دامنه انجام‌شده

مرحله دوم برنامه عملیاتی، یعنی «اعتبارسنجی Artifact و ذخیره Atomic»، روی خروجی مرحله قبل اعمال شد.

## تغییرات اصلی

### ۱. اعتبارسنجی مشترک Artifact

فایل جدید `scripts/artifact_validation.py` اضافه شد و APIهای زیر را فراهم می‌کند:

- `validate_artifact()`
- `validate_markdown()`
- `validate_opml()`
- `ValidationResult`
- `ArtifactValidationError`

### ۲. قواعد اعتبارسنجی Markdown

Markdown تنها زمانی معتبر است که:

- خالی نباشد؛
- حداقل ۱۰۰ بایت حجم داشته باشد؛
- UTF-8 معتبر باشد؛
- عنوان سطح اول `#` داشته باشد؛
- حداقل یک عنوان سطح دوم `##` داشته باشد؛
- فقط شامل Heading یا لینک دانلود نباشد؛
- حاوی پاسخ خطا یا عذرخواهی شناخته‌شده ChatGPT نباشد؛
- صفحه HTML ذخیره‌شده با پسوند Markdown نباشد.

### ۳. قواعد اعتبارسنجی OPML

OPML پیش از پذیرش:

- Repair می‌شود؛
- به‌عنوان XML Parse می‌شود؛
- باید Root از نوع `<opml>` داشته باشد؛
- باید `<body>` داشته باشد؛
- باید حداقل یک `<outline>` داشته باشد.

اعتبارسنجی معنایی OPML در `scripts/opml_utils.py` نیز تقویت شد.

### ۴. ذخیره Atomic

تابع `save_artifact_download()` در `scripts/batch_common.py` بازنویسی شد:

1. فایل دانلودی به یک فایل موقت در همان پوشه خروجی منتقل می‌شود.
2. فایل موقت اعتبارسنجی و در صورت OPML بودن Repair می‌شود.
3. فایل روی دیسک Flush می‌شود.
4. تنها پس از موفقیت کامل، با `os.replace()` جایگزین خروجی اصلی می‌شود.

خروجی قبلی پیش از پایان این مراحل حذف نمی‌شود.

### ۵. نگه‌داری فایل‌های ردشده

Artifact نامعتبر در مسیر زیر نگه‌داری می‌شود:

```text
<output-dir>/_rejected/
```

نام فایل شامل Timestamp است تا Candidateهای شکست‌خورده روی هم نوشته نشوند.

### ۶. رفتار Retry

شکست اعتبارسنجی به‌صورت Exception کنترل‌شده به Retry Loop منتقل می‌شود. پیام عمومی Retry نیز از «No OPML obtained» به «No valid artifact obtained» تغییر کرد تا برای Markdown و OPML صحیح باشد.

### ۷. مستندات

README با موارد زیر به‌روزرسانی شد:

- توضیح Validation و Atomic Save؛
- مسیر `_rejected`؛
- راهنمای عیب‌یابی Artifact ردشده؛
- تعداد و حوزه تست‌های جدید.

## فایل‌های تغییرکرده

```text
README.md
scripts/artifact_validation.py       (جدید)
scripts/batch_common.py
scripts/opml_utils.py
tests/test_artifact_validation.py    (جدید)
tests/test_atomic_artifact_save.py   (جدید)
```

## تست‌ها

### نتیجه مجموعه کامل

```text
Ran 42 tests
OK
```

- ۲۴ تست قبلی بدون Regression موفق ماندند.
- ۱۸ تست جدید برای Validation و Atomic Save اضافه شد.

### سناریوهای تست‌شده

- Markdown معتبر
- نبودن H1 یا H2
- فایل کوچک و ناقص
- پاسخ عذرخواهی یا خطای Assistant
- HTML جعلی با پسوند Markdown
- OPML معتبر
- Repair کاراکتر `&` در OPML
- OPML بدون Outline
- پسوند مورد انتظار نامعتبر یا مبهم
- جایگزینی موفق خروجی
- حفظ خروجی قبلی در شکست Validation
- حفظ Candidate نامعتبر در `_rejected`
- Repair پیش از جایگزینی OPML
- شکست مصنوعی `os.replace`
- عدم باقی‌ماندن فایل موقت
- حالت Source و Destination یکسان

## Smoke Test کنترل‌شده

نتیجه آزمون عملی:

```text
invalid_rejected= True
old_output_preserved= True
rejected_candidate_saved= True
valid_accepted= True
output_replaced= True
incoming_temp_left= False
```

این آزمون ثابت کرد Artifact ناقص نمی‌تواند خروجی سالم قبلی را حذف کند و Artifact معتبر پس از Validation به‌صورت Atomic جایگزین می‌شود.

## نتیجه

مرحله دوم کامل است. Pipeline اکنون پیش از ذخیره، ساختار واقعی Markdown یا OPML را بررسی می‌کند و دیگر خروجی سالم قبلی را پیش از اعتبارسنجی فایل جدید حذف نمی‌کند.
