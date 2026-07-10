from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected source block not found in {path}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "scripts/convert_md_to_pdf.py",
    '            print(f"✓ {md.name} -> {pdf.name}")\n',
    '            print(f"[ok] {md.name} -> {pdf.name}")\n',
)
replace_once(
    "scripts/convert_md_to_pdf.py",
    '            print(f"✗ Failed {md.name}: {message}")\n',
    '            print(f"[error] Failed {md.name}: {message}")\n',
)
replace_once(
    "tests/test_combined_pdf_links.py",
    '''                output = combined.create_combined(
                    notes,
                    pdf_dir=pdfs,
                    output_path=root / "final.pdf",
                    index_md=index_md,
                    title="Test",
                )
''',
    '''                output = combined.create_combined(
                    notes,
                    pdf_dir=pdfs,
                    output_path=root / "final.pdf",
                    index_md=index_md,
                    title="Test",
                    continuous_page_numbers=False,
                )
''',
)

Path(".github/workflows/phase1-stability.yml").write_text('''name: Phase 1 Stability

on:
  push:
  pull_request:

jobs:
  tests:
    name: Tests (${{ matrix.os }}, Python ${{ matrix.python }})
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.10", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - name: Install Python dependencies
        run: python -m pip install --upgrade pip && python -m pip install -r requirements.txt
      - name: Compile Python sources
        run: python -m compileall -q scripts tests
      - name: Run test suite
        run: python -m unittest discover -s tests -v

  acceptance:
    name: Browser-free release acceptance
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install PDF system libraries
        run: |
          sudo apt-get update
          sudo apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info
      - name: Install Python dependencies
        run: python -m pip install --upgrade pip && python -m pip install -r requirements.txt
      - name: Run Phase 1 acceptance
        run: python scripts/phase1_acceptance.py --workdir "$RUNNER_TEMP/notemaker-acceptance" --report logs/phase1-acceptance.json
      - name: Upload acceptance report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: phase1-acceptance-report
          path: logs/phase1-acceptance.json
''', encoding="utf-8")

Path(__file__).unlink()
