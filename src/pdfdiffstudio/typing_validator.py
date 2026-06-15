from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Callable

from pdfdiffstudio.pdf_compare import PdfComparisonResult


ProgressCallback = Callable[[str, int], None]

SUPPORTED_LANGUAGES = {
    "en": "English",
    "nl": "Dutch",
}

WORD_PATTERN = re.compile("[^\\W\\d_]+(?:['\\u2019][^\\W\\d_]+)?", re.UNICODE)


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


@dataclass(frozen=True)
class _LineCandidates:
    source: str
    page_number: int
    line_number: int
    context: str
    words: tuple[tuple[str, str], ...]


def validate_typing(
    comparison: PdfComparisonResult,
    language_mode: str = "auto",
    max_issues: int = 1000,
    max_suggestion_words: int = 250,
    progress: ProgressCallback | None = None,
) -> TypingValidationResult:
    if language_mode not in {"auto", "en", "nl"}:
        raise ValueError(f"Unsupported typing validation language: {language_mode}")

    _emit(progress, "Preparing text for typing check", 0)
    lines = _collect_candidate_lines(comparison)
    total_lines = max(len(lines), 1)
    issues: list[TypingIssue] = []
    checked_words = 0
    suggestion_words = 0
    seen: set[tuple[str, int, int, str, str]] = set()

    for line_index, line in enumerate(lines, start=1):
        if line_index == 1 or line_index % 25 == 0 or line_index == total_lines:
            percent = min(99, int((line_index / total_lines) * 100))
            _emit(progress, f"Checking typing line {line_index} of {total_lines}", percent)

        language_code = _detect_language(line.words) if language_mode == "auto" else language_mode
        unknown_words = {
            normalized
            for _, normalized in line.words
            if not _is_known(language_code, normalized)
        }
        checked_words += len(line.words)

        for original, normalized in line.words:
            if normalized not in unknown_words:
                continue
            key = (line.source, line.page_number, line.line_number, language_code, normalized)
            if key in seen:
                continue
            seen.add(key)

            suggestions: tuple[str, ...] = ()
            if suggestion_words < max_suggestion_words and len(normalized) <= 24:
                suggestions = _suggestions(language_code, normalized)
                suggestion_words += 1

            issues.append(
                TypingIssue(
                    source=line.source,
                    page_number=line.page_number,
                    line_number=line.line_number,
                    language_code=language_code,
                    word=original,
                    suggestions=suggestions,
                    context=line.context,
                )
            )
            if len(issues) >= max_issues:
                _emit(progress, "Typing check reached the issue limit", 100)
                return TypingValidationResult(
                    issues=tuple(issues),
                    language_mode=language_mode,
                    checked_words=checked_words,
                    truncated=True,
                )

    _emit(progress, "Typing check complete", 100)
    return TypingValidationResult(
        issues=tuple(issues),
        language_mode=language_mode,
        checked_words=checked_words,
        truncated=False,
    )


def _collect_candidate_lines(comparison: PdfComparisonResult) -> list[_LineCandidates]:
    lines: list[_LineCandidates] = []
    for page in comparison.pages:
        for source, text in (("First PDF", page.left_text), ("Second PDF", page.right_text)):
            for line_number, line in enumerate(_split_lines(text), start=1):
                words = tuple(
                    (word, _normalize_word(word))
                    for word in _iter_words(line)
                    if _should_check(word)
                )
                if words:
                    lines.append(
                        _LineCandidates(
                            source=source,
                            page_number=page.page_number,
                            line_number=line_number,
                            context=_compact_context(line),
                            words=words,
                        )
                    )
    return lines


def _split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _iter_words(line: str):
    for match in WORD_PATTERN.finditer(line):
        yield match.group(0)


def _normalize_word(word: str) -> str:
    return word.strip("'").replace("\u2019", "'").casefold()


def _should_check(word: str) -> bool:
    stripped = word.strip("'").replace("\u2019", "'")
    if len(stripped) < 3:
        return False
    if any(character.isdigit() for character in stripped):
        return False
    if "_" in stripped:
        return False
    if stripped.isupper():
        return False
    if any(character.isupper() for character in stripped[1:]):
        return False
    return True


def _detect_language(words: tuple[tuple[str, str], ...]) -> str:
    if not words:
        return "en"
    known_counts = {
        language_code: sum(1 for _, word in words if _is_known(language_code, word))
        for language_code in SUPPORTED_LANGUAGES
    }
    if known_counts["nl"] > known_counts["en"]:
        return "nl"
    return "en"


@lru_cache(maxsize=100000)
def _is_known(language_code: str, word: str) -> bool:
    return word in _spellchecker(language_code)


@lru_cache(maxsize=10000)
def _suggestions(language_code: str, word: str) -> tuple[str, ...]:
    spellchecker = _spellchecker(language_code)
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


def _emit(progress: ProgressCallback | None, message: str, percent: int) -> None:
    if progress is not None:
        progress(message, percent)
