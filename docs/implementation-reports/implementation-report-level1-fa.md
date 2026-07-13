# گزارش فنی Level 1 — Browser Contract و Compatibility Layer

> نسخه پروژه: **0.3.0**  
> تاریخ اجرا: **2026-07-10**  
> وضعیت: **تکمیل‌شده و آماده ورود به Level 2**

## 1. هدف Level 1

هدف این سطح، جداکردن منطق Batch، Retry، Manifest و Diagnostics از Selenium بود؛ بدون آنکه موتور مرورگر فعال یا رفتار پیش‌فرض کاربر تغییر کند. نتیجه باید یک مرز معماری پایدار ایجاد می‌کرد تا Patchright در Level 2 به‌عنوان Provider جدید اضافه شود و نیازی به بازنویسی Batchها وجود نداشته باشد.

در این سطح اجرای موازی واقعی عمداً فعال نشده است. مقدار `--parallel-runs` همچنان فقط `1` را می‌پذیرد تا پیش از ایجاد Coordinator و Single-writer Manifest هیچ Race Condition پنهانی وارد سیستم نشود.

## 2. معماری پیاده‌سازی‌شده

### 2.1. قراردادهای مستقل از Engine

Package جدید زیر ایجاد شد:

```text
scripts/browser_runtime/
├── __init__.py
├── contracts.py
├── errors.py
├── factory.py
├── models.py
├── selenium_provider.py
└── selenium_legacy.py
```

دو قرارداد اصلی تعریف شدند:

- `BrowserProvider`: مسئول ساخت یا Wrap کردن Session؛
- `BrowserSession`: رابط سطح بالا برای تمام عملیات موردنیاز Batch.

`BrowserSession` عملیات زیر را پوشش می‌دهد:

- بررسی سلامت و بستن Session؛
- Navigation و تشخیص Login؛
- شروع Temporary Chat و انتخاب Model؛
- Upload فایل؛
- ارسال Prompt؛
- انتظار برای پایان Response؛
- Snapshot و Resolve کردن Download؛
- خواندن آخرین پاسخ Assistant؛
- Screenshot و Page Source؛
- خواندن و حذف Cookieهای Automation.

Batchها دیگر برای انجام این عملیات به Selenium Driver، `find_element`، `find_elements` یا Locator وابسته نیستند.

### 2.2. مدل‌های نوع‌دار

مدل‌های زیر اضافه شدند:

- `BrowserLaunchOptions`
- `UploadRequest`
- `ResponseWaitRequest`
- `DownloadRequest`
- `BrowserOperationRecord`

این مدل‌ها ورودی‌های Browser Runtime را Normalize و Validate می‌کنند. برای نمونه، Extensionهای مورد انتظار به فرم استاندارد مانند `.md` و `.opml` تبدیل می‌شوند و Timeout نامعتبر پیش از رسیدن به Provider رد می‌شود.

### 2.3. Error Taxonomy

خطاهای Browser Runtime به کلاس‌های مستقل تبدیل شدند:

- `BrowserStartupError`
- `BrowserAuthenticationError`
- `BrowserNavigationError`
- `BrowserUploadError`
- `BrowserSendError`
- `BrowserResponseTimeout`
- `BrowserDownloadError`
- `BrowserCrashedError`
- `TemporaryChatError`
- `UnsupportedBrowserCapability`

`SeleniumProvider` خطاهای Legacy را بر اساس Operation و نشانه‌های Crash/Disconnect به این Taxonomy تبدیل می‌کند. این ساختار برای تصمیم‌گیری Retry و Recovery در Levelهای بعدی ضروری است.

## 3. Selenium Provider و Compatibility

### 3.1. SeleniumProvider

`SeleniumProvider` موتور فعال Level 1 است. این Provider رفتار Selenium موجود را تغییر نمی‌دهد و فقط آن را پشت قرارداد جدید قرار می‌دهد.

`SeleniumBrowserSession` عملیات سطح بالا را به API Legacy Delegate می‌کند و Raw Driver را فقط داخل Adapter نگه می‌دارد. Batchها Raw Driver را مشاهده یا استفاده نمی‌کنند.

### 3.2. Compatibility Facade

فایل عمومی سابق:

```text
scripts/run_chatgpt_temporary_test.py
```

به Compatibility Facade تبدیل شد. پیاده‌سازی قبلی به فایل زیر منتقل شد:

```text
scripts/browser_runtime/selenium_legacy.py
```

Facade ویژگی‌های زیر را حفظ می‌کند:

- تمام **51 تابع عمومی** ثبت‌شده در Baseline؛
- Signatureهای قبلی از طریق `functools.wraps`؛
- قابلیت Patch کردن توابع و مسیرهایی مثل `DOWNLOAD_DIR` و `LOG_FILE`؛
- CLI و `main()` قبلی؛
- رفتار Download Detection و Selenium فعلی.

نتیجه بررسی خودکار Compatibility:

```json
{
  "baseline_function_count": 51,
  "facade_function_count": 51,
  "missing_baseline_functions": [],
  "extra_public_functions": [],
  "compatible": true
}
```

## 4. تغییرات Batch و Recovery

### 4.1. PDF Batch

`batch_pdf.process_one` اکنون فقط از متدهای `BrowserSession` استفاده می‌کند:

```text
start_new_chat
select_model
snapshot_downloads
upload
assistant_message_count
send_message
wait_for_response
resolve_download
```

### 4.2. Markdown Batch

`batch_markdown.process_markdown_section` نیز به همان قرارداد منتقل شد و دیگر هیچ Browser Operation را مستقیماً از Core Legacy فراخوانی نمی‌کند.

### 4.3. Batch Common

موارد زیر Provider-aware شدند:

- `bootstrap_session`
- `recreate_driver`
- `recover_from_chat_error`
- `run_with_retries`
- `reset_chat`
- `warm_up`
- `driver_is_alive`
- `quit_driver`
- Cookie Pruning
- Failure Capture

نام‌های Compatibility مانند `recreate_driver` و `quit_driver` فعلاً حفظ شده‌اند، اما پیاده‌سازی آن‌ها روی `BrowserSession` است.

Provider از طریق Factory ساخته می‌شود:

```python
provider = create_browser_provider("selenium")
```

## 5. Diagnostics مستقل از Selenium

Diagnostics دیگر وجود Property مخصوص Selenium را فرض نمی‌کند.

- Screenshot از Capability متد `save_screenshot` گرفته می‌شود؛
- Page Source ابتدا از `get_page_source()` خوانده می‌شود؛
- Property قدیمی `page_source` برای سازگاری همچنان پشتیبانی می‌شود؛
- خطای Screenshot یا Page Source همچنان Best-effort است و خطای اصلی Job را Mask نمی‌کند.

## 6. Fake Browser Provider

Fake استاندارد زیر اضافه شد:

```text
tests/fakes/fake_browser_provider.py
```

این Fake دارای Operation Log و Plan قابل تنظیم است و سناریوهای زیر را بدون Browser واقعی اجرا می‌کند:

1. Success و تولید Artifact معتبر؛
2. Response Timeout نوع‌دار؛
3. Browser Crash نوع‌دار؛
4. Download نامعتبر و ردشدن توسط Validator موجود؛
5. Screenshot و Page Source برای Diagnostics؛
6. ثبت Launch Options و ترتیب عملیات.

Fake Provider به جای جایگزین‌کردن Validator یا Manifest، دقیقاً از همان لایه‌های واقعی Note Maker عبور می‌کند.

## 7. Guardrailهای معماری

تست AST جدید تضمین می‌کند که فایل‌های زیر از Locator خام استفاده نکنند:

- `batch_common.py`
- `batch_pdf.py`
- `batch_markdown.py`

موارد ممنوع:

```text
find_element
find_elements
locator
query_selector
```

تست دیگری بررسی می‌کند که PDF و Markdown عملیات Browser را از `core.*` دور نزنند.

همچنین Importهای Selenium فقط در `selenium_legacy.py` مجاز شناخته شده‌اند و Facade و Batchها Import مستقیم Selenium ندارند.

## 8. نتایج Verification

### Unit و Integration

- تعداد تست‌ها: **101**
- موفق: **101**
- ناموفق: **0**

### Acceptance مرورگر-آزاد

سه سناریوی Acceptance موفق شدند:

1. Partial Failure، Validation و Diagnostics؛
2. `--retry-failed` و Resume بدون بازشدن Browser در اجرای بدون تغییر؛
3. PDF Book End-to-End با لینک داخلی و Bookmark.

### Compile

```text
python -m compileall -q scripts tests
```

نتیجه: **Pass**

### Compatibility

- 51/51 تابع عمومی Facade حفظ شده‌اند؛
- CLIهای PDF، Markdown و Pipeline قابل تولید هستند؛
- Behavior پیش‌فرض همچنان Selenium و تک‌Session است.

### Live Browser

Live Browser Smoke Test در این محیط اجرا نشد. بنابراین Login، Upload و Download واقعی با حساب ChatGPT باید پیش از Release عملیاتی روی ماشین دارای Browser و Profile معتبر یک بار به‌صورت دستی اجرا شود.

## 9. مواردی که عمداً در Level 1 انجام نشدند

- Patchright Provider؛
- Persistent Context مبتنی بر Playwright؛
- Profile Clone و Session Snapshot؛
- Coordinator و Worker Process؛
- Dynamic Job Queue؛
- Single-writer Manifest Runtime؛
- Parallel Run بیشتر از یک؛
- Global Rate Limit و Adaptive Concurrency.

این موارد متعلق به Levelهای بعدی‌اند. فعال‌کردن Parallel پیش از Coordinator همچنان با خطای روشن متوقف می‌شود.

## 10. Gate ورود به Level 2

Level 1 معیارهای Gate A را برآورده کرده است:

- Regression در تست‌های قبلی وجود ندارد؛
- Browser Contract عملیاتی است؛
- Selenium پشت Provider قرار گرفته است؛
- Batchها Engine-agnostic شده‌اند؛
- Fake Provider آماده Contract Test مشترک با Patchright است؛
- Compatibility Facade کامل است؛
- Parallel Runtime هنوز Fail-Closed است.

Level 2 می‌تواند `PatchrightProvider` را با همان Contract پیاده‌سازی کند، بدون تغییر ساختار Manifest، Resume، Validation و Batch Planning.
