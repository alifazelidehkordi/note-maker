from argparse import Namespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import convert_md_to_pdf as pdf


class ConvertMdToPdfTests(unittest.TestCase):
    def test_clean_markdown_strips_frontmatter_and_metadata(self):
        raw = """---
pdf_pages: 1-3
---
**منبع اصلی:** sample.pdf

# Topic

Body
"""
        cleaned = pdf.clean_markdown(raw)
        self.assertIn("# Topic", cleaned)
        self.assertNotIn("pdf_pages", cleaned)
        self.assertNotIn("منبع اصلی", cleaned)

    def test_contains_rtl_script_detects_persian(self):
        self.assertTrue(pdf.contains_rtl_script("فهرست مطالب"))
        self.assertFalse(pdf.contains_rtl_script("Table of Contents"))

    def test_resolve_style_auto_enables_rtl(self):
        style = pdf.resolve_style(pdf.PdfStyle(), "فصل اول", auto_rtl=True)
        self.assertTrue(style.rtl)

    def test_resolve_style_respects_forced_ltr(self):
        style = pdf.resolve_style(
            pdf.PdfStyle(rtl=False),
            "فصل اول",
            auto_rtl=False,
        )
        self.assertFalse(style.rtl)

    def test_infer_title_uses_first_heading(self):
        text = "# Cell Membrane\n\n## Explanation\n"
        self.assertEqual(pdf.infer_title(text, "fallback", cleaned=True), "Cell Membrane")

    def test_md_to_html_wraps_key_points(self):
        if pdf.markdown is None:
            self.skipTest("markdown package not installed")
        html_body = pdf.md_to_html(
            "# Topic\n\n## Key Points\n\n- one\n",
            cleaned=True,
        )
        self.assertIn('class="key-points"', html_body)
        self.assertIn("Key Points", html_body)

    def test_apply_preset_uses_named_defaults(self):
        style = pdf.apply_preset(pdf.PdfStyle(preset="compact"))
        self.assertEqual(style.font_size, pdf.PRESETS["compact"]["font_size"])
        self.assertEqual(style.margin, pdf.PRESETS["compact"]["margin"])

    def test_is_topic_note_filters_meta_files(self):
        self.assertTrue(pdf.is_topic_note(Path("01_01_Topic.md")))
        self.assertFalse(pdf.is_topic_note(Path("STUDY_INDEX-rewritten.md")))
        self.assertFalse(pdf.is_topic_note(Path("COMBINED_NOTES.md")))

    def test_find_rich_index_md(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes"
            notes.mkdir()
            (Path(tmp) / "STUDY_INDEX-rewritten.md").write_text("# Index\n", encoding="utf-8")
            found = pdf.find_rich_index_md(notes)
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "STUDY_INDEX-rewritten.md")

    def test_make_pdf_writes_file(self):
        if pdf.HTML is None:
            self.skipTest("weasyprint not installed")
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "sample.md"
            md.write_text("# Sample\n\n## Key Points\n\n- one\n", encoding="utf-8")
            out = pdf.make_pdf(md, Path(tmp) / "sample.pdf", auto_rtl=False)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 500)

    def test_batch_convert_reports_partial_failures_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "notes"
            output_dir = root / "pdfs"
            input_dir.mkdir()
            for name in ("01_First.md", "02_Broken.md", "03_Third.md"):
                (input_dir / name).write_text(f"# {name}\n", encoding="utf-8")

            def fake_make_pdf(md_path, output_pdf, **_kwargs):
                if md_path.name == "02_Broken.md":
                    raise RuntimeError("simulated renderer failure")
                output_pdf.write_bytes(b"%PDF-test")
                return output_pdf

            with patch.object(pdf, "require_dependencies"), patch.object(
                pdf, "make_pdf", side_effect=fake_make_pdf
            ):
                result = pdf.batch_convert(input_dir, output_dir)

            self.assertEqual(
                [path.name for path in result.created],
                ["01_First.pdf", "03_Third.pdf"],
            )
            self.assertEqual(len(result.failed), 1)
            self.assertEqual(result.failed[0][0].name, "02_Broken.md")
            self.assertIn("simulated renderer failure", result.failed[0][1])
            self.assertFalse(result.succeeded)

    def test_main_returns_two_when_batch_has_failures(self):
        args = Namespace(
            input="notes",
            output="pdfs",
            batch=True,
            pattern="*.md",
            css=None,
            preset="study",
            theme="medical-blue",
            page_size="A4",
            margin=None,
            font_size=None,
            line_height=None,
            font_family=None,
            rtl=False,
            no_auto_rtl=False,
            no_page_numbers=False,
            title=None,
        )
        result = pdf.BatchResult(
            created=[Path("pdfs/01_First.pdf")],
            failed=[(Path("notes/02_Broken.md"), "failed")],
        )
        with patch.object(pdf, "parse_args", return_value=args), patch.object(
            pdf, "batch_convert", return_value=result
        ):
            self.assertEqual(pdf.main(), 2)

    def test_main_returns_zero_when_batch_succeeds(self):
        args = Namespace(
            input="notes",
            output="pdfs",
            batch=True,
            pattern="*.md",
            css=None,
            preset="study",
            theme="medical-blue",
            page_size="A4",
            margin=None,
            font_size=None,
            line_height=None,
            font_family=None,
            rtl=False,
            no_auto_rtl=False,
            no_page_numbers=False,
            title=None,
        )
        result = pdf.BatchResult(created=[Path("pdfs/01_First.pdf")], failed=[])
        with patch.object(pdf, "parse_args", return_value=args), patch.object(
            pdf, "batch_convert", return_value=result
        ):
            self.assertEqual(pdf.main(), 0)


if __name__ == "__main__":
    unittest.main()
