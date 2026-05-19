"""
Intelligent scene detection using weighted keyword scoring.

Replaces simple keyword matching with a configurable weighted scoring system
that considers:
- Keyword match count and weight
- Text length
- Complexity signals (code blocks, math expressions, error traces)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class SceneCategory:
    """A scene category with matching keywords and weights."""
    name: str
    description: str = ""
    keywords: dict[str, float] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)

    def score(self, text: str) -> float:
        """Calculate a weighted score for this category given the input text."""
        total = 0.0
        text_lower = text.lower()

        for keyword, weight in self.keywords.items():
            count = text_lower.count(keyword.lower())
            total += count * weight

        for pattern in self.patterns:
            try:
                matches = len(re.findall(pattern, text, re.IGNORECASE))
                total += matches * 5.0  # Regex patterns are high-confidence
            except re.error:
                continue

        return total


@dataclass
class DetectionResult:
    """Result of scene detection."""
    category: str
    score: float
    confidence: float  # 0.0 - 1.0
    reason: str = ""

    @property
    def is_reasoning(self) -> bool:
        return self.category == "reasoning"


class SceneDetector:
    """Detects the appropriate scene/model group for a given message.

    Usage::

        detector = SceneDetector()
        result = detector.detect(message_text)
        if result.category == "reasoning":
            # use reasoning model group
    """

    # Built-in reasoning keywords with weights.
    # Higher weight = stronger signal.
    DEFAULT_REASONING_KEYWORDS: ClassVar[dict[str, float]] = {
        # Technical keywords (high confidence)
        "写一个": 15.0,
        "实现一个": 15.0,
        "代码": 12.0,
        "编程": 12.0,
        "脚本": 12.0,
        "算法": 10.0,
        # Problem solving
        "bug": 10.0,
        "报错": 10.0,
        "推导": 8.0,
        "分析": 6.0,
        "为什么": 6.0,
        # Math & logic
        "数学": 8.0,
        "逻辑": 8.0,
        "推理": 8.0,
        # Languages
        "python": 7.0,
        "javascript": 7.0,
        "java": 7.0,
        "c++": 7.0,
        "typescript": 7.0,
        "golang": 7.0,
        "rust": 7.0,
        "react": 7.0,
        "vue": 7.0,
        # Analysis
        "解释": 5.0,
        "原理": 5.0,
        "怎么": 3.0,
        "如何": 3.0,
    }

    # Patterns for detecting complex content
    COMPLEXITY_PATTERNS: ClassVar[list[str]] = [
        r"```[\s\S]*?```",  # Code blocks
        r"`[^`]+`",  # Inline code
        r"Traceback\s*\(.*\)",  # Python traceback
        r"at\s+[\w.$]+\(",  # Java stack trace
        r"Error[: ]",  # Error patterns
        r"Exception[: ]",  # Exception
        r"\bdef\s+\w+\s*\(.*\)\s*:",  # Python function def
        r"\bfunction\s+\w+\s*\(.*\)",  # JS function
        r"\\frac\{",  # LaTeX math
        r"\$[^$]+\$",  # Math expressions
    ]

    # Thresholds
    MIN_REASONING_SCORE: ClassVar[float] = 10.0
    """Minimum score to classify as reasoning."""
    LONG_TEXT_THRESHOLD: ClassVar[int] = 150
    """Text length above which we treat as reasoning candidate."""
    VERY_LONG_TEXT_THRESHOLD: ClassVar[int] = 500
    """Text length above which we're very confident it's reasoning."""
    LONG_TEXT_BASE_SCORE: ClassVar[float] = 8.0
    """Base score for long text."""
    VERY_LONG_TEXT_SCORE: ClassVar[float] = 18.0
    """Base score for very long text."""

    def __init__(self, custom_keywords: dict[str, float] | None = None):
        self._daily = SceneCategory(
            name="daily",
            description="Daily chat (lightweight models)",
        )
        self._reasoning = SceneCategory(
            name="reasoning",
            description="Reasoning / complex tasks (powerful models)",
            keywords={**self.DEFAULT_REASONING_KEYWORDS, **(custom_keywords or {})},
            patterns=list(self.COMPLEXITY_PATTERNS),
        )

    def detect(self, text: str) -> DetectionResult:
        """Detect the appropriate scene for a message.

        Args:
            text: The user's message text.

        Returns:
            DetectionResult with category and confidence.
        """
        reasoning_score = 0.0
        matched_signals: list[str] = []

        # 1. Keyword scoring
        text_lower = text.lower()
        for keyword, weight in self._reasoning.keywords.items():
            count = text_lower.count(keyword.lower())
            if count > 0:
                reasoning_score += count * weight
                matched_signals.append(f"keyword:{keyword}(x{count})")

        # 2. Pattern matching (code blocks, math, traces)
        for pattern in self.COMPLEXITY_PATTERNS:
            try:
                matches = re.findall(pattern, text)
                if matches:
                    reasoning_score += len(matches) * 5.0
                    matched_signals.append(f"pattern:{pattern[:20]}(x{len(matches)})")
            except re.error:
                continue

        # 3. Text length bonus
        text_len = len(text)
        if text_len >= self.VERY_LONG_TEXT_THRESHOLD:
            reasoning_score += self.VERY_LONG_TEXT_SCORE
            matched_signals.append(f"length:very_long({text_len})")
        elif text_len >= self.LONG_TEXT_THRESHOLD:
            reasoning_score += self.LONG_TEXT_BASE_SCORE
            matched_signals.append(f"length:long({text_len})")

        # 4. Decision
        if reasoning_score >= self.MIN_REASONING_SCORE:
            confidence = min(1.0, reasoning_score / 40.0)
            return DetectionResult(
                category="reasoning",
                score=reasoning_score,
                confidence=confidence,
                reason=f"Matched signals: {', '.join(matched_signals[:5])}",
            )

        return DetectionResult(
            category="daily",
            score=0.0,
            confidence=min(1.0, (self.MIN_REASONING_SCORE - reasoning_score) / self.MIN_REASONING_SCORE),
            reason="No reasoning signals detected",
        )

    def add_keyword(self, keyword: str, weight: float) -> None:
        """Add or update a keyword weight."""
        self._reasoning.keywords[keyword] = weight

    def remove_keyword(self, keyword: str) -> None:
        self._reasoning.keywords.pop(keyword, None)  # type: ignore[arg-type]