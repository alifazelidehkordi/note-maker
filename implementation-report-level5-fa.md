# گزارش اجرای فاز ۵ — Parallel Coordinator و Worker Runtime

**پروژه:** Note Maker  
**نسخه خروجی:** `0.7.0`  
**تاریخ اجرا:** 10 July 2026  
**وضعیت:** پیاده‌سازی کامل و فعال؛ اجرای واقعی N Worker در سطح Runtime و Fake Provider تأیید شده است

---

## ۱. هدف فاز

هدف این فاز فعال‌کردن اجرای واقعی و قابل تنظیم چند Worker بود، بدون بازگشت به مدل شکننده «تقسیم دستی بازه فایل‌ها بین چند اسکریپت». معماری جدید باید ویژگی‌های زیر را فراهم می‌کرد:

1. یک Coordinator واحد برای Planning، Dispatch، Manifest و Shutdown؛
2. Workerهای مستقل در Processهای جدا با Browser Session طولانی‌عمر؛
3. صف پویا به‌جای تقسیم ثابت Jobها؛
4. جلوگیری از اجرای تکراری Job میان دو Run مستقل؛
5. تشخیص Crash یا Freeze Worker و بازیابی خودکار؛
6. Resume امن پس از توقف عادی یا Kill اجباری؛
7. یک مسیر Runtime مشترک برای یک Worker و چند Worker.

این فاز `--parallel-runs` را برای مقادیر `1` تا `16` فعال می‌کند. کنترل سراسری Rate Limit و Adaptive Concurrency عمداً به فاز ۶ موکول شده‌اند.

---

## ۲. معماری اجراشده

```text
Planner
   │ ExecutionJob[]
   ▼
ParallelCoordinator ──────── writable ManifestCoordinator
   │     │
   │     ├── shared Event Queue ◀── Worker Events / Heartbeats
   │     ├── Claim Store
   │     └── per-worker Command Queue
   │
   ├── Worker Process 1 ── Browser Session 1 ── isolated profile/downloads
   ├── Worker Process 2 ── Browser Session 2 ── isolated profile/downloads
   └── Worker Process N ── Browser Session N ── isolated profile/downloads
```

اصل مالکیت:

- Coordinator تنها Writer Manifest است؛
- Worker فقط Command دریافت و Event تولید می‌کند؛
- هر Worker دقیقاً یک Browser Session طولانی‌عمر دارد؛
- هر Job پیش از Dispatch یک Claim اتمیک می‌گیرد؛
- Worker بعد از اتمام Job، Job بعدی را Request می‌کند.

---

## ۳. اجزای جدید Parallel Runtime

ساختار `scripts/parallel_runtime` توسعه یافت:

```text
parallel_runtime/
├── models.py
├── planner.py
├── job_sources.py
├── event_bus.py
├── claims.py
├── coordinator.py
├── worker.py
├── executors.py
└── testing.py
```

### ۳.۱ `RunConfig`

`RunConfig` تمام تنظیمات مورد نیاز Child Process را به Payload سریال‌پذیر تبدیل می‌کند:

```text
run_id
manifest_path
claims_dir
worker_count
executor_path
executor_config
heartbeat_interval
worker_timeout
startup_stagger
max_worker_restarts
shutdown_grace
claim_stale_after
poll_interval
external_claim_wait
```

هیچ Browser Object، Lock غیرقابل Pickle یا Manifest Writer وارد Payload نمی‌شود.

### ۳.۲ Process Model

Workerها با Context زیر ساخته می‌شوند:

```python
multiprocessing.get_context("spawn")
```

این تصمیم از انتقال ناخواسته Browser Handle، Thread، Lock و Runtime داخلی Selenium/Patchright جلوگیری می‌کند و رفتار Linux و Windows را به هم نزدیک نگه می‌دارد.

### ۳.۳ Command Queue و Event Queue

هر Worker Command Queue اختصاصی دارد. همه Workerها یک Event Queue مشترک به Coordinator دارند.

Commandها:

```text
RUN_JOB
STOP
```

Eventهای Type‌شده:

```text
WORKER_READY
JOB_REQUESTED
JOB_STARTED
ATTEMPT_STARTED
HEARTBEAT
JOB_SUCCEEDED
JOB_FAILED
DIAGNOSTIC_SAVED
WORKER_FATAL
WORKER_STOPPED
```

Worker نتیجه را به‌صورت Payload ساده ارسال می‌کند و هیچ Mutation مستقیم Manifest انجام نمی‌دهد.

---

## ۴. صف پویا و Load Distribution

Jobها ابتدا بر اساس موارد زیر مرتب می‌شوند:

1. `estimated_weight` نزولی؛
2. `job.key` برای ترتیب Deterministic.

Worker پس از Ready شدن یا پایان Job، `JOB_REQUESTED` می‌فرستد. Coordinator همان لحظه Job بعدی قابل Claim را اختصاص می‌دهد. بنابراین:

- بازه فایل ثابت برای Worker وجود ندارد؛
- Worker سریع‌تر Job بیشتری می‌گیرد؛
- یک Job سنگین باعث Idle شدن کل Workerهای دیگر نمی‌شود؛
- تعداد Workerها بدون تغییر Job Planner قابل تنظیم است.

تست Jobهای با Duration متفاوت نشان داد Jobها بین Workerهای آزاد دوباره توزیع می‌شوند و همه Jobها دقیقاً یک‌بار تکمیل می‌شوند.

---

## ۵. Claim Store و جلوگیری از Duplicate

Claimها در پوشه مشترک وابسته به Manifest/Output ساخته می‌شوند:

```text
<manifest-parent>/.note-maker-claims/
```

ایجاد Claim با `O_CREAT | O_EXCL` انجام می‌شود. Payload Claim شامل موارد زیر است:

```text
job_key
run_id
worker_id
worker_pid
hostname
owner_token
claimed_at
heartbeat_at
```

### قواعد مالکیت

- فقط Owner Token فعلی می‌تواند Heartbeat یا Release انجام دهد؛
- Release تکراری Idempotent است؛
- Claim فعال متعلق به Run دیگر باعث Wait/Skip Dispatch می‌شود؛
- Claim Process مرده روی همان Host بعد از TTL قابل Reclaim است؛
- Job تکمیل‌شده توسط Run دیگر از Manifest تازه خوانده و به‌عنوان `externally_completed` ثبت می‌شود.

تست دو Coordinator مستقل روی Output مشترک تأیید کرد هیچ Job دوبار Execute نمی‌شود.

---

## ۶. Worker Lifecycle و Browser Ownership

Lifecycle عملیاتی:

```text
STARTING → READY → REQUESTING_JOB → RUNNING_JOB
              ▲                         │
              └─────────────────────────┘

Crash/Timeout → LOST → REQUEUE → RESTART → READY
Shutdown      → DRAINING/STOP → STOPPED
```

Executorهای واقعی:

```text
PdfJobExecutor
MarkdownJobExecutor
```

رفتار Executor:

- Provider داخل Child Process و به‌صورت Lazy ساخته می‌شود؛
- Browser Session برای چند Job همان Worker نگه داشته می‌شود؛
- Retry و Diagnostics قبلی حفظ شده‌اند؛
- Worker فقط نتیجه و Metadata را Event می‌کند؛
- بستن Browser و Runtime در پایان Worker انجام می‌شود.

Parent Process در مسیر Coordinator هیچ Provider یا Browser Session نمی‌سازد.

---

## ۷. Heartbeat، Crash Recovery و Restart

هر Worker یک Heartbeat Thread مستقل دارد. Coordinator زمان آخرین Heartbeat را در حافظه نگه می‌دارد و Claim را Refresh می‌کند.

تنظیمات پیش‌فرض:

```text
heartbeat_interval = 10s
worker_timeout = 45s
worker_ready_timeout = 180s
max_worker_restarts = 2
startup_stagger = 1s
```

Timeout شروع Worker از Timeout Heartbeat جدا است: تا پیش از `READY` مقدار `worker_ready_timeout` اعمال می‌شود و پس از Ready فقط سکوت Heartbeat با `worker_timeout` سنجیده می‌شود. این جداسازی مانع Kill اشتباه Workerهایی می‌شود که Spawn یا راه‌اندازی Browser آن‌ها کندتر است.

اگر Process Exit کند یا Heartbeat از Timeout عبور کند:

1. Worker Terminate می‌شود؛
2. در صورت نیاز Kill اجباری انجام می‌شود؛
3. Job جاری `interrupted` می‌شود؛
4. Claim آزاد می‌شود؛
5. Job به ابتدای صف برمی‌گردد؛
6. Worker جایگزین در محدوده Restart Budget ساخته می‌شود.

### Profile نسل‌دار

Worker جایگزین از Runtime ID جدید استفاده می‌کند:

```text
worker-001
worker-001-g002
worker-001-g003
```

این طراحی مانع آن می‌شود که Chromium باقی‌مانده یا Profile Lock مربوط به نسل Crash‌شده، Worker جایگزین را مسدود کند.

### Throttled Manifest Heartbeat

Heartbeat Process و Claim پرتکرار است، اما ثبت پایدار Manifest Throttle شده است. بنابراین هر Event به Disk Write تبدیل نمی‌شود و فشار I/O با تعداد Workerها خطی و بی‌حد رشد نمی‌کند.

---

## ۸. Single-writer Manifest و Merge معنایی

Workerها ماژول Writable Manifest را وارد نمی‌کنند. Coordinator Eventها را به Transitionهای زیر تبدیل می‌کند:

```text
mark_running
mark_heartbeat
mark_completed
mark_failed
mark_interrupted
```

دو Race مرزی اصلاح شدند:

1. اگر Coordinator دوم Manifest را پیش از تکمیل Job Load کرده باشد، Planning قدیمی آن دیگر نمی‌تواند Record معتبر `completed` روی Disk را با `pending` یا `interrupted` Downgrade کند؛ مشروط به اینکه هویت Job یکسان باشد و Artifact تکمیل‌شده معتبر باقی مانده باشد.
2. پس از گرفتن Claim و دقیقاً پیش از Dispatch، Manifest دوباره خوانده می‌شود. بنابراین اگر Run دیگر در فاصله «بررسی اولیه تا گرفتن Claim» Job را تکمیل کرده باشد، Run دوم آن را دوباره اجرا نمی‌کند.

این Merge معنایی علاوه بر Dirty-key Merge فاز ۴ عمل می‌کند.

Eventها علاوه بر `worker_id` منطقی، `runtime_worker_id` نسل‌دار دارند. Coordinator پیام Bufferشده از نسل قدیمی را نادیده می‌گیرد؛ بنابراین Heartbeat، Fatal یا Stop دیررس Worker Crash‌شده نمی‌تواند وضعیت Worker جایگزین را تغییر دهد.

---

## ۹. Shutdown و Resume

### Graceful Shutdown

در `SIGINT` یا `SIGTERM`:

1. Dispatch جدید متوقف می‌شود؛
2. Job جاری Resumeable و `interrupted` ثبت می‌شود؛
3. STOP برای Workerها ارسال می‌شود؛
4. تا `shutdown_grace` صبر می‌شود؛
5. Process باقی‌مانده Terminate می‌شود؛
6. اگر Process همچنان زنده باشد، Kill اجباری انجام می‌شود؛
7. فقط پس از مرگ قطعی Process، Claimهای متعلق به آن آزاد می‌شوند؛
8. Queueها بسته می‌شوند؛
9. Result با `interrupted=true` بازگردانده می‌شود.

Batch در این حالت Exit Code `130` می‌دهد.

### Forced Kill

تست POSIX کل Process Group شامل Coordinator و Worker را با `SIGKILL` متوقف کرد. پس از انقضای Claim، Run جدید Job را Reclaim و با موفقیت تکمیل کرد. در نتیجه Kill اجباری نیز به بن‌بست دائمی یا Duplicate منجر نمی‌شود.

---

## ۱۰. CLI و رفتار اجرایی

Flag اصلی:

```text
--parallel-runs N   # 1..16
```

Flagهای جدید:

```text
--worker-heartbeat-interval SECONDS
--worker-timeout SECONDS
--worker-ready-timeout SECONDS
--worker-startup-stagger SECONDS
--max-worker-restarts N
--shutdown-grace-seconds SECONDS
```

همه Flagها در مسیرهای زیر پشتیبانی و Forward می‌شوند:

```text
batch_pdf.py
batch_markdown.py
pipeline.py
```

نمونه:

```bash
./run_pdf_to_notes.sh \
  --browser-provider patchright \
  --profile-snapshot default \
  --parallel-runs 4 \
  --worker-heartbeat-interval 10 \
  --worker-timeout 45 \
  --worker-ready-timeout 180 \
  --worker-startup-stagger 1 \
  --max-worker-restarts 2 \
  --shutdown-grace-seconds 10
```

### مسیر مشترک تک‌ورکر

`parallel-runs=1` در اجرای معمول از همان Coordinator و Child Worker عبور می‌کند. تنها استثنا `--keep-browser` است که برای Workflow تعاملی قدیمی، مسیر In-process را حفظ می‌کند و با `parallel-runs>1` Fail-Closed است.

---

## ۱۱. Batch Summary

Summary هر Run اکنون علاوه بر اطلاعات قبلی شامل موارد زیر است:

```text
worker_assignments
worker_restarts
externally_completed
coordinator_duration_seconds
interrupted
```

Status نهایی Run می‌تواند یکی از موارد زیر باشد:

```text
completed
completed_with_failures
interrupted
```

---

## ۱۲. آزمون‌ها و Gateهای نهایی

### ۱۲.۱ مجموعه کامل

```text
Ran 157 tests
OK
```

اجرای Pytest نیز نتیجه زیر را ثبت کرد:

```text
157 passed, 4 subtests passed
```

### ۱۲.۲ Acceptance اختصاصی Parallel Runtime

```text
14 passed, 4 subtests passed
```

سناریوهای تأییدشده:

- اجرای ۱، ۲، ۳ و ۴ Worker؛
- اجرای دقیقاً یک‌باره همه Jobها؛
- Dynamic Distribution برای Durationهای متفاوت؛
- Crash و Requeue و Worker Restart؛
- Timeout مستقل Startup/READY؛
- Heartbeat Timeout و جایگزینی Worker Frozen؛
- Profile نسل‌دار بعد از Restart؛
- Claim مالکیت/Heartbeat/Release/Reclaim؛
- دو Run مستقل روی Output مشترک بدون Duplicate، شامل Recheck بعد از Claim؛
- Stale Planner بدون Downgrade رکورد Completed؛
- نادیده‌گرفتن Event دیررس نسل قدیمی؛
- Graceful SIGTERM با نگه‌داشت Claim تا مرگ قطعی Worker و Kill Escalation؛
- Forced SIGKILL و Resume پس از Stale Claim؛
- Dispatch واقعی PDF و Markdown به Coordinator بدون ساخت Provider در Parent.

### ۱۲.۳ Acceptance سازگاری قبلی

هر سه سناریو موفق‌اند:

```text
[PASS] batch_failure_and_diagnostics
[PASS] retry_failed_and_resume
[PASS] pdf_book_end_to_end
```

### ۱۲.۴ Compile

```text
python -m compileall -q scripts tests
```

بدون خطا اجرا شد.

### ۱۲.۵ Patchright Smoke

Smoke واقعی Persistent Context با Chromium سیستمی موفق بود:

```text
executable=/usr/bin/chromium
provider=patchright
health=healthy
title=Patchright Smoke
screenshot=successful
```

---

## ۱۳. محدودیت و تست دستی باقی‌مانده

اجرای End-to-End چند Worker روی ChatGPT واقعی در این محیط انجام نشد، زیرا به Snapshot لاگین‌شده خصوصی کاربر و Account معتبر نیاز دارد. هیچ Cookie، Credential یا Session خصوصی داخل بسته قرار داده نشده است.

کد واقعی Worker/Provider به Batchها متصل است و Smoke مرورگر واقعی موفق است، اما Gate عملیاتی پیش از Production باید با Snapshot محلی کاربر برای Workerهای ۱، ۲ و ۴ اجرا شود:

```text
Upload → Send → Response Wait → Download → Validation
```

به دلیل اینکه Rate Limit حساب و ChatGPT Web سراسری است، شروع Production با ۲ Worker توصیه می‌شود تا فاز ۶ Global Cooldown و Adaptive Concurrency اضافه شود.

---

## ۱۴. موارد فاز بعدی

فاز ۶ باید موارد زیر را اضافه کند:

- Global Rate Limit Controller؛
- Cooldown مشترک میان Workerها؛
- Backoff با Jitter؛
- تفکیک Retry Budgetهای Content/Network/Browser/Download؛
- Circuit Breaker برای Authentication Failure؛
- Adaptive Concurrency؛
- Worker Recycling بر اساس تعداد Job یا Memory؛
- Zombie Browser Detection و Cleanup عمیق‌تر.

---

## ۱۵. نتیجه نهایی

فاز ۵ هدف اصلی خود را محقق کرده است: Note Maker دیگر برای Parallelism به تقسیم دستی فایل‌ها یا چند Shell مستقل وابسته نیست. تعداد Workerها قابل تنظیم است، صف پویاست، Browserها Process-isolated هستند، Manifest یک Writer دارد، Claimها مانع Duplicate می‌شوند و Crash، Freeze، Shutdown و Resume مسیر مشخص و آزموده‌شده دارند.
