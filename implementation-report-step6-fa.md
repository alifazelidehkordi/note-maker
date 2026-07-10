# گزارش پیاده‌سازی مرحله ششم — یکپارچه‌سازی، پذیرش و Release

## نتیجه

مرحله ششم و نهایی فاز پایداری روی نسخه مرحله پنجم اعمال شد. پروژه اکنون نسخه `0.2.0` دارد و علاوه بر تست‌های واحد، یک سناریوی پذیرش End-to-End کنترل‌شده و مرورگر-آزاد ارائه می‌کند.

## تغییرات انجام‌شده

### 1. Acceptance Runner مستقل

فایل جدید:

```text
scripts/phase1_acceptance.py
```

Runner سه جریان متوالی را اجرا می‌کند:

1. شکست جزئی Batch، Validation، نگه‌داری Candidateهای ردشده، Diagnostics و Exit Code برابر `2`؛
2. اجرای `--retry-failed` فقط برای Job ناموفق و سپس Resume بدون ساخت Browser؛
3. تبدیل واقعی دو Note به PDF، ساخت فایل ترکیبی، کنترل URIهای محلی، Bookmarkها و Metadata.

گزارش JSON نسخه‌دار تولید می‌شود و کد خروج Runner در شکست پذیرش برابر `2` است.

### 2. Runnerهای سیستم‌عامل

```text
run_phase1_acceptance.sh
run_phase1_acceptance.cmd
```

### 3. تست یکپارچه جدید

```text
tests/test_phase1_acceptance.py
```

این تست کل Acceptance Runner را در Temporary Workspace اجرا می‌کند. تعداد تست‌های پروژه از ۷۷ به ۷۸ افزایش یافت.

### 4. مستندات Release

فایل‌های جدید:

```text
VERSION
CHANGELOG.md
RELEASE_CHECKLIST.md
docs/PHASE1_MIGRATION_FA.md
docs/PHASE1_ACCEPTANCE_FA.md
```

README نیز با نسخه، تعداد تست، فرمان Acceptance، روش مهاجرت و لینک مستندات جدید به‌روزرسانی شد.

### 5. CI

Workflow جدید:

```text
.github/workflows/phase1-stability.yml
```

شامل:

- تست روی Ubuntu و Windows؛
- Python 3.10 و 3.12؛
- Compile Check؛
- Acceptance مستقل روی Ubuntu؛
- Upload گزارش JSON حتی در صورت شکست.

فایل Workflow از نظر YAML محلی Parse شده است، اما اجرای واقعی GitHub Actions در این محیط ممکن نبود.

## نتایج آزمون

### Compile

```text
python3 -m compileall -q scripts tests
Result: PASS
```

### مجموعه کامل

```text
Ran 78 tests
OK
```

### Acceptance مستقل

هر سه Check موفق شدند:

```text
PASS batch_failure_and_diagnostics
PASS retry_failed_and_resume
PASS pdf_book_end_to_end
```

خروجی PDF پذیرش:

- ۲ PDF موضوعی؛
- فایل ترکیبی ۴ صفحه‌ای؛
- ۲ صفحه Index؛
- ۸ لینک داخلی تبدیل‌شده؛
- بدون URI محلی `note:` یا `file:`؛
- Bookmark فهرست و هر دو Topic موجود.

## معیارهای پایان مرحله

| معیار | نتیجه |
|---|---|
| تست Failure Injection | انجام شد |
| Resume بدون Browser | انجام شد |
| `--retry-failed` هدفمند | انجام شد |
| PDF End-to-End واقعی | انجام شد |
| بررسی لینک و Bookmark | انجام شد |
| مستندات مهاجرت | انجام شد |
| Changelog و Version | انجام شد |
| Release Checklist | انجام شد |
| CI Linux/Windows | تعریف شد؛ اجرای Remote انجام نشد |
| Smoke Test زنده ChatGPT | انجام نشد؛ در Checklist دستی باقی مانده است |

## محدودیت باقی‌مانده

این محیط حساب واردشده ChatGPT و Browser Session واقعی نداشت؛ بنابراین Smoke Test زنده Selenium انجام نشد. Acceptance خودکار، Retry/Resume/Diagnostics را با Fake Driver و Fake Provider اجرا می‌کند و بخش PDF را با WeasyPrint و PyPDF واقعی می‌سازد.
