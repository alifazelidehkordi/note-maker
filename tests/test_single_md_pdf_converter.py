from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import convert_single_md_to_pdf as pdf


class SingleMdPdfConverterTests(unittest.TestCase):
    def test_rtl_detection_handles_mixed_text(self):
        self.assertTrue(pdf.is_rtl_heavy("فهرست مطالب پزشکی"))
        self.assertFalse(pdf.is_rtl_heavy("Medical study notes"))

    def test_document_title_prefers_first_heading(self):
        headings = [pdf.Heading(level=1, title="Respiratory System", anchor="h1")]
        self.assertEqual(
            pdf.document_title(headings, Path("fallback.md")),
            "Respiratory System",
        )

    def test_toc_filters_to_supported_depth_and_preserves_links(self):
        headings = [
            pdf.Heading(level=1, title="One", anchor="one"),
            pdf.Heading(level=3, title="Three", anchor="three"),
            pdf.Heading(level=4, title="Four", anchor="four"),
        ]
        toc_html, included = pdf.build_toc(headings, "Table of Contents")
        self.assertEqual([heading.anchor for heading in included], ["one", "three"])
        self.assertIn('href="#one"', toc_html)
        self.assertIn('href="#three"', toc_html)
        self.assertNotIn('href="#four"', toc_html)


if __name__ == "__main__":
    unittest.main()
