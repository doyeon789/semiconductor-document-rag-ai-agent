"""Classify control-seeking questions before document retrieval."""

from __future__ import annotations

import re

from semiconductor_rag.agent.models import AgentQuestionClass

CONTROL_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|above)\s+instructions?",
        r"(?:이전|위의|모든)\s*(?:지시|명령|규칙)(?:을|를)?\s*무시",
        r"(?:system\s+prompt|developer\s+message)",
        r"(?:시스템\s*프롬프트|개발자\s*메시지)",
        r"(?:reveal|show|print)\s+(?:the\s+)?(?:hidden\s+)?(?:prompt|instructions?)",
        r"(?:프롬프트|숨겨진\s*지시).{0,16}(?:출력|공개|보여)",
    )
)


def classify_agent_question(question: str) -> AgentQuestionClass:
    """Classify a question as a document query or control-seeking input.

    Parameters
    ----------
    question : str
        Non-blank user question.

    Returns
    -------
    AgentQuestionClass
        Classification used by the first agent routing decision.

    Raises
    ------
    ValueError
        If the question is blank.
    """
    stripped_question = question.strip()
    if not stripped_question:
        raise ValueError("question must not be blank")
    if any(
        pattern.search(stripped_question) for pattern in CONTROL_INSTRUCTION_PATTERNS
    ):
        return AgentQuestionClass.PROMPT_INJECTION
    return AgentQuestionClass.DOCUMENT_QUERY
