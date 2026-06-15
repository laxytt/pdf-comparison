from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdfdiffstudio.pdf_compare import PdfComparisonResult, build_page_diff
from pdfdiffstudio.typing_validator import validate_typing


class TypingValidatorTests(unittest.TestCase):
    def test_validate_typing_detects_english_typo(self) -> None:
        result = self._comparison("This sentence has an exampel typo.", "")

        validation = validate_typing(result, "en")

        self.assertTrue(any(issue.word == "exampel" for issue in validation.issues))
        self.assertTrue(any("example" in issue.suggestions for issue in validation.issues))

    def test_validate_typing_detects_dutch_typo(self) -> None:
        result = self._comparison("", "Dit is een voorbeeldt zin.")

        validation = validate_typing(result, "nl")

        self.assertTrue(any(issue.word == "voorbeeldt" for issue in validation.issues))
        self.assertTrue(any("voorbeeld" in issue.suggestions for issue in validation.issues))

    def test_validate_typing_auto_picks_dutch_context(self) -> None:
        result = self._comparison("", "Dit is een voorbeeldt zin met tekst.")

        validation = validate_typing(result, "auto")

        matching = [issue for issue in validation.issues if issue.word == "voorbeeldt"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].language_code, "nl")

    @staticmethod
    def _comparison(left_text: str, right_text: str) -> PdfComparisonResult:
        page = build_page_diff(1, left_text, right_text)
        return PdfComparisonResult(
            left_path=Path("left.pdf"),
            right_path=Path("right.pdf"),
            left_page_count=1,
            right_page_count=1,
            pages=(page,),
        )


if __name__ == "__main__":
    unittest.main()
