from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

from pdfdiffstudio.pdf_compare import PdfComparisonResult


SUPPORTED_LANGUAGES = {
    "en": "English",
    "nl": "Dutch",
}

WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’][A-Za-zÀ-ÖØ-öø-ÿ]+)?")
SKIP_WORD_PATTERN = re.compile(r"^[A-ZÀ-ÖØ-Þ]{2,}$")


@dataclass(frozen=True)
class TypingIssue:
    source: str
    page_number: int
    line_number: int
    language_code: str
    word: str
    suggestions: tuple[str, ...]
    context: str

    @property
    def language_name(self) -> str:
        return SUPPORTED_LANGUAGES.get(self.language_code, self.language_code)


@dataclass(frozen=True)
class TypingValidationResult:
    issues: tuple[TypingIssue, ...]
    language_mode: str
    checked_words: int
    truncated: bool = False


def validate_typing(
    comparison: PdfComparisonResult,
    language_mode: str = "auto",
    max_issues: int = 1000,
) -> TypingValidationResult:
    if language_mode not in {"auto", "en", "nl"}:
        raise ValueError(f"Unsupported typing validation language: {language_mode}")

    issues: list[TypingIssue] = []
    checked_words = 0
    seen: set[tuple[str, int, int, str, str]] = set()

    for page in comparison.pages:
        for source, text in (("First PDF", page.left_text), ("Second PDF", page.right_text)):
            for line_number, line in enumerate(_split_lines(text), start=1):
                words = list(_iter_words(line))
                if not words:
                    continue
                language_code = _detect_language(words) if language_mode == "auto" else language_mode
                spellchecker = _spellchecker(language_code)
                normalized_words = [_normalize_word(word) for word in words]
                candidates = [
                    normalized
                    for original, normalized in zip(words, normalized_words)
                    if _should_check(original)
                ]
                if not candidates:
                    continue

                unknown_words = spellchecker.unknown(candidates)
                checked_words += len(candidates)

                for original, normalized in zip(words, normalized_words):
                    if normalized not in unknown_words:
                        continue
                    key = (source, page.page_number, line_number, language_code, normalized)
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(
                        TypingIssue(
                            source=source,
                            page_number=page.page_number,
                            line_number=line_number,
                            language_code=language_code,
                            word=original,
                            suggestions=_suggestions(spellchecker, normalized),
                            context=_compact_context(line),
                        )
                    )
                    if len(issues) >= max_issues:
                        return TypingValidationResult(
                            issues=tuple(issues),
                            language_mode=language_mode,
                            checked_words=checked_words,
                            truncated=True,
                        )

    return TypingValidationResult(
        issues=tuple(issues),
        language_mode=language_mode,
        checked_words=checked_words,
        truncated=False,
    )


def _split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _iter_words(line: str):
    for match in WORD_PATTERN.finditer(line):
        yield match.group(0)


def _normalize_word(word: str) -> str:
    return word.strip("'’").casefold()


def _should_check(word: str) -> bool:
    if len(word) < 3:
        return False
    if any(character.isdigit() for character in word):
        return False
    if "_" in word:
        return False
    if SKIP_WORD_PATTERN.match(word):
        return False
    return True


def _detect_language(words: list[str]) -> str:
    normalized = [_normalize_word(word) for word in words if _should_check(word)]
    if not normalized:
        return "en"
    known_counts = {
        language_code: sum(1 for word in normalized if word in _spellchecker(language_code))
        for language_code in SUPPORTED_LANGUAGES
    }
    return max(known_counts, key=known_counts.get)


def _suggestions(spellchecker, word: str) -> tuple[str, ...]:
    correction = spellchecker.correction(word)
    candidates = spellchecker.candidates(word) or set()
    ordered: list[str] = []
    if correction:
        ordered.append(correction)
    for candidate in sorted(candidates):
        if candidate not in ordered:
            ordered.append(candidate)
        if len(ordered) >= 5:
            break
    return tuple(ordered[:5])


def _compact_context(line: str, limit: int = 180) -> str:
    compacted = " ".join(line.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


@lru_cache(maxsize=2)
def _spellchecker(language_code: str):
    try:
        from spellchecker import SpellChecker
    except ImportError as exc:
        raise RuntimeError(
            "Typing validation requires pyspellchecker. "
            "Install dependencies with: python -m pip install -r requirements.txt"
        ) from exc
    return SpellChecker(language=language_code)
