# گزارش ادغام و پایداری Note Maker

تاریخ بررسی: 2026-09-05

## وضعیت اولیه

- مخزن `alifazelidehkordi/note-maker`، branch پیش‌فرض `main`، commit اولیه `a86ed6744841e38439c8433e45a15e36b11915cc`.
- نسخه پروژه 0.8.2؛ Python >=3.10، setuptools/wheel، argparse CLI و TOML configuration.
- Selenium/Patchright برای مرورگر، Markdown/Mistune، WeasyPrint و pypdf برای PDF، OPML/XMind، multiprocessing و manifest برای پردازش قابل ادامه.
- package.json فقط launcher دستورات تست/پذیرش است؛ پروژه frontend جاوااسکریپتی نیست.
- وابستگی‌ها: pyproject.toml، requirements.lock و requirements-dev.lock؛ requirements.txt به lock زمان اجرا ارجاع می‌دهد.
- CI اولیه main موفق بود: workflow runهای <run-id> و <run-id>.
- تست پایه محلی: 232 تست، موفق با یک skip؛ ادعایی مبنی بر خراب بودن اولیه main وجود ندارد.
- clone مستقیم بدون credential در این محیط ممکن نبود. محتوای Git از اتصال مجاز GitHub دریافت شد؛ blobها، treeها و 80 commit موردنیاز با SHA اصلی بازسازی/تأیید شدند. ادغام‌ها با Git و استراتژی ort انجام شدند. تاریخچه محلی در مبنای 9109c6d shallow است؛ تاریخچه اصلی GitHub حذف یا بازنویسی نمی‌شود.

## تغییرات منتقل‌شده

اعداد ستون جلو/عقب نسبت به main اولیه هستند. همه 16 branch (شامل main) بررسی شدند و صفحه بعدی فهرست خالی بود.

| Branch | SHA اولیه | جلو/عقب | تصمیم |
|---|---|---|---|
| `dependabot/github_actions/actions/checkout-7` | `3a0b57a` | 1/11 | ادغام استاندارد؛ بررسی release notes و حفظ workflow فعلی. |
| `dependabot/github_actions/actions/setup-python-7` | `f7d9074` | 1/11 | ادغام استاندارد؛ بررسی release notes و حفظ workflow فعلی. |
| `dependabot/github_actions/actions/upload-artifact-7` | `80cfcbe` | 1/11 | ادغام استاندارد؛ بررسی release notes و حفظ workflow فعلی. |
| `feat/single-md-pdf-converter` | `fbf54e4` | 2/99 | بدون ادغام مجدد؛ کد آن عیناً در scripts/convert_single_md_to_pdf.py موجود است. |
| `improve/part-1a-profile-cleanup` | `a1101e2` | 10/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-1b-stage-events` | `0b6f017` | 18/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-1c-live-status` | `4f63ab6` | 20/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-1d-event-journal` | `98de179` | 25/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-1e-structured-logs` | `c97ff1d` | 29/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-1f-observability-summary` | `faa8bea` | 35/0 | ادغام از مسیر part-1f؛ ایمنی پروفایل و observability. |
| `improve/part-2a-project-login` | `0ce595c` | 31/0 | ادغام از مسیر part-2b؛ تنظیمات پروژه، session و preview. |
| `improve/part-2b-execution-preview` | `44375ad` | 39/0 | ادغام از مسیر part-2b؛ تنظیمات پروژه، session و preview. |
| `improve/part-2c-run-command-ergonomics` | `44375ad` | 39/0 | همان SHA مربوط به part-2b؛ بدون تغییر مستقل و با ادغام part-2b پوشش داده شد. |
| `improve-interactive-cli` | `e651258` | 11/11 | ادغام استاندارد؛ wizard، اعتبارسنجی ورودی و نصب console در setup. |
| `pdf-final-pipeline` | `2f362ee` | 6/99 | وارد نشد؛ جایگزینی ناسازگار مسیر فعلی، الزام فونت‌های SF موجودنبودن در مخزن و افزودن PyMuPDF/reportlab. |

تغییرات part-1a تا part-1f به صورت زنجیره‌ای هستند. مسیر part-2 از part-1c منشعب شده است؛ ادغام part-1f و part-2b هر دو مجموعه را حفظ می‌کند. برای جلوگیری از تکرار تاریخچه، cherry-pick لازم نشد.

### تعارض‌ها

- `note_maker/entrypoint.py`: تعارض add/add بین پیش‌نمایش و گزارش تفصیلی؛ parser/helperها و dispatch هر دو قابلیت حفظ شدند.
- `note_maker/cli.py`: importها، گزینه profile-snapshot و doctor؛ session alias و doctor جدید با wizard، keep-runtime و اجرای قدیمی ترکیب شدند.
- `.github/workflows/quality.yml` و `.github/workflows/phase1-stability.yml`: تغییر خطوط مجاور checkout/setup-python؛ هر دو action روی v7 قرار گرفتند و مراحل موجود حفظ شدند.
- هیچ فایل یا قابلیت PDF موجود حذف نشد. فونت‌های دلخواه و مبدل سخت‌گیرانه همچنان نیازمند فایل فونت ارائه‌شده توسط کاربر هستند.

## مشکلات پیدا شده و رفع آن‌ها

| مشکل | علت | راه‌حل | فایل‌ها |
|---|---|---|---|
| دو entrypoint ناسازگار | توسعه مستقل status details و preview | ترکیب کنترل مسیرها و تست استفاده متوالی از init، preview و details | note_maker/entrypoint.py، tests/test_cli_integration.py |
| شکست mypy: شش خطا | reuse متغیر alias با نوع متفاوت، provider اختیاری و ignoreهای تکراری | نام متغیر مستقل، مقدار رشته‌ای برای lookup و حذف ignore اضافی | note_maker/cli.py، note_maker/preview.py |
| شکست lint/format | ترتیب import و قالب‌بندی branchهای جدید | اجرای formatter و اصلاح import در سطح پشتیبانی‌شده | note_maker/cli.py، note_maker/entrypoint.py، note_maker/preview.py، note_maker/project.py |
| traceback در preview با sections نامعتبر یا prompt غیر UTF-8 | exceptionهای ValueError/UnicodeDecodeError کنترل نمی‌شدند | ConfigError و خروج با کد 2، بدون ساخت output؛ تست regression | note_maker/preview.py، tests/test_cli_integration.py |
| discoverability ناقص status details | گزینه‌ها در wrapper بودند و help اصلی آن‌ها را نمایش نمی‌داد | help خوانا و تست help، مستندات CLI مشترک | note_maker/cli.py، note_maker/entrypoint.py، docs/CLI.md |
| نصب دستی Patchright بدون مرورگر | pip باینری Chromium را نصب نمی‌کند | مستندکردن python -m patchright install chromium | README.md |
| setup بدون console | نصب dependencyها به‌تنهایی پروژه را نصب نمی‌کرد | انتقال نصب editable از branch interactive | setup.sh، setup.cmd |

## تست و اعتبارسنجی

محیط محلی: Linux، Python 3.12، venv مستقل `.venv`. داده‌های تست ساختگی هستند.

| دستور/بررسی | نتیجه |
|---|---|
| python -m pip install -r requirements-dev.lock | موفق؛ نسخه‌های دقیق lock |
| python -m pip install --no-deps -e . | موفق |
| python -m pip check | بدون ناسازگاری |
| python -m compileall -q note_maker scripts tests | موفق |
| python -m ruff check note_maker tests/test_configuration.py tests/test_unified_cli.py tests/test_cli_integration.py | موفق |
| python -m ruff format --check note_maker tests/test_configuration.py tests/test_unified_cli.py tests/test_cli_integration.py | موفق |
| python -m mypy note_maker | موفق، 8 فایل منبع |
| python -m coverage run -m unittest discover -s tests -v | 302 تست، موفق با یک skip |
| python -m coverage report | 61٪؛ حداقل لازم 45٪ |
| python scripts/phase1_acceptance.py --workdir <TEMP_DIR> --report <REPORT_JSON> | سه سناریوی موفق: diagnostics، retry/resume و PDF end-to-end؛ دو PDF موضوعی و کتاب 4 صفحه‌ای با لینک و bookmark |
| python scripts/level6_acceptance.py | 18 تست موفق با یک skip |
| python -m build | wheel و sdist ساخته شدند |
| python -m twine check dist/* | هر دو توزیع PASSED |
| نصب wheel با --no-deps --force-reinstall | موفق؛ --version، init، preview و status --help خارج از checkout تست شدند |
| piptools compile برای runtime و --extra dev | هر دو lock، پس از حذف خط کامنت دستور تولید، دقیقاً با مخزن یکسان هستند |
| python -m pip_audit -r requirements.lock --progress-spinner off | آسیب‌پذیری شناخته‌شده‌ای گزارش نشد |
| VERSION / package.json / pyproject.toml | همگی 0.8.2 |
| git diff --check | موفق |

## محدودیت‌ها و وضعیت نهایی

- پردازش محلی، مسیرهای CLI، تست‌های شبیه‌سازی‌شده browser، ساخت بسته و خروجی واقعی PDF تأیید شده‌اند.
- دانلود Chromium در محیط حاضر timeout شد و installer نهایتاً خطای lock داد؛ smoke واقعی Chromium اجرا نشده است. این خطای دریافت باینری محیط است و با تغییر کد برنامه پنهان نشده.
- ورود واقعی ChatGPT، تولید آنلاین و سازگاری زنده UI بدون session کاربر تأیید نشده‌اند.
- اجرای محلی Windows و Python 3.10 انجام نشده؛ matrix موجود GitHub این دو محور را پوشش می‌دهد.
- CI برخی branchهای اولیه پیش از اجرای هر step شکست خورده بود و log قابل دریافت نداشت؛ علت قطعی از اتصال موجود مشخص نشد. نتیجه CI ادغام در PR ثبت/پیگیری می‌شود و جایگزین نتایج محلی بالا نیست.
- استفاده کامل آنلاین منوط به نصب Chromium، کتابخانه‌های سیستم PDF و ایجاد session معتبر است.

## اجرای پیشنهادی

```bash
./setup.sh
source .venv-linux/bin/activate
note-maker init --input-dir inputs --output-dir outputs/notes \
  --prompt prompts/prompt-rewrite-notes.md --format md --browser-provider patchright
note-maker run pdf --dry-run
note-maker login --name default
note-maker run pdf --profile-snapshot default
```

ابتدا فایل‌های ورودی را در inputs قرار دهید. برای مسیر تعاملی از `note-maker interactive` استفاده کنید. گزینه‌های کامل در docs/CLI.md مستند شده‌اند.
