import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdfdiffstudio.pdf_compare import build_page_diff


class PageDiffTests(unittest.TestCase):
    def test_build_page_diff_marks_insertions_and_deletions(self) -> None:
        result = build_page_diff(1, "A\nB\nC", "A\nB2\nC\nD")

        self.assertEqual(result.page_number, 1)
        self.assertEqual(result.added_lines, 1)
        self.assertEqual(result.removed_lines, 0)
        self.assertEqual(result.changed_lines, 1)
        self.assertTrue(result.is_changed)
        self.assertIn("word-added", result.right_html)
        self.assertIn("added", result.right_html)

    def test_build_page_diff_marks_removed_page(self) -> None:
        result = build_page_diff(3, "Only on the left", "")

        self.assertEqual(result.status, "Removed")
        self.assertEqual(result.removed_lines, 1)
        self.assertEqual(result.added_lines, 0)

    def test_build_page_diff_for_equal_text_is_unchanged(self) -> None:
        result = build_page_diff(2, "Same\nText", "Same\nText")

        self.assertEqual(result.status, "Unchanged")
        self.assertEqual(result.added_lines, 0)
        self.assertEqual(result.removed_lines, 0)
        self.assertEqual(result.changed_lines, 0)
        self.assertEqual(result.similarity, 1.0)

    def test_build_page_diff_can_render_dark_theme(self) -> None:
        result = build_page_diff(4, "Old value", "New value", theme="dark")

        self.assertIn("#17191c", result.left_html)
        self.assertIn("#17191c", result.right_html)
        self.assertIn("word-removed", result.left_html)
        self.assertIn("word-added", result.right_html)


if __name__ == "__main__":
    unittest.main()
