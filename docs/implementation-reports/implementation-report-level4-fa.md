# گزارش اجرای فاز ۴ — Job Planner و Single-writer Manifest

**پروژه:** Note Maker  
**نسخه خروجی:** `0.6.0`  
**تاریخ اجرا:** ۲۰ تیر ۱۴۰۵ / 10 July 2026  
**وضعیت:** پیاده‌سازی کامل، تمام Gateهای خودکار موفق، اجرای موازی واقعی همچنان Fail-Closed

---

## ۱. هدف فاز

هدف این فاز آماده‌کردن هسته داده و Planning برای اجرای موازی بود، بدون آن‌که هنوز چند Browser یا Worker واقعی Start شوند. دو مسئله اصلی حل شدند:

1. Planning و تصمیم‌های Resume از `batch_pdf.py` و `batch_markdown.py` خارج و به یک Planner مشترک و Browser-free منتقل شدند.
2. Manifest از Schema 1 به Schema 2 ارتقا یافت و مالکیت نوشتن آن به Process هماهنگ‌کننده محدود شد تا در فاز بعد Workerها فقط Event تولید کنند و هیچ‌گاه Manifest را مستقیم تغییر ندهند.

این فاز عمداً `--parallel-runs > 1` را فعال نمی‌کند. برای فعال‌سازی ایمن Parallel، هنوز Coordinator، Event Bus، Claim Store و Worker Runtime فاز ۵ لازم‌اند.

---

## ۲. خروجی معماری

### ۲.۱ Package جدید `parallel_runtime`

ساختار زیر اضافه شد:

```text
scripts/parallel_runtime/
├── __init__.py
├── models.py
├── planner.py
└── job_sources.py
```

مسئولیت‌ها:

- `models.py`: مدل‌های مستقل از Browser؛
- `planner.py`: تصمیم‌گیری Resume و ساخت Execution Plan؛
- `job_sources.py`: تبدیل File Job و Markdown Section به Candidateهای پایدار؛
- `__init__.py`: سطح عمومی مدل‌ها و Planner.

هیچ‌یک از این ماژول‌ها به Selenium، Patchright، Locator یا Browser Session وابسته نیستند.

### ۲.۲ مدل `ExecutionJob`

`JobSpec` قبلی به یک مدل عمومی‌تر با نام `ExecutionJob` ارتقا یافت و نام `JobSpec` برای سازگاری حفظ شد.

فیلدهای اصلی:

```text
key
source
source_hash
prompt_path
prompt_hash
output
expected_extensions
mode
model
title
estimated_weight
metadata
```

ویژگی‌های مهم:

- مسیرها در زمان ساخت Resolve می‌شوند؛
- Extensionها Normalize و مرتب می‌شوند؛
- `metadata` به Mapping غیرقابل‌تغییر تبدیل می‌شود؛
- `estimated_weight` حداقل ۱ است؛
- مدل قابلیت تبدیل به Payload سریال‌پذیر را دارد؛
- Property سازگار `prompt` برای API قبلی باقی مانده است.

### ۲.۳ وزن تخمینی Job

برای آماده‌سازی صف پویا در فاز ۵، هر Job وزن تقریبی دارد:

- File Job: بر اساس Size فایل با واحد ۲۵۶ KiB؛
- Text/Section Job: بر اساس حجم UTF-8 با واحد ۴۰۰۰ Byte؛
- حداقل وزن: `1`.

این وزن فعلاً ترتیب اجرای Sequential را تغییر نمی‌دهد، اما در Coordinator بعدی برای Priority، Load Balancing و جلوگیری از Idle شدن Workerها قابل استفاده است.

---

## ۳. Planner مشترک و Browser-free

### ۳.۱ روند Planning

Batchها اکنون قبل از ساخت Browser Provider مراحل زیر را انجام می‌دهند:

1. جمع‌آوری Sourceها یا Sectionها؛
2. ساخت `PlanningCandidate`؛
3. ساخت `ExecutionJob` پایدار؛
4. خواندن Manifest از طریق View فقط‌خواندنی؛
5. اجرای `plan_jobs()`؛
6. تولید Plan شامل:
   - Jobهای Runnable؛
   - Jobهای Skip؛
   - Jobهای Adopt؛
   - Transitionهای Manifest؛
   - مجموع وزن تخمینی؛
7. ثبت تمام Transitionهای اولیه در یک Batch Write؛
8. ساخت Provider و Browser فقط وقتی `plan.requires_worker == True` باشد.

### ۳.۲ نتیجه صفر Job قابل اجرا

اگر همه Jobها Completed و معتبر باشند یا توسط Filterها Skip شوند:

- Browser Provider ساخته نمی‌شود؛
- Session Bootstrap اجرا نمی‌شود؛
- Worker ساخته نمی‌شود؛
- Summary و Run Record همچنان ثبت می‌شوند؛
- Exit Code رفتار قبلی را حفظ می‌کند.

این رفتار با تستی کنترل می‌شود که `get_browser_provider()` و `bootstrap_session()` را در حالت صفر Job ممنوع می‌کند.

### ۳.۳ Markdown Section Planning

فایل موقت هر Section اکنون در مرحله Planning و قبل از Worker Startup ساخته می‌شود:

```text
<output-dir>/_md_sections/<section-stem>.md
```

مسیر فایل در `ExecutionJob.metadata.section_file` ثبت می‌شود. بنابراین Worker Process آینده یک Path پایدار دریافت می‌کند و لازم نیست Object حافظه‌ای `MarkdownSection` را از Process اصلی به‌صورت ضمنی به اشتراک بگذارد.

### ۳.۴ Transitionهای Planner

Planner مستقیماً Manifest را تغییر نمی‌دهد و فقط Transition تولید می‌کند:

```text
PENDING
INVALIDATED
ADOPTED
INTERRUPTED
```

نوشتن این Transitionها فقط توسط `ManifestCoordinator.apply_plan()` انجام می‌شود.

---

## ۴. Manifest Schema Version 2

### ۴.۱ ساختار سطح بالا

Schema جدید:

```json
{
  "schema_version": 2,
  "created_at": "...",
  "updated_at": "...",
  "runs": {},
  "items": {}
}
```

بخش `runs` برای ثبت هر اجرای مستقل اضافه شد.

### ۴.۲ Metadata جدید هر Job

فیلدهای زیر به Record هر Job اضافه شدند:

```text
estimated_weight
metadata
run_id
worker_id
claimed_at
last_heartbeat_at
browser_restarts
duration_seconds
rate_limit_count
```

در اجرای Sequential فعلی، `worker_id` برابر `worker-001` است. این ساختار مستقیماً برای Workerهای واقعی فاز بعد قابل استفاده است.

### ۴.۳ وضعیت `interrupted`

Status جدید `interrupted` اضافه شد. Jobهای `running` متعلق به اجرای قبلی در مرحله Planning قابل تبدیل به `interrupted` هستند و Resume Decision آن‌ها همچنان Runnable باقی می‌ماند.

API جدید:

```python
mark_interrupted(job, reason=...)
```

### ۴.۴ Migration از Schema 1

Manifestهای نسخه ۱ به‌صورت خودکار خوانده می‌شوند:

- `schema_version` به ۲ ارتقا می‌یابد؛
- `runs` اضافه می‌شود؛
- Metadataهای اجرایی با مقدار امن پیش‌فرض افزوده می‌شوند؛
- وضعیت و Hashهای Jobهای قدیمی حفظ می‌شوند؛
- Metadata مهاجرت ثبت می‌شود:

```json
{
  "migration": {
    "from_schema_version": 1,
    "migrated_at": "..."
  }
}
```

نسخه‌های ناشناخته همچنان Fail-Closed هستند.

---

## ۵. Single-writer و کنترل Race

### ۵.۱ مالک صریح نوشتن

Batchها اکنون از کلاس زیر استفاده می‌کنند:

```python
ManifestCoordinator
```

Planner و Worker آینده فقط `ManifestReaderView` دریافت می‌کنند. این View فقط دو عملیات دارد:

```text
get
inspect
```

هیچ API نوشتنی مانند `mark_running`، `mark_completed` یا `save` روی View وجود ندارد.

### ۵.۲ محافظت Process-bound

Writable Manifest هنگام ساخت PID مالک را ثبت می‌کند. اگر همان Handle بعد از Fork/Process Boundary داخل Worker استفاده شود، هر Mutation با خطای زیر متوقف می‌شود:

```text
ManifestWriteForbiddenError
```

Worker باید نتیجه را به Coordinator Event Bus ارسال کند؛ مسیر مستقیم نوشتن Fail-Closed است.

### ۵.۳ Write Lock کوتاه‌مدت

هر Save یک Lock کوتاه‌مدت اتمیک می‌گیرد:

```text
.<manifest-name>.write.lock
```

Lock با `O_CREAT | O_EXCL` ساخته می‌شود و فقط زمان Read-Merge-Atomic Replace نگه داشته می‌شود. Lock قدیمی‌تر از ۶۰ ثانیه قابل پاک‌سازی است و Timeout انتظار ۵ ثانیه است.

### ۵.۴ Dirty-key Merge

هر Coordinator فقط Keyهای تغییرکرده خود را روی آخرین نسخه Disk Merge می‌کند. نتیجه:

- دو Coordinator که Manifest را در زمان متفاوت Load کرده‌اند، اگر Jobهای متفاوتی را تغییر دهند Update یکدیگر را از بین نمی‌برند؛
- کل Snapshot قدیمی روی فایل جدید Overwrite نمی‌شود؛
- Atomic Replace و Backup قبلی حفظ شده‌اند.

این رفتار با تست دو Instance قدیمی که Jobهای `a` و `b` را مستقل می‌نویسند تأیید شده است.

### ۵.۵ Batched Flush

Context Manager جدید:

```python
with store.batch_update():
    ...
```

تمام Transitionهای Planning و Run Registration در یک Flush ثبت می‌شوند. تست Failure/Spy تأیید می‌کند که برای چند Job فقط یک `save()` انجام می‌شود.

---

## ۶. Run Metadata

APIهای جدید:

```text
register_run
finish_run
get_run
```

Record هر Run شامل موارد زیر است:

```text
run_id
mode
status
created_at
updated_at
finished_at
planned_jobs
estimated_total_weight
parallel_runs
browser_provider
summary_path
```

Status پایان Run در حالت فعلی یکی از موارد زیر است:

```text
completed
completed_with_failures
```

اگر Process پیش از پایان متوقف شود، وضعیت میانی و Jobهای Running/Interrupted برای Resume باقی می‌مانند.

---

## ۷. Summary اختصاصی Run

هر Batch اکنون یک Summary تغییرناپذیر می‌سازد:

```text
logs/runs/<run-id>/summary.json
```

برای سازگاری با ابزارهای قبلی، فایل زیر همچنان یک Copy کامل از آخرین Summary است:

```text
logs/last_batch_summary.json
```

و Pointer زیر Source اصلی را مشخص می‌کند:

```text
logs/last_batch_summary.pointer.json
```

هر سه فایل با Temporary File، `fsync` و `os.replace` نوشته می‌شوند.

---

## ۸. تغییرات Batch PDF و Markdown

### PDF Batch

- ساخت Job و Resume Loop محلی حذف شد؛
- `build_file_candidates()` و `plan_jobs()` استفاده می‌شوند؛
- Provider فقط در صورت وجود Job Runnable ساخته می‌شود؛
- هر Attempt با `worker-001` در Manifest v2 ثبت می‌شود؛
- Run Record و Summary Path ثبت می‌شوند.

### Markdown Batch

- Planning Sectionها به Planner مشترک منتقل شد؛
- Section File قبل از Startup ساخته می‌شود؛
- Metadata Section در Job ثبت می‌شود؛
- Resume و Adopt/Skip رفتار قبلی را حفظ کرده‌اند؛
- Provider فقط برای Plan غیرخالی ساخته می‌شود.

---

## ۹. تست‌ها و Gateهای نهایی

### ۹.۱ Automated Tests

نتیجه نهایی:

```text
Ran 139 tests
OK
```

تست‌های جدید شامل:

- Planning فایل بدون Browser؛
- Planning Section و Materialization پایدار؛
- محاسبه وزن File/Text؛
- صفر Job قابل اجرا و عدم ساخت Provider؛
- Batch Flush تک‌نوشتن؛
- Migration Schema 1 به 2؛
- Worker/Run Metadata؛
- وضعیت Interrupted؛
- Process-bound Writer Guard؛
- Read-only Manifest API؛
- Merge دو Coordinator با Snapshot قدیمی؛
- مسیر Summary اختصاصی Run و Latest Pointer؛
- AST Boundary برای جلوگیری از بازگشت Planning به Batchها؛
- عدم وابستگی Planner به Browser Runtime.

### ۹.۲ Acceptance

هر سه سناریوی Acceptance موفق شدند:

```text
[PASS] batch_failure_and_diagnostics
[PASS] retry_failed_and_resume
[PASS] pdf_book_end_to_end
```

Resume بدون Browser، Retry Failed، حفظ Artifact سالم، Diagnostics، PDF Rendering، Internal Link و Bookmark همگی تأیید شدند.

### ۹.۳ Compile

```text
python -m compileall -q scripts tests
```

بدون خطا اجرا شد.

### ۹.۴ Browser Smoke

Smoke واقعی Patchright با Chromium سیستمی موفق بود:

```text
executable: /usr/bin/chromium
provider: patchright
health: healthy
title: Patchright Smoke
screenshot: successful
```

این Smoke به ChatGPT متصل نشد و از `about:blank` و HTML محلی استفاده کرد.

---

## ۱۰. موارد عمداً خارج از این فاز

موارد زیر هنوز پیاده‌سازی نشده‌اند:

- اجرای واقعی چند Worker؛
- Process Coordinator؛
- Queue پویا و Work Stealing؛
- Worker Event Bus؛
- Claim File و Lease Job؛
- Heartbeat و Worker Lost Detection؛
- Global Rate-limit Controller؛
- Adaptive Concurrency؛
- Graceful/Forced Shutdown چند Process.

بنابراین:

```text
--parallel-runs 2
```

همچنان با پیام Level 4 Fail-Closed است.

---

## ۱۱. Gate ورود به فاز ۵

شرایط لازم برای شروع Parallel Coordinator برقرار شده‌اند:

- Browser Provider مستقل است؛
- Profile هر Worker مستقل است؛
- Jobها مدل سریال‌پذیر و وزن‌دار دارند؛
- Planning بدون Browser انجام می‌شود؛
- Markdown Worker Input مسیر پایدار دارد؛
- Manifest v2 Run/Worker Metadata دارد؛
- Worker API فقط‌خواندنی است؛
- تنها Coordinator می‌تواند Manifest را تغییر دهد؛
- صفر Job باعث Startup Worker نمی‌شود؛
- Summaryها Run-specific هستند.

فاز بعد باید `coordinator.py`، `worker.py`، `event_bus.py`، `claims.py` و Lifecycle Processها را پیاده‌سازی و سپس `--parallel-runs N` را برای اولین بار فعال کند.

---

## ۱۲. نتیجه

فاز ۴ کامل است. Note Maker اکنون یک Data Plane امن و قابل‌تست برای Parallelism دارد، بدون آن‌که ریسک Race روی Manifest یا Startup غیرضروری Browser ایجاد شود. رفتار Sequential و Resume فعلی حفظ شده و زیرساخت لازم برای اجرای واقعی N Worker در فاز ۵ آماده است.
