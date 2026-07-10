# گزارش اجرای فاز ۶ — Resilience، Rate Limit و Adaptive Control

**پروژه:** Note Maker  
**نسخه خروجی:** `0.8.0`  
**تاریخ اجرا:** 10 July 2026  
**وضعیت:** پیاده‌سازی کامل؛ Gateهای خودکار، Acceptance و Smoke مرورگر موفق

---

## ۱. هدف فاز

فاز ۵ اجرای واقعی چند Worker را فعال کرد. هدف فاز ۶ این بود که همان Runtime در برابر محدودیت‌ها و خرابی‌های رایج ChatGPT Web رفتار کنترل‌شده و قابل‌بازیابی داشته باشد؛ به‌خصوص:

1. Rate Limit یک Worker باعث هجوم Workerهای دیگر نشود؛
2. خطای موقت شبکه کل Batch را متوقف نکند؛
3. Session نامعتبر چند Login Window هم‌زمان نسازد؛
4. Retryها سقف روشن و دسته‌بندی مستقل داشته باشند؛
5. تعداد Worker فعال در فشار Rate Limit قابل کاهش و بازیابی باشد؛
6. Workerهای طولانی‌عمر یا پرمصرف بدون از دست‌رفتن خروجی Recycle شوند؛
7. Browser Process باقی‌مانده و Claim قدیمی Runtime بعدی را قفل نکند.

---

## ۲. معماری نهایی

```text
ExecutionJob
    │
    ▼
ParallelCoordinator ─────────────── writable ManifestCoordinator
    │
    ├── GlobalRuntimeController
    │     ├── Global Rate-limit Cooldown
    │     ├── Authentication Circuit
    │     ├── Severe Rate-limit Circuit
    │     └── Adaptive Active-worker Limit
    │
    ├── ClaimStore / Stale Recovery
    ├── Worker Lifecycle / Recycling
    └── Process-tree Hygiene
             │
             ├── Worker 1 ── RetryTracker ── Browser Session
             ├── Worker 2 ── RetryTracker ── Browser Session
             └── Worker N ── RetryTracker ── Browser Session
```

### مرز مالکیت

- Coordinator تنها مالک State سراسری و Writer Manifest است؛
- Worker فقط Retry محلی انجام می‌دهد و Event نوع‌دار می‌فرستد؛
- Worker به Manifest قابل‌نوشتن دسترسی ندارد؛
- Cooldown یا Adaptive Limit از داخل Worker تغییر نمی‌کند؛
- Process Cleanup پیش از آزادکردن Claim تکمیل می‌شود.

---

## ۳. Global Rate Limit Controller

فایل جدید:

```text
scripts/parallel_runtime/resilience.py
```

`GlobalRuntimeController` وضعیت زیر را در Process Coordinator نگه می‌دارد:

```text
requested_limit
active_limit
minimum_active_limit
cooldown_until
rate_limit_events
auth_failures
adaptive_scale_downs
adaptive_scale_ups
circuit_open_reason
```

هنگامی که Worker یک Event از نوع Rate Limit منتشر می‌کند:

1. `retry_after` در صورت وجود خوانده می‌شود؛
2. Cooldown سراسری حداقل به مقدار تنظیم‌شده جلو می‌رود؛
3. تخصیص Job جدید به تمام Workerها متوقف می‌شود؛
4. Jobهای در حال اجرا بدون ضرورت قطع نمی‌شوند؛
5. Event برای Adaptive Control و Circuit Breaker ثبت می‌شود؛
6. پس از پایان Cooldown، Dispatch از همان صف Resume می‌شود.

مقدار ثبت‌شده در Summary، افزایش یکتای Cooldown درخواست‌شده است؛ Eventهای هم‌پوشان یک بازه را چند بار محاسبه نمی‌کنند.

### Policy پیش‌فرض

```text
global_rate_limit_cooldown = 180s
rate_limit_failures_before_abort = 6
rate_limit_window_seconds = 300s
```

مقدار صفر برای `rate_limit_failures_before_abort`، Circuit شدید Rate Limit را غیرفعال می‌کند.

---

## ۴. Retry Budgetهای مستقل

کلاس‌های جدید:

```text
FailureCategory
RetryBudgetPolicy
RetryTracker
RetryDecision
```

خطاها در دسته‌های پایدار زیر قرار می‌گیرند:

```text
content
network
browser
download
rate_limit
auth
unknown
```

### سقف‌های پیش‌فرض

| دسته | مقدار | معنا |
|---|---:|---|
| Content | 3 | تعداد Attempt کل برای خطای پاسخ/محتوا |
| Network | 4 | تعداد Retry شبکه |
| Browser | 3 | تعداد Retry Startup/Crash/Profile |
| Download | 2 | تعداد Retry دانلود |
| Rate Limit | 2 | تعداد Retry محلی Rate Limit |
| Auth | 0 | بدون Retry محلی |

یک خطای شبکه دیگر بودجه Content یا Browser را مصرف نمی‌کند. شمارنده‌ها در نتیجه Worker و Summary Coordinator ثبت می‌شوند.

### Backoff و Jitter

برای Network، Browser، Download و Rate Limit:

```text
base = 3s
sequence = 3, 6, 12, 24 ...
cap = 24s
jitter = ±20%
```

Jitter با Seed مربوط به Job و Attempt به‌صورت Deterministic ساخته می‌شود؛ بنابراین هم از بیدارشدن هم‌زمان Workerها جلوگیری می‌کند و هم تست‌ها تکرارپذیر باقی می‌مانند. برای Rate Limit، مقدار `retry_after` Provider بر Backoff محاسبه‌شده اولویت دارد.

Auth Failure هرگز وارد Loop Retry محلی نمی‌شود و مستقیم به کنترل سراسری ارتقا می‌یابد.

---

## ۵. Authentication Circuit و Startup Barrier

Coordinator در شروع Run ابتدا فقط یک Worker را ایجاد می‌کند. Workerهای باقی‌مانده پس از دریافت `WORKER_READY` از Worker اول ساخته می‌شوند.

این Barrier باعث می‌شود Profile منقضی یا حساب Logout‌شده چند صفحه Login هم‌زمان باز نکند.

اگر Auth Failure رخ دهد:

1. Event نوع‌دار `AUTH_FAILURE` ثبت می‌شود؛
2. شمارنده سراسری افزایش می‌یابد؛
3. Dispatch جدید متوقف می‌شود؛
4. پس از رسیدن به Threshold، Circuit باز می‌شود؛
5. Jobهای تکمیل‌شده دست‌نخورده باقی می‌مانند؛
6. Jobهای ناتمام برای Resume حفظ می‌شوند.

Policy پیش‌فرض:

```text
auth_failures_before_abort = 2
```

---

## ۶. Adaptive Concurrency

Adaptive Concurrency پشت Feature Flag زیر قرار دارد و پیش‌فرض خاموش است:

```bash
--adaptive-concurrency
```

رفتار:

1. Rate Limit Eventها در Window زمانی ثبت می‌شوند؛
2. پس از `adaptive_scale_down_threshold`، ظرفیت Dispatch یک واحد کم می‌شود؛
3. Worker سالم و Job در حال اجرا Kill نمی‌شود؛
4. فقط تعداد Slotهای مجاز برای Assignment جدید کاهش می‌یابد؛
5. پس از `adaptive_recovery_seconds` سکوت، یک Slot بازیابی می‌شود؛
6. بازیابی تا سقف `parallel-runs` ادامه پیدا می‌کند.

Defaults:

```text
adaptive_scale_down_threshold = 2
adaptive_recovery_seconds = 900s
```

Summary شامل کمترین و آخرین ظرفیت فعال و تعداد Scale-down/Scale-up است.

---

## ۷. Worker Recycling

دو Trigger مستقل اضافه شد:

```text
worker_max_jobs
worker_memory_limit_mb
```

Defaults:

```text
worker_max_jobs = 20
worker_memory_limit_mb = 0  # disabled
```

Recycle فقط پس از پایان موفق یا نهایی Job انجام می‌شود؛ بنابراین Artifact تکمیل‌شده دوباره اجرا نمی‌شود. Worker جایگزین Generation جدید می‌گیرد:

```text
worker-001
worker-001-g002
worker-001-g003
```

این Generation Profile و Runtime مجزا دارد و به Lock یا Memory State Worker قبلی وابسته نیست.

Memory Trigger، RSS کل Process Tree Worker را می‌سنجد تا مصرف Chromium Child Processها نیز دیده شود.

---

## ۸. Zombie Process و Runtime Cleanup

فایل جدید:

```text
scripts/parallel_runtime/process_hygiene.py
```

قابلیت‌ها:

- کشف Child Processها از `/proc` در Linux؛
- محاسبه RSS Parent و Descendantها؛
- ثبت PIDهای شناخته‌شده پیش از توقف Worker؛
- ارسال `SIGTERM` به Childهای باقی‌مانده؛
- ارتقا به `SIGKILL` پس از Grace؛
- نگه‌داشتن Claim تا پایان Process Cleanup؛
- گزارش تعداد Childهای نیازمند Force Cleanup.

این مسیر به Claim Safety فاز ۵ متصل است و مالکیت Job پیش از مرگ قطعی Process آزاد نمی‌شود.

---

## ۹. Stale Claim Recovery

`ClaimStore` با دو عملیات تکمیل شد:

```text
recover_stale()
release_run(run_id)
```

Coordinator هنگام Startup، Claimهای قابل‌بازیابی را طبق قواعد قبلی PID/Host/Token پاک می‌کند و تعداد آن‌ها را در Summary ثبت می‌کند. در Shutdown نیز Claimهای متعلق به Run پس از توقف Workerها آزاد می‌شوند.

Claim فعال متعلق به Process زنده یا Host دیگر همچنان Fail-Closed باقی می‌ماند.

---

## ۱۰. Eventهای جدید

به Event Bus اضافه شد:

```text
RETRY_SCHEDULED
GLOBAL_COOLDOWN_REQUESTED
AUTH_FAILURE
```

Payload Retry شامل دسته، شمارنده، سقف و Delay است. Coordinator از Eventها برای State سراسری استفاده می‌کند؛ Worker هیچ Reference مستقیم به `GlobalRuntimeController` ندارد.

---

## ۱۱. CLIهای جدید

گزینه‌های زیر در PDF، Markdown و Pipeline یکسان اضافه و Forward شدند:

```text
--global-rate-limit-cooldown SECONDS
--auth-failures-before-abort N
--rate-limit-failures-before-abort N
--rate-limit-window-seconds SECONDS
--adaptive-concurrency
--adaptive-scale-down-threshold N
--adaptive-recovery-seconds SECONDS
--worker-max-jobs N
--worker-memory-limit-mb MB
--network-retries N
--browser-retries N
--download-retries N
--rate-limit-retries N
--retry-backoff-base SECONDS
--retry-backoff-cap SECONDS
--retry-jitter-ratio RATIO
```

Validationها شامل مقادیر منفی، Window نامعتبر، Threshold کمتر از یک و Jitter خارج از بازه صفر تا یک هستند.

---

## ۱۲. Summary و Metrics

خروجی PDF و Markdown اکنون موارد زیر را نیز ثبت می‌کند:

```text
retry_counts
rate_limit_events
auth_failures
global_cooldown_seconds
worker_recycles
zombie_processes_cleaned
stale_claims_recovered
minimum_active_workers
final_active_workers
adaptive_scale_downs
adaptive_scale_ups
circuit_breaker_reason
```

Run Summary همچنان زیر مسیر زیر پایدار می‌ماند:

```text
logs/runs/<run-id>/summary.json
```

---

## ۱۳. تست‌ها و معیار پذیرش

### Regression

```text
169 / 169 tests passed
```

این مجموعه تمام تست‌های فازهای قبلی را نیز شامل می‌شود.

### Acceptance اختصاصی فاز ۶

```text
11 / 11 tests passed
```

سناریوهای پوشش‌داده‌شده:

1. Rate Limit مصنوعی، Assignment جدید را سراسری Pause می‌کند؛
2. Network Failure موقت در بودجه محدود بازیابی می‌شود؛
3. Auth Failure در Startup فقط یک Worker/Login Flow ایجاد می‌کند؛
4. Adaptive Limit کاهش و پس از Quiet Period بازیابی می‌شود؛
5. Worker Recycling خروجی و Resume State را خراب نمی‌کند؛
6. Retry از سقف دسته عبور نمی‌کند؛
7. Process Child باقی‌مانده پاک می‌شود؛
8. Claim Stale به‌صورت ایمن بازیابی می‌شود.

### Acceptance پایدار قبلی

هر سه سناریو موفق‌اند:

- Partial failure و Diagnostics؛
- Retry-failed و Browser-free Resume؛
- PDF Book end-to-end.

### Compile و Browser Smoke

- `python -m compileall -q scripts tests`: موفق؛
- Patchright Persistent Context واقعی با `/usr/bin/chromium`: موفق؛
- Health: `healthy`؛
- Navigation، DOM، Title و Screenshot: موفق.

---

## ۱۴. فایل‌های کلیدی تغییرکرده

```text
scripts/parallel_runtime/resilience.py
scripts/parallel_runtime/process_hygiene.py
scripts/parallel_runtime/coordinator.py
scripts/parallel_runtime/worker.py
scripts/parallel_runtime/executors.py
scripts/parallel_runtime/event_bus.py
scripts/parallel_runtime/claims.py
scripts/parallel_runtime/models.py
scripts/parallel_runtime/testing.py
scripts/runtime_flags.py
scripts/batch_common.py
scripts/batch_pdf.py
scripts/batch_markdown.py
scripts/pipeline.py
scripts/level6_acceptance.py
tests/test_resilience_control.py
tests/test_level6_coordinator.py
tests/test_process_hygiene.py
tests/test_runtime_flags.py
```

---

## ۱۵. محدودیت‌های صادقانه

تست End-to-End کامل زیر در این محیط اجرا نشد:

```text
چند Worker واقعی
→ Profile خصوصی و Login‌شده ChatGPT
→ Upload واقعی
→ Rate Limit واقعی حساب
→ Download واقعی Artifact
```

این سناریو به Account و Snapshot خصوصی کاربر نیاز دارد. هیچ Cookie، Credential، Profile یا Session خصوصی در بسته تحویل قرار نگرفته است.

Adaptive Concurrency نیز عمداً پیش‌فرض خاموش است؛ مقدار مناسب Worker و Threshold باید با محدودیت حساب واقعی و Latency عملیاتی تنظیم شود.

Process-tree cleanup بر Linux با `/proc` قابل مشاهده و تست شده است. روی سیستم‌هایی بدون `/proc`، منطق اصلی Worker Termination باقی می‌ماند اما Telemetry و Cleanup فرزندان به قابلیت‌های سیستم‌عامل محدود است.

---

## ۱۶. نتیجه

فاز ۶ Runtime موازی فاز ۵ را از یک موتور صرفاً هم‌زمان به یک Runtime دارای کنترل فشار و بازیابی Production نزدیک کرد:

- یک Rate Limit، کل Pool را هماهنگ می‌کند؛
- خطاهای موقت بودجه مستقل و محدود دارند؛
- Auth Failure چند Window هم‌زمان ایجاد نمی‌کند؛
- Concurrency در صورت انتخاب کاربر Adaptive می‌شود؛
- Worker طولانی‌عمر بدون از دست‌دادن Job Recycle می‌شود؛
- Child Process و Claim باقی‌مانده پاک‌سازی می‌شوند؛
- تمام رفتارهای پیشین Resume، Manifest، Claim و Parallel حفظ شده‌اند.

فاز بعدی طبق برنامه، **Observability و Diagnostics موازی** است: Event Journal پایدار، Logهای ساختاریافته Coordinator/Worker، Dashboard Summary و Correlation کامل Run/Worker/Job/Attempt.
