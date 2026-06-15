import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdfdiffstudio.pdf_compare import compare_pdfs, render_visual_diff


class PdfIntegrationTests(unittest.TestCase):
    def test_compare_and_render_generated_pdfs(self) -> None:
        if importlib.util.find_spec("fitz") is None or importlib.util.find_spec("PIL") is None:
            raise unittest.SkipTest("PyMuPDF and Pillow are not installed")

        import fitz

        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            left_pdf = root / "left.pdf"
            right_pdf = root / "right.pdf"
            self._write_pdf(fitz, left_pdf, "Invoice\nTotal: 100 USD")
            self._write_pdf(fitz, right_pdf, "Invoice\nTotal: 120 USD")

            result = compare_pdfs(left_pdf, right_pdf)
            self.assertEqual(result.left_page_count, 1)
            self.assertEqual(result.right_page_count, 1)
            self.assertEqual(result.changed_pages, 1)

            visual = render_visual_diff(left_pdf, right_pdf, 0, dpi=72, output_dir=root / "visual")
            self.assertTrue(visual.left_image.exists())
            self.assertTrue(visual.right_image.exists())
            self.assertGreater(visual.changed_ratio, 0)

    @staticmethod
    def _write_pdf(fitz, path: Path, text: str) -> None:
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 72), text, fontsize=14)
        document.save(path)
        document.close()


if __name__ == "__main__":
    unittest.main()
