import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import convert_md_to_pdf as pdf
import create_combined_pdf as combined
from create_combined_pdf import add_continuous_page_numbers, aliases_from_uri, create_combined
from generate_study_index import build_index_md, collect_parts


class CombinedPdfLinkTests(unittest.TestCase):
    def test_file_and_note_aliases(self):
        self.assertIn("01_topic", aliases_from_uri("note://01_Topic"))
        self.assertIn("01_topic", aliases_from_uri("file:///tmp/01_Topic.pdf"))

    def test_continuous_page_numbers_and_labels(self):
        if pdf.HTML is None:
            self.skipTest("WeasyPrint unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "numbered.pdf"
            writer = PdfWriter()
            for _ in range(3):
                writer.add_blank_page(width=595.276, height=841.89)

            count = add_continuous_page_numbers(writer, start=4)
            with output.open("wb") as stream:
                writer.write(stream)

            reader = PdfReader(output)
            self.assertEqual(count, 3)
            self.assertEqual(reader.page_labels, ["4", "5", "6"])
            self.assertEqual([page.extract_text() for page in reader.pages], ["4", "5", "6"])

    def test_continuous_page_numbers_reject_invalid_start(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with self.assertRaisesRegex(ValueError, "start at 1"):
            add_continuous_page_numbers(writer, start=0)

    def test_index_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "01_01_Topic.md"
            note.write_text("---\npart: 1\nchapter: 1\ntitle: موضوع\npdf_pages: 1-2\n---\n# موضوع\n\nمتن", encoding="utf-8")
            text = build_index_md(collect_parts(Path(tmp)), course_title="نمونه")
            self.assertIn("## نمای کلی", text)
            self.assertIn("## فهرست فصل‌ها و گروه‌ها", text)
            self.assertIn("note://01_01_Topic", text)

    def test_combined_links_are_internal(self):
        if pdf.HTML is None or pdf.markdown is None:
            self.skipTest("PDF dependencies unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); notes = root / "notes"; notes.mkdir()
            for n in (1, 2):
                (notes / f"01_{n:02d}_Topic.md").write_text(f"# موضوع {n}\n\nمتن", encoding="utf-8")
            output = create_combined(notes, output_path=root / "final.pdf", title="نمونه")
            reader = PdfReader(output)
            self.assertEqual(
                reader.page_labels,
                [str(number) for number in range(1, len(reader.pages) + 1)],
            )
            index_pages = len(reader.pages) - 2
            page_map = {p.indirect_reference.idnum: i for i, p in enumerate(reader.pages)}
            uris, targets = [], []
            for page in reader.pages[:index_pages]:
                for ref in page.get("/Annots") or []:
                    annotation = ref.get_object(); action = annotation.get("/A")
                    if action and action.get("/S") == "/URI":
                        uris.append(action.get("/URI"))
                    dest = annotation.get("/Dest")
                    if isinstance(dest, list):
                        targets.append(page_map[dest[0].idnum])
            self.assertEqual(uris, [])
            self.assertEqual(set(targets), {index_pages, index_pages + 1})
            self.assertTrue((root / "STUDY_INDEX.md").exists())

    def test_pdf_needs_rebuild_when_missing_or_source_is_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "01_Topic.md"
            target = root / "01_Topic.pdf"
            note.write_text("# Topic\n", encoding="utf-8")

            self.assertTrue(combined.pdf_needs_rebuild(note, target))
            self.assertEqual(combined.pdf_rebuild_reason(note, target), "missing")

            target.write_bytes(b"%PDF-test")
            os.utime(target, ns=(1_000_000_000, 1_000_000_000))
            os.utime(note, ns=(2_000_000_000, 2_000_000_000))
            self.assertTrue(combined.pdf_needs_rebuild(note, target))
            self.assertEqual(combined.pdf_rebuild_reason(note, target), "source-newer")

            os.utime(target, ns=(3_000_000_000, 3_000_000_000))
            self.assertFalse(combined.pdf_needs_rebuild(note, target))
            self.assertIsNone(combined.pdf_rebuild_reason(note, target))

    def test_create_combined_rebuilds_only_stale_topic_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes"
            pdfs = root / "pdfs"
            notes.mkdir()
            pdfs.mkdir()
            stale_note = notes / "01_01_Stale.md"
            current_note = notes / "01_02_Current.md"
            stale_note.write_text("# Stale\n", encoding="utf-8")
            current_note.write_text("# Current\n", encoding="utf-8")
            index_md = root / "index.md"
            index_md.write_text("# Index\n", encoding="utf-8")

            def write_blank_pdf(path: Path) -> None:
                writer = PdfWriter()
                writer.add_blank_page(width=100, height=100)
                with path.open("wb") as stream:
                    writer.write(stream)

            stale_pdf = pdfs / "01_01_Stale.pdf"
            current_pdf = pdfs / "01_02_Current.pdf"
            write_blank_pdf(stale_pdf)
            write_blank_pdf(current_pdf)
            os.utime(stale_pdf, ns=(1_000_000_000, 1_000_000_000))
            os.utime(stale_note, ns=(2_000_000_000, 2_000_000_000))
            os.utime(current_note, ns=(1_000_000_000, 1_000_000_000))
            os.utime(current_pdf, ns=(2_000_000_000, 2_000_000_000))

            converted_sources: list[str] = []

            def fake_make_pdf(md_path, output_pdf, **_kwargs):
                converted_sources.append(Path(md_path).name)
                write_blank_pdf(Path(output_pdf))
                return Path(output_pdf)

            with patch.object(combined, "make_pdf", side_effect=fake_make_pdf):
                output = combined.create_combined(
                    notes,
                    pdf_dir=pdfs,
                    output_path=root / "final.pdf",
                    index_md=index_md,
                    title="Test",
                )

            self.assertTrue(output.exists())
            self.assertIn("01_01_Stale.md", converted_sources)
            self.assertNotIn("01_02_Current.md", converted_sources)
            self.assertIn("index.md", converted_sources)


if __name__ == "__main__":
    unittest.main()
