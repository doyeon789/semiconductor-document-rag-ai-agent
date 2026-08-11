"""Small in-memory BM25 index for page-aware chunks."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from semiconductor_rag.domain import Chunk
from semiconductor_rag.retrieval.models import SearchHit

WORD_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+(?:[./-][0-9A-Za-z가-힣]+)*")
HANGUL_PATTERN = re.compile(r"[가-힣]")


def tokenize_search_text(value: str) -> tuple[str, ...]:
    """Normalize search text into exact and Korean character tokens.

    Korean two-character tokens make common particles less likely to hide a
    matching technical term. English terms, abbreviations, and equipment codes
    retain their full normalized form.

    Parameters
    ----------
    value : str
        Query or chunk text.

    Returns
    -------
    tuple[str, ...]
        Case-folded search tokens in source order.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    for token in WORD_PATTERN.findall(normalized):
        tokens.append(token)
        if HANGUL_PATTERN.search(token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tuple(tokens)


class BM25Index:
    """Rank an immutable collection of chunks with the BM25 formula.

    Parameters
    ----------
    chunks : collections.abc.Sequence[Chunk]
        Chunks to index in memory.
    k1 : float, default=1.5
        Term-frequency saturation parameter.
    b : float, default=0.75
        Document-length normalization parameter.

    Raises
    ------
    ValueError
        If either BM25 parameter is outside its supported range.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """Build term frequencies and document frequencies for the chunks."""
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between zero and one")

        self._chunks = tuple(chunks)
        self._k1 = k1
        self._b = b
        tokenized = tuple(tokenize_search_text(chunk.text) for chunk in self._chunks)
        self._term_frequencies = tuple(Counter(tokens) for tokens in tokenized)
        self._document_lengths = tuple(len(tokens) for tokens in tokenized)
        self._average_document_length = (
            sum(self._document_lengths) / len(self._document_lengths)
            if self._document_lengths
            else 0.0
        )
        self._document_frequencies = Counter(
            token for tokens in tokenized for token in set(tokens)
        )

    def search(self, query: str, top_k: int = 5) -> tuple[SearchHit, ...]:
        """Return the highest-scoring chunks for a non-empty query.

        Parameters
        ----------
        query : str
            User search query.
        top_k : int, default=5
            Maximum number of results to return.

        Returns
        -------
        tuple[SearchHit, ...]
            Positive-score hits ordered by score and stable chunk identifier.

        Raises
        ------
        ValueError
            If the query is blank or ``top_k`` is not positive.
        """
        query_tokens = tokenize_search_text(query)
        if not query_tokens:
            raise ValueError("query must contain searchable text")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        query_term_frequencies = Counter(query_tokens)
        hits = tuple(
            SearchHit(
                chunk=chunk,
                score=self._score_document(index, query_term_frequencies),
            )
            for index, chunk in enumerate(self._chunks)
        )
        positive_hits = (hit for hit in hits if hit.score > 0)
        ranked_hits = sorted(
            positive_hits,
            key=lambda hit: (-hit.score, str(hit.chunk.chunk_id)),
        )
        return tuple(ranked_hits[:top_k])

    def _score_document(
        self,
        document_index: int,
        query_term_frequencies: Counter[str],
    ) -> float:
        """Calculate one document's BM25 score.

        Parameters
        ----------
        document_index : int
            Position of the indexed chunk.
        query_term_frequencies : collections.Counter[str]
            Normalized query term counts.

        Returns
        -------
        float
            Non-negative BM25 relevance score.
        """
        if not self._chunks or self._average_document_length == 0:
            return 0.0

        term_frequencies = self._term_frequencies[document_index]
        document_length = self._document_lengths[document_index]
        score = 0.0
        for term, query_frequency in query_term_frequencies.items():
            term_frequency = term_frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            document_frequency = self._document_frequencies[term]
            inverse_document_frequency = math.log(
                1
                + (len(self._chunks) - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            length_normalization = (
                1
                - self._b
                + self._b * (document_length / self._average_document_length)
            )
            saturation = (term_frequency * (self._k1 + 1)) / (
                term_frequency + self._k1 * length_normalization
            )
            score += query_frequency * inverse_document_frequency * saturation
        return score
