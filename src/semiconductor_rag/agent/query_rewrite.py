"""Expand common semiconductor Korean and English query expressions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

DOMAIN_TERM_GROUPS = (
    ("원자층 증착", "원자층 막성장", "ALD", "atomic layer deposition"),
    ("화학 기상 증착", "CVD", "chemical vapor deposition"),
    ("물리 기상 증착", "PVD", "physical vapor deposition"),
    ("포토리소그래피", "포토 공정", "lithography"),
    ("식각", "에칭", "etch", "etching"),
    ("이온 주입", "ion implantation"),
    ("화학적 기계 연마", "CMP", "chemical mechanical polishing"),
    ("초점심도", "DOF", "depth of focus"),
)


class QueryRewrite(BaseModel):
    """Describe one deterministic domain-term query expansion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    original_query: str = Field(min_length=1)
    rewritten_query: str = Field(min_length=1)
    added_terms: tuple[str, ...]


def rewrite_semiconductor_query(query: str) -> QueryRewrite:
    """Append missing aliases from matched semiconductor term groups.

    Parameters
    ----------
    query : str
        Original user question or failed search query.

    Returns
    -------
    QueryRewrite
        Original query, deterministic expanded query, and newly added aliases.

    Raises
    ------
    ValueError
        If the query is blank.
    """
    stripped_query = query.strip()
    if not stripped_query:
        raise ValueError("query must not be blank")

    normalized_query = stripped_query.casefold()
    additions: list[str] = []
    for term_group in DOMAIN_TERM_GROUPS:
        if not any(term.casefold() in normalized_query for term in term_group):
            continue
        additions.extend(
            term
            for term in term_group
            if term.casefold() not in normalized_query
            and term.casefold() not in {value.casefold() for value in additions}
        )
    rewritten_query = " ".join((stripped_query, *additions))
    return QueryRewrite(
        original_query=stripped_query,
        rewritten_query=rewritten_query,
        added_terms=tuple(additions),
    )
