from pathlib import Path
import sys
import unittest


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
        found = pdf.find_rich_index_md(ROOT / "outputs" / "phisiopath-full")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "STUDY_INDEX-rewritten.md")

    def test_make_pdf_writes_file(self):
        if pdf.HTML is None:
            self.skipTest("weasyprint not installed")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "sample.md"
            md.write_text("# Sample\n\n## Key Points\n\n- one\n", encoding="utf-8")
            out = pdf.make_pdf(md, Path(tmp) / "sample.pdf", auto_rtl=False)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 500)


if __name__ == "__main__":
    unittest.main()