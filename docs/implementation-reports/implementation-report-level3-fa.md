# گزارش اجرای فاز ۳ — Profile Manager و Session Bootstrap

**پروژه:** Note Maker  
**نسخه خروجی:** `0.5.0`  
**تاریخ اجرا:** ۲۰ تیر ۱۴۰۵ / 10 July 2026  
**وضعیت:** پیاده‌سازی و Gateهای خودکار کامل؛ تست زنده حساب واقعی ChatGPT نیازمند Session کاربر است

---

## ۱. هدف فاز

هدف این فاز حذف اشتراک ناامن Browser Profile و آماده‌سازی زیرساخت لازم برای Workerهای مستقل بود. هر Run و هر Worker باید Profile، Downloads، Logs و Diagnostics مستقل داشته باشد؛ Session ورود باید از یک Snapshot کنترل‌شده قابل بازیابی باشد؛ و هیچ دو Process نباید هم‌زمان مالک یک Profile شوند.

این فاز عمداً اجرای `--parallel-runs > 1` را فعال نمی‌کند. فعال‌سازی Parallel واقعی به Job Planner، Coordinator و Single-writer Manifest در فازهای بعد وابسته است.

---

## ۲. خروجی معماری

### ۲.۱ Profile Manager

ماژول `scripts/browser_runtime/profile_manager.py` اضافه شد و مسئولیت‌های زیر را بر عهده دارد:

- تشخیص شواهد Session معتبر ChatGPT/OpenAI از Cookie Database جدید و قدیمی Chromium؛
- کنترل انقضای Cookie بر اساس Timestamp داخلی Chromium؛
- ساخت Snapshot انتخابی از داده‌های Session؛
- ثبت Size و SHA-256 تک‌تک فایل‌های Snapshot؛
- اعتبارسنجی مجدد Snapshot پیش از Restore؛
- حذف Symlink و Lockهای ناامن از Snapshot؛
- جلوگیری Fail-Closed از Snapshot یا حذف Profile فعال؛
- ایجاد ساختار مستقل Run/Worker؛
- اعمال Cleanup/Retention Policy.

ساختار Runtime:

```text
.runtime/
└── runs/
    └── <run-id>/
        ├── run.json
        └── workers/
            └── <worker-id>/
                ├── worker.json
                ├── profile/
                ├── downloads/
                ├── logs/
                └── diagnostics/
```

### ۲.۲ Session Snapshot

Snapshot تنها داده‌های مرتبط با Session را منتقل می‌کند:

- `Cookies` و فایل‌های Journal/WAL/SHM؛
- `Local Storage`؛
- `Session Storage`؛
- `IndexedDB`؛
- `Login Data`؛
- `Web Data`؛
- `Local State`؛
- `Preferences` و `Secure Preferences`.

Cache، GPU data، Crash reports، Browser binaries، Lockها و Symlinkها منتقل نمی‌شوند.

فیلدهای شناخته‌شده حاوی مسیر Absolute در `Local State` و `Preferences` پاک‌سازی می‌شوند. `Secure Preferences` عمداً بدون بازنویسی کپی می‌شود، چون Chromium بخش‌هایی از آن را با Integrity Metadata محافظت می‌کند و تغییر آن ممکن است باعث کنار گذاشته‌شدن تنظیمات شود.

Metadata Snapshot مسیر Absolute پروفایل مبدأ را ذخیره نمی‌کند؛ فقط نام Profile و Fingerprint هش‌شده ثبت می‌شود.

### ۲.۳ مالکیت اتمیک Profile

برای هر Profile یک Lease اتمیک با فایل زیر ایجاد می‌شود:

```text
.note-maker-profile-owner.json
```

Lease شامل Token، PID، Host، Run ID و Worker ID است. ایجاد آن با `O_CREAT | O_EXCL` انجام می‌شود.

قواعد مالکیت:

- Profile دارای Owner زنده قابل استفاده نیست؛
- Owner مرده روی همان Host قابل بازیابی است؛
- Owner ناشناخته یا متعلق به Host دیگر Fail-Closed است؛
- `SingletonLock`، `SingletonSocket` و `SingletonCookie` فعال مانع استفاده یا Clone می‌شوند؛
- Lease در Close عادی و Failure هنگام Startup آزاد می‌شود.

### ۲.۴ Session Bootstrapper

ماژول `scripts/browser_runtime/session_manager.py` اضافه شد:

- قبل از Start مرورگر Lease را می‌گیرد؛
- Profile و Download Directory مستقل را به Provider تزریق می‌کند؛
- عملیات Cookie Pruning را فقط بعد از اخذ Lease انجام می‌دهد؛
- Session را داخل `ManagedBrowserSession` قرار می‌دهد؛
- در Close یا Startup Failure، Lease را آزاد می‌کند؛
- Provider-neutral است و برای Selenium و Patchright کار می‌کند.

### ۲.۵ Login Bootstrap

ابزارهای زیر اضافه شدند:

```text
scripts/profile_bootstrap.py
scripts/browser_runtime/login_bootstrap.py
run_login.sh
run_login.cmd
```

Commandهای `profile_bootstrap.py`:

- `inspect`
- `login`
- `snapshot`
- `prepare-worker`
- `cleanup-run`

نمونه Bootstrap:

```bash
./run_login.sh --profile chrome_profile_login --snapshot-name default
```

بعد از Login و بسته‌شدن Browser، ابزار وجود Cookie معتبر را بررسی و Snapshot را می‌سازد. خروجی شامل `snapshot_id` و مسیر Snapshot است.

### ۲.۶ تنظیمات Runtime در CLI

Flagهای زیر به PDF Batch، Markdown Batch و Pipeline اضافه و Forward شدند:

```text
--runtime-dir PATH
--profile-snapshot ID_OR_PATH
--keep-runtime
```

نمونه اجرا:

```bash
./run_pdf_batch.sh \
  --browser-provider patchright \
  --profile-snapshot default-YYYYMMDDTHHMMSSZ-xxxxxxxx \
  --runtime-dir .runtime \
  --parallel-runs 1
```

متغیرهای محیطی معادل:

```text
CHATGPT_RUNTIME_DIR
CHATGPT_PROFILE_TEMPLATE_DIR
CHATGPT_PROFILE_SNAPSHOT
CHATGPT_RUNTIME_RETENTION
```

Policy پیش‌فرض:

```text
delete-success-keep-failure
```

گزینه‌های دیگر:

```text
keep-all
delete-all
```

---

## ۳. یکپارچه‌سازی با Batchهای موجود

مسیرهای `batch_pdf.py` و `batch_markdown.py` اکنون:

1. Runtime Settings را Validate می‌کنند؛
2. در صورت انتخاب Snapshot، Worker Profile مستقل می‌سازند؛
3. در غیر این صورت Direct Profile قدیمی را Lease-protected استفاده می‌کنند؛
4. Session را از `SessionBootstrapper` دریافت می‌کنند؛
5. Recovery مرورگر را روی همان Worker Context انجام می‌دهند؛
6. بعد از Close، Retention Policy را اعمال می‌کنند؛
7. تنظیمات Runtime را در Batch Summary ثبت می‌کنند.

قابلیت‌های قبلی شامل Manifest، Resume، Retry، Validation، Atomic Save و Diagnostics بدون تغییر رفتاری حفظ شده‌اند.

---

## ۴. نکته مهم درباره مدل Process

در Smoke اولیه مشخص شد Patchright Sync API اجازه ایجاد دو Runtime مستقل در یک Python Process را نمی‌دهد. بنابراین تست و معماری نهایی به مدل صحیح زیر تغییر کرد:

```text
Coordinator Process
├── Worker Process 1 → Patchright Runtime 1 → Profile 1
└── Worker Process 2 → Patchright Runtime 2 → Profile 2
```

این نتیجه با ADR مربوط به Process-based Workerها و طراحی فاز Parallel Coordinator سازگار است.

---

## ۵. تست‌ها و اعتبارسنجی

### ۵.۱ Unit/Integration Tests

```text
Ran 128 tests
OK
```

پوشش جدید شامل:

- Cookie Database جدید و قدیمی؛
- Cookie منقضی؛
- Snapshot انتخابی؛
- حذف Absolute Pathهای شناخته‌شده؛
- عدم بازنویسی `Secure Preferences`؛
- SHA-256 و Size mismatch؛
- حذف Symlinkهای تو در تو؛
- Profile فعال؛
- Lease انحصاری؛
- بازیابی Owner مرده محلی؛
- Profileهای مستقل دو Worker؛
- Cleanup محدود به یک Worker؛
- Retention Policy؛
- Cleanup یک Run ناموجود بدون ساخت Artifact؛
- آزادشدن Lease در Startup Failure؛
- اجرای Callback فقط بعد از اخذ Lease؛
- CLI flags و Pipeline forwarding.

### ۵.۲ Acceptance

هر سه سناریوی Browser-free موفق شدند:

| سناریو | نتیجه |
|---|---|
| Partial failure + Diagnostics | Pass |
| Retry failed + unchanged Resume | Pass |
| PDF book end-to-end | Pass |

فایل نتیجه: `docs/level3-results/acceptance.json`

### ۵.۳ Compile

```text
python -m compileall -q scripts tests
compileall=passed
```

### ۵.۴ Patchright Basic Smoke

با Chromium سیستمی `/usr/bin/chromium`:

```text
provider=patchright
health=healthy
title=Patchright Smoke
basic navigation succeeded
```

### ۵.۵ Real Profile Isolation Smoke

Smoke واقعی با دو Process مستقل اجرا شد:

```text
snapshot_clone=passed
simultaneous_processes=2
profile_isolation=passed
```

در این تست:

- یک Persistent Profile پایه ایجاد شد؛
- Snapshot ساخته شد؛
- دو Worker از Snapshot مستقل Restore شدند؛
- دو Chromium هم‌زمان Start شدند؛
- Worker اول Stop شد؛
- Health و State Worker دوم سالم باقی ماند؛
- Runtime Worker اول حذف شد؛
- Profile Worker دوم دست‌نخورده باقی ماند.

---

## ۶. وضعیت معیارهای پذیرش فاز ۳

| معیار | وضعیت | توضیح |
|---|---|---|
| دو Browser هم‌زمان با Profile مستقل | Pass | Smoke واقعی دو Process |
| عدم وجود Singleton Lock مشترک | Pass | Clone مستقل، حذف Lockها و تست Activity |
| بازیابی Login بدون Login دستی هر Worker | پیاده‌سازی کامل؛ Live Account Pending | Cookie evidence و Clone تست شده؛ تست Account واقعی نیازمند Session خصوصی کاربر است |
| حذف Runtime یک Worker بدون اثر روی Worker دیگر | Pass | Smoke واقعی و Unit Test |
| مدیریت Pathهای Absolute ناسازگار | Pass | Sanitization تنظیمات شناخته‌شده + Metadata بدون Source Path |

---

## ۷. محدودیت‌های صریح

### ۷.۱ تست حساب واقعی ChatGPT

هیچ Credential، Cookie یا Session خصوصی در بسته قرار نگرفته است. در نتیجه زنجیره زیر با حساب واقعی اجرا نشده است:

```text
Reference Login
→ Authenticated Snapshot
→ Worker Restore
→ ChatGPT Login Reuse
→ Upload
→ Prompt
→ Download
```

ابزار اجرای آن آماده است، اما تأیید نهایی باید روی ماشین کاربر و با Profile لاگین‌شده انجام شود.

### ۷.۲ Parallel Runs

`--parallel-runs 2` و مقادیر بیشتر همچنان Fail-Closed هستند. دلیل:

- Job Planner مشترک هنوز استخراج نشده؛
- Manifest v2 و Single-writer Coordinator هنوز پیاده نشده‌اند؛
- Claim/IPC/Event Queue هنوز وجود ندارد.

فعال‌سازی زودهنگام Parallel می‌توانست Race روی Manifest و Job ownership ایجاد کند.

### ۷.۳ حساسیت Snapshot

`profile_templates/` باید مانند Credential نگهداری شود. Snapshot ممکن است داده‌های لازم برای ادامه Session کاربر را داشته باشد و نباید Commit، Share یا داخل ZIP عمومی قرار گیرد.

---

## ۸. فایل‌های اصلی اضافه یا تغییرکرده

### اضافه‌شده

```text
scripts/browser_runtime/profile_manager.py
scripts/browser_runtime/session_manager.py
scripts/browser_runtime/login_bootstrap.py
scripts/profile_bootstrap.py
scripts/smoke_test_profile_isolation.py
run_login.sh
run_login.cmd
tests/test_profile_manager.py
tests/test_session_bootstrap.py
docs/level3-results/*
```

### تغییرکرده

```text
scripts/browser_runtime/errors.py
scripts/browser_runtime/__init__.py
scripts/browser_runtime/selenium_provider.py
scripts/browser_runtime/selenium_legacy.py
scripts/batch_common.py
scripts/batch_pdf.py
scripts/batch_markdown.py
scripts/pipeline.py
scripts/runtime_flags.py
README.md
CHANGELOG.md
RELEASE_CHECKLIST.md
.gitignore
VERSION
package.json
```

---

## ۹. Gate ورود به فاز بعد

فاز ۳ برای ورود به **فاز ۴ — Job Planner و Single-writer Manifest** آماده است.

فاز بعد باید:

1. Planning را از Batchهای PDF و Markdown استخراج کند؛
2. Planning را بدون ساخت Browser انجام دهد؛
3. Manifest را به Schema v2 مهاجرت دهد؛
4. Run/Worker Metadata اضافه کند؛
5. Worker را از نوشتن مستقیم Manifest منع کند؛
6. Run-specific Summary ایجاد کند؛
7. پایه Single-writer Coordinator را آماده کند.

تا پایان فاز ۴، Parallel واقعی نباید فعال شود.
