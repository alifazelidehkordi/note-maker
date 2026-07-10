# پذیرش مرحله اول پایداری

## اجرای خودکار

```bash
./run_phase1_acceptance.sh
```

در Windows:

```bat
run_phase1_acceptance.cmd
```

گزارش پیش‌فرض در مسیر زیر نوشته می‌شود:

```text
logs/phase1-acceptance.json
```

برای نگه‌داشتن تمام Artifactهای سناریو:

```bash
./run_phase1_acceptance.sh \
  --workdir /tmp/notemaker-phase1-acceptance \
  --report /tmp/notemaker-phase1-acceptance/report.json
```

## سناریوهای خودکار

### 1. شکست جزئی و Diagnostics

دو Source ساختگی وارد Batch می‌شوند. اولی یک Markdown معتبر می‌سازد و دومی در هر دو Attempt فایل نامعتبر تولید می‌کند. معیارهای پذیرش:

- Exit Code برابر `2`؛
- Job اول `completed`؛
- Job دوم `failed` با دو Attempt؛
- فایل نامعتبر جایگزین خروجی نشود؛
- هر Candidate ردشده در `_rejected` حفظ شود؛
- Diagnostics نهایی و مسیر آن در Summary وجود داشته باشد.

### 2. Retry و Resume

با `--retry-failed` فقط Job ناموفق اجرا و تکمیل می‌شود. سپس یک اجرای بدون تغییر انجام می‌شود. معیارهای پذیرش:

- Job موفق قبلی اجرا نشود؛
- Attemptهای قبلی حفظ شوند؛
- هر دو Job Completed شوند؛
- اجرای سوم هر دو را Skip کند؛
- Browser Driver ساخته نشود.

### 3. PDF End-to-End

دو Markdown نهایی با WeasyPrint به PDF تبدیل و با PyPDF ادغام می‌شوند. معیارهای پذیرش:

- دو PDF موضوعی تولید شوند؛
- فایل ترکیبی Index داشته باشد؛
- هیچ URI محلی `note:` یا `file:` باقی نماند؛
- Bookmark فهرست و هر دو Topic وجود داشته باشد؛
- Metadata عنوان صحیح باشد.

## Smoke Test دستی Browser

آزمون خودکار به حساب ChatGPT متصل نمی‌شود. پیش از Release عمومی این تست دستی انجام شود:

1. دو فایل کوچک واقعی در `inputs/` قرار دهید.
2. یک اجرای کامل با Profile آزمایشی انجام دهید.
3. اجرای دوم را بدون تغییر تکرار و عدم بازشدن Browser را بررسی کنید.
4. Prompt را تغییر دهید و بازسازی Jobها را تأیید کنید.
5. Browser را وسط Job دوم ببندید.
6. اجرای بعدی را انجام دهید و Recovery همان Job را بررسی کنید.
7. یک خروجی عمداً نامعتبر ایجاد و پوشه Diagnostics را بررسی کنید.
8. PDFها و فایل ترکیبی را تولید و لینک‌های فهرست را دستی باز کنید.

نتیجه Smoke Test دستی باید در `RELEASE_CHECKLIST.md` ثبت شود.
