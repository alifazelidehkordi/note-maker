# گزارش اجرای Level 2 — Patchright Browser Provider

> نسخه پروژه: **0.4.0**  
> تاریخ اجرا: **۲۰ تیر ۱۴۰۵ / ۱۰ ژوئیه ۲۰۲۶**  
> مبنای کار: خروجی تأییدشده Level 1 با Browser Contract و Compatibility Layer

## 1. نتیجه اجرایی

Level 2 با هدف افزودن یک موتور مرورگر جدید، بدون شکستن مسیر Selenium و بدون فعال‌سازی زودهنگام Parallelism، پیاده‌سازی شد.

خروجی این Level شامل یک `PatchrightProvider` عملیاتی است که از **Persistent Browser Context**، Profile مستقل، Selector Registry مرکزی، State Machine پاسخ، Upload مبتنی بر DOM، Send Guard، دانلود Event-first، بازیابی محدودشده و خطاهای Type شده استفاده می‌کند.

رفتار پیش‌فرض پروژه همچنان:

```text
browser-provider = selenium
parallel-runs    = 1
```

است. Patchright فقط با انتخاب صریح کاربر فعال می‌شود:

```bash
python scripts/batch_pdf.py \
  --browser-provider patchright \
  --parallel-runs 1
```

مقادیر بیشتر از یک برای `--parallel-runs` همچنان Fail-Closed هستند؛ زیرا Coordinator، Profile Manager چندورکری و Single-writer Manifest هنوز وارد مسیر اجرایی نشده‌اند.

---

## 2. معماری نهایی این Level

```text
Batch PDF / Batch Markdown / Pipeline
                    │
                    ▼
             BrowserProvider
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
 SeleniumProvider      PatchrightProvider
          │                   │
          ▼                   ▼
 SeleniumSession      Persistent Context
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
        Selector Registry  State Machine  Download Resolver
                                            │
                              Event-first ──┴── Filesystem fallback
```

Batchها فقط با قرارداد سطح‌بالای `BrowserSession` کار می‌کنند و هیچ Locator خام Patchright یا Selenium در Orchestration وارد نشده است.

---

## 3. اجزای پیاده‌سازی‌شده

### 3.1. Patchright Provider و Persistent Context

فایل جدید:

```text
scripts/browser_runtime/patchright_provider.py
```

قابلیت‌های اصلی:

- بارگذاری Lazy وابستگی Patchright؛ اجرای Selenium به Import یا Start شدن Patchright وابسته نیست.
- اجرای Chromium با Persistent Context و Profile قابل نگه‌داری.
- Profile و Download Directory مستقل و قابل تنظیم.
- تشخیص خودکار Chrome یا Chromium نصب‌شده روی سیستم.
- امکان تعیین Binary با متغیر `CHATGPT_CHROME_BINARY`.
- اعمال لایه Stealth به‌صورت Best-effort؛ شکست Stealth باعث ازکارافتادن Provider نمی‌شود.
- حفظ Page، Context و Playwright lifecycle در یک Session مشخص.
- پشتیبانی از Headless و Headful.

مسیر Profile پیش‌فرض Patchright:

```text
patchright_profile/
```

متغیرهای محیطی مرتبط:

```text
CHATGPT_PATCHRIGHT_PROFILE_DIR
CHATGPT_DOWNLOAD_DIR
CHATGPT_CHROME_BINARY
```

### 3.2. Selector Registry مرکزی

فایل جدید:

```text
scripts/browser_runtime/selectors.py
```

Selectorها و Phraseهای حساس UI از Provider جدا شده‌اند، از جمله:

- Composer و Send Button
- Stop Generation
- File Input و Attach Button
- Assistant Messages
- Model Switcher
- Upload Progress و Upload Error
- Login و Cookie Banner
- Cloudflare Challenge
- Rate Limit
- Network Error Markerها
- Download Candidateها

این جداسازی باعث می‌شود تغییر UI در یک نقطه اصلاح شود و منطق Provider پراکنده نشود.

### 3.3. State Machine نشست و پاسخ

فایل جدید:

```text
scripts/browser_runtime/state_machine.py
```

Stateهای نشست شامل موارد زیر است:

```text
CREATED
NAVIGATING
AUTH_REQUIRED
READY
UPLOADING
SENDING
GENERATING
DOWNLOADING
FAILED
CLOSED
```

Stateهای پاسخ:

```text
WAITING
GENERATING
RATE_LIMITED
DOWNLOAD_READY
STABLE
```

تصمیم پایان پاسخ فقط به یک Selector متکی نیست. ماشین حالت، تعداد پیام‌های Assistant، وضعیت Generation، Rate Limit، وجود Download Candidate و ثبات زمانی پاسخ را کنار هم ارزیابی می‌کند.

### 3.4. Login، Cloudflare و Network Recovery

Provider اکنون می‌تواند این وضعیت‌ها را از هم تفکیک کند:

- Login لازم است.
- Cloudflare یا Human Verification فعال است.
- شبکه واقعاً قطع یا DNS ناموفق است.
- Page قابل دسترس است ولی در State مورد انتظار نیست.
- Browser، Context یا Page بسته شده است.

Navigation دارای Retry محدودشده است و خطاهای Network یا Browser Crash به خطاهای عمومی UI تبدیل نمی‌شوند.

در Headless mode، اگر Login لازم باشد، Provider با `AuthenticationRequiredError` متوقف می‌شود و به‌صورت مبهم Timeout نمی‌دهد.

### 3.5. Upload مبتنی بر DOM

Upload ابتدا از `input[type=file]` استفاده می‌کند و وابستگی به تعاملات Desktop را از مسیر اصلی Patchright حذف می‌کند.

پس از انتخاب فایل، Provider موارد زیر را کنترل می‌کند:

- وجود فایل ورودی
- پایان Progress یا Processing
- نمایش خطای Upload
- Timeout عملیات

خطاها با Taxonomy مشخص `BrowserUploadError` یا `UploadError` برگردانده می‌شوند.

### 3.6. Send Guard و جلوگیری از ارسال تکراری

برای هر Prompt یک Hash نگه‌داری می‌شود. Session همچنین این موارد را ثبت می‌کند:

- تعداد پیام Assistant پیش از ارسال
- زمان شروع Send
- دریافت یا عدم دریافت Acknowledgement
- مشاهده Generation یا پیام جدید

دو حالت محافظت می‌شوند:

1. اگر ارسال قبلی تأیید شده باشد، Retry همان Prompt کلیک دوم انجام نمی‌دهد.
2. اگر کلیک قبلی انجام شده ولی تأیید آن نامشخص باشد، ارسال مجدد تا Window محافظتی متوقف می‌شود و `BrowserSendError` روشن برمی‌گردد.

این رفتار مانع تولید دو پاسخ یا دو Artifact برای یک Attempt می‌شود.

### 3.7. Rate Limit و Retry Cooldown

`RateLimitError` دارای `retry_after` است. Orchestrator مقدار پیشنهادی Provider را در Retry رعایت می‌کند:

```text
retry_wait = max(default_retry_delay, provider_retry_after)
```

بنابراین Rate Limit دیگر بلافاصله با Retry کوتاه و تکراری تشدید نمی‌شود.

### 3.8. Response Waiting و Long Generation

`wait_for_response` موارد زیر را کنترل می‌کند:

- شروع Generation
- Stop Button
- افزایش تعداد پیام Assistant
- ثبات پاسخ
- Download Candidate
- Rate Limit
- Timeout
- Generation طولانی یا Stalled

در Generation طولانی، سیاست Stop-and-grace محدودشده وجود دارد تا Session بی‌نهایت در حالت Generating باقی نماند.

### 3.9. دانلود Event-first و Job-specific Staging

فایل‌های جدید/اصلاح‌شده:

```text
scripts/browser_runtime/downloads.py
scripts/browser_runtime/models.py
```

ترتیب دریافت Artifact:

1. Candidateهای پیام آخر Assistant پیدا و Score می‌شوند.
2. فقط Candidate مرتبط با Extension مورد انتظار پذیرفته می‌شود.
3. `expect_download` قبل از Click ثبت می‌شود.
4. فایل مستقیماً در Staging مخصوص Job ذخیره می‌شود.
5. Artifact با Validator فعلی بررسی می‌شود.
6. فقط در صورت شکست Event path، Filesystem Salvage محدودشده اجرا می‌شود.

ساختار نمونه Staging:

```text
downloads/
└── jobs/
    └── section_01/
        └── generated.md
```

قواعد ایمنی:

- کنترل Snapshot پیش از Prompt
- کنترل `started_at_ns`
- رد فایل‌های قدیمی و بدون تغییر
- رد `.crdownload`، `.part`، `.tmp` و فایل‌های ناقص
- رد Trigger عمومی مانند «Download» بدون اشاره معتبر به فرمت مورد انتظار
- بررسی محتوایی Markdown و OPML، نه فقط پسوند فایل

### 3.10. Health Check و Recovery

قرارداد `BrowserSession` با دو Capability تکمیل شد:

```python
health() -> BrowserHealth
recover(reason: str = "") -> bool
```

Health Statusها:

```text
HEALTHY
DEGRADED
DEAD
```

Patchright Recovery در سطح Page انجام می‌شود و از ساخت Session موازی یا Profile اشتراکی پنهان خودداری می‌کند.

### 3.11. CLI و Factory

Factory اکنون دو Provider معتبر دارد:

```text
selenium
patchright
```

گزینه زیر در PDF، Markdown و Pipeline پذیرفته می‌شود:

```bash
--browser-provider patchright
```

گزینه زیر همچنان فقط مقدار یک را می‌پذیرد:

```bash
--parallel-runs 1
```

درخواست مقدار دو یا بیشتر با پیام روشن متوقف می‌شود؛ اجرای Parallel ناقص یا Silent Fallback وجود ندارد.

### 3.12. Setup و Dependency Pinning

`requirements.txt` شامل نسخه‌های Pin شده است:

```text
patchright==1.61.2
playwright-stealth==2.0.3
```

رفتار Setup:

1. وابستگی‌های Python نصب می‌شوند.
2. اگر Chrome/Chromium سیستمی موجود باشد، همان Binary استفاده می‌شود.
3. فقط اگر Browser سیستمی پیدا نشود، نصب Chromium اختصاصی Patchright درخواست می‌شود.
4. با `SKIP_PATCHRIGHT_BROWSER_INSTALL=1` می‌توان نصب Binary را صریحاً رد کرد.

---

## 4. Taxonomy خطاهای جدید

خطاهای Provider به Typeهای زیر نگاشت می‌شوند:

| Type | کاربرد |
|---|---|
| `AuthenticationRequiredError` | Login کاربر لازم است |
| `CloudflareChallengeError` | Challenge در بازه مجاز رفع نشده است |
| `NetworkUnavailableError` | شبکه یا DNS پس از Recovery محدود همچنان نامعتبر است |
| `PageStateError` | Page باز است ولی State مورد نیاز فراهم نیست |
| `UploadError` | Upload کامل نشده یا خطای UI گزارش شده است |
| `SendError` / `BrowserSendError` | Prompt با اطمینان ارسال نشده است |
| `RateLimitError` | محدودیت سرویس با Cooldown پیشنهادی |
| `ResponseTimeoutError` | پاسخ در Timeout پایدار نشده است |
| `GenerationStalledError` | Generation از سیاست زمانی عبور کرده است |
| `DownloadNotFoundError` | Artifact تازه و معتبر پیدا نشده است |
| `BrowserCrashedError` | Browser، Context یا Page از بین رفته است |

---

## 5. فایل‌های اصلی اضافه‌شده

```text
scripts/browser_runtime/patchright_provider.py
scripts/browser_runtime/selectors.py
scripts/browser_runtime/state_machine.py
scripts/browser_runtime/downloads.py
scripts/smoke_test_patchright.py

tests/test_patchright_provider.py
tests/test_patchright_downloads.py
tests/test_browser_response_state_machine.py

docs/level2-results/
implementation-report-level2-fa.md
```

فایل‌های کلیدی اصلاح‌شده:

```text
scripts/browser_runtime/contracts.py
scripts/browser_runtime/models.py
scripts/browser_runtime/errors.py
scripts/browser_runtime/factory.py
scripts/browser_runtime/selenium_provider.py
scripts/browser_runtime/__init__.py
scripts/batch_common.py
scripts/batch_pdf.py
scripts/batch_markdown.py
scripts/runtime_flags.py
scripts/pipeline.py
requirements.txt
setup.sh
setup.cmd
README.md
CHANGELOG.md
RELEASE_CHECKLIST.md
VERSION
package.json
```

---

## 6. نتایج اعتبارسنجی

### 6.1. Unit و Integration Tests

```text
Ran 111 tests
OK
```

پوشش جدید شامل:

- Patchright Session Contract
- Health و Recovery
- Error Translation
- Response State Machine
- Event-first Download
- Job-specific Staging
- Filesystem Salvage
- Freshness و Candidate Scoring
- Artifact Validator Integration
- Send Deduplication پس از Acknowledgement
- جلوگیری از Click دوم در Send نامطمئن
- رعایت `retry_after` در Rate Limit
- Opt-in Provider و Default Preservation
- Fail-closed Parallelism

گزارش کامل:

```text
docs/level2-results/unit-tests.txt
```

### 6.2. Acceptance

هر سه سناریوی Acceptance موفق شدند:

```text
[PASS] batch_failure_and_diagnostics
[PASS] retry_failed_and_resume
[PASS] pdf_book_end_to_end
```

گزارش JSON دارای مقادیر زیر است:

```json
{
  "version": "0.4.0",
  "passed": true
}
```

مسیرها:

```text
docs/level2-results/acceptance.txt
docs/level2-results/acceptance.json
```

### 6.3. Compile Check

```bash
python -m compileall -q scripts tests
```

بدون خطا اجرا شد.

### 6.4. Smoke واقعی Patchright

Smoke واقعی Headless با Persistent Context اجرا شد:

```text
browser=/usr/bin/chromium
provider=patchright
health=healthy
title=Patchright Smoke
basic navigation succeeded
```

این تست موارد زیر را عملاً تأیید کرد:

- Import و راه‌اندازی واقعی Patchright
- Persistent Context
- استفاده از Chromium سیستمی
- ساخت Profile و Download Directory مستقل
- Page navigation
- Health Check
- Screenshot
- Close lifecycle

گزارش:

```text
docs/level2-results/patchright-basic-smoke.txt
```

### 6.5. وضعیت نصب Browser Binary

تلاش برای دریافت Chromium اختصاصی Patchright از CDN در محیط اجرا به خطای DNS رسید. این شکست در گزارش زیر ثبت شده است:

```text
docs/level2-results/patchright-browser-install.txt
```

این مورد Provider را متوقف نکرد؛ Auto-detection مرورگر سیستمی `/usr/bin/chromium` فعال شد و Smoke واقعی با موفقیت عبور کرد.

---

## 7. مواردی که عمداً اجرا نشدند

### 7.1. Smoke کامل ChatGPT

مسیر کامل زیر در این محیط اجرا نشد:

```text
Login واقعی → Upload واقعی → Send واقعی → Generation → Download واقعی
```

علت: این تست به Account و Persistent Profile لاگین‌شده متعلق به کاربر نیاز دارد. هیچ Credential یا Session مصنوعی ساخته یا وارد بسته نشده است.

فرمان آماده اجرای دستی:

```bash
.venv-linux/bin/python scripts/smoke_test_patchright.py \
  --chatgpt \
  --input inputs/sample.pdf \
  --prompt prompts/prompt-rewrite-notes.md \
  --expected-extension .md
```

برای اولین Login بهتر است Headful اجرا شود تا Session در `patchright_profile/` ذخیره شود.

### 7.2. Parallel Execution

Parallel واقعی در این Level فعال نشده است. دلیل فنی:

- Profile Manager چندورکری هنوز پیاده نشده است.
- Coordinator و Dynamic Job Queue هنوز مالک Lifecycle نیستند.
- Manifest هنوز باید در فاز Parallel به Single-writer تبدیل شود.
- Download و Diagnostics باید برای هر Worker Namespace قطعی داشته باشند.

فعال‌سازی Parallel در این نقطه می‌توانست Race Condition ایجاد کند؛ بنابراین Fail-closed بودن، بخشی از Definition of Done این Level است.

---

## 8. سازگاری عقب‌رو

موارد زیر بدون Regression باقی ماندند:

- Selenium به‌عنوان Provider پیش‌فرض
- Compatibility Facade سطح Level 1
- APIهای عمومی Baseline
- Manifest و Resume
- Retry و `--retry-failed`
- Validation و Atomic Save
- Diagnostics
- PDF generation و Combined Book
- CLIهای فعلی

Patchright به‌صورت Opt-in اضافه شده و هیچ Migration اجباری برای کاربران Selenium رخ نداده است.

---

## 9. Gate ورود به Level بعدی

Level 2 برای ورود به Level 3 آماده است، زیرا:

- Browser Contract پایدار است.
- دو Provider از یک Interface استفاده می‌کنند.
- Patchright Persistent Context واقعی راه‌اندازی شده است.
- Profile path و Download path قابل تزریق‌اند.
- Health و Recovery قرارداد مشخص دارند.
- خطاها Type شده‌اند.
- Download به Job Key مجهز شده است.
- تست‌ها بدون Browser و با Browser واقعی وجود دارند.

Level بعدی باید **Profile Manager و Session Bootstrap** را پیاده کند، از جمله:

- Profile template و Clone امن برای هر Worker
- Lock و Ownership Profile
- Warm-up و Login bootstrap
- Validation نشست پیش از دریافت Job
- Cleanup و Retention Policy
- جلوگیری از اشتراک Profile بین Processها

پس از آن، Coordinator و Parallel Scheduler می‌توانند بدون به‌اشتراک‌گذاری Browser State ساخته شوند.

---

## 10. خلاصه تحویل

| مورد | نتیجه |
|---|---|
| نسخه | `0.4.0` |
| Provider پیش‌فرض | Selenium |
| Provider جدید | Patchright، Opt-in |
| Persistent Context | پیاده‌سازی و Smoke شده |
| Upload DOM-first | پیاده‌سازی شده |
| Send Guard | پیاده‌سازی و تست شده |
| Response State Machine | پیاده‌سازی و تست شده |
| Download Event-first | پیاده‌سازی و تست شده |
| Typed Errors | پیاده‌سازی شده |
| Health/Recovery | پیاده‌سازی شده |
| Unit/Integration | **111/111 موفق** |
| Acceptance | **3/3 موفق** |
| Compileall | موفق |
| Basic real-browser smoke | موفق با `/usr/bin/chromium` |
| Full ChatGPT smoke | اجرا نشده؛ نیازمند Profile واقعی کاربر |
| Parallel > 1 | عمداً Fail-Closed |

