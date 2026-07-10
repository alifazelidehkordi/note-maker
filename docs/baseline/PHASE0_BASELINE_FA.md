# Baseline فاز صفر

- **تاریخ ثبت:** 2026-07-10
- **نسخه مبنا:** 0.2.0
- **هدف:** Freeze کردن رفتار پیش از استخراج Browser Provider و ساخت Parallel Runtime

## نتیجه تست پیش از تغییر

| مجموعه | نتیجه |
|---|---:|
| Unit/Integration | 78 از 78 موفق |
| Browser-free acceptance | 3 از 3 موفق |

فرمان‌های مرجع:

```bash
./run_tests.sh
./run_phase1_acceptance.sh --report docs/baseline/acceptance-before.json
```

خروجی کامل در فایل‌های زیر ثبت شده است:

- `unit-tests-before.txt`
- `acceptance-before.txt`
- `acceptance-before.json`

## Freeze سطح عمومی

Public function/class/constantهای چهار فایل اصلی در `public-api-before.json` ثبت شده‌اند:

- `scripts/run_chatgpt_temporary_test.py`
- `scripts/batch_common.py`
- `scripts/batch_pdf.py`
- `scripts/batch_markdown.py`

هش فایل‌های اصلی پیش از تغییر در `key-files-before.sha256` نگه‌داری می‌شود.

## Freeze رابط خط فرمان

Help سه CLI اصلی پیش از افزودن Feature Flagها در `cli-before/` ذخیره شده است:

- `batch-pdf-help.txt`
- `batch-markdown-help.txt`
- `pipeline-help.txt`

## قرارداد سازگاری فاز 0

- Engine فعال همچنان Selenium است.
- اجرای پیش‌فرض همچنان تک‌Browser و ترتیبی است.
- Resume، Manifest، Validation، Diagnostics و Exit Codeها تغییر معنایی ندارند.
- Feature Flagهای جدید فقط حالت `--browser-provider selenium --parallel-runs 1` را فعال می‌کنند.
- مقدار Parallel بزرگ‌تر از 1 به‌صورت Fail-Closed رد می‌شود تا قبل از Single-writer Manifest هیچ Race پنهانی ایجاد نشود.

## نتیجه پس از اجرای فاز 0

| مجموعه | پیش از تغییر | پس از تغییر |
|---|---:|---:|
| Unit/Integration | 78/78 | 86/86 |
| Browser-free acceptance | 3/3 | 3/3 |

خروجی‌های پس از تغییر در `unit-tests-after.txt`، `acceptance-after.txt` و `acceptance-after.json` ثبت شده‌اند. تفاوت Help رابط خط فرمان در `cli-help.diff` قابل مشاهده است.

Live Browser Smoke Test در این محیط اجرا نشد؛ این فاز عمداً Browser Engine را تغییر نمی‌دهد و Acceptance رسمی آن Browser-free است.
