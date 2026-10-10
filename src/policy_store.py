"""Clause level retrieval over the T&E policy.

The policy is chunked by clause identifier (TE-xx.y) rather than by a fixed
token window. A finance clause is a natural semantic unit, and chunking on it
means every retrieved passage can be cited by number, which is what TE-11.2
requires of a disallowance.

Retrieval is TF-IDF with cosine similarity, implemented in about forty lines
of standard library code so the project installs and runs with no vector
database and no embedding service.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

from . import config as C

CLAUSE_RE = re.compile(r"^(TE-\d{2}\.\d+)\s+(.*)$")
SECTION_RE = re.compile(r"^###\s+(TE-\d{2})\.\s*(.+)$")
TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for",
    "by", "with", "at", "as", "be", "that", "this", "it", "not", "from", "per",
    "where", "any", "all", "must", "may", "shall", "which", "than", "each",
}


@dataclass
class Clause:
    clause_id: str
    section_id: str
    section_title: str
    text: str

    def cite(self) -> str:
        return f"{self.clause_id} ({self.section_title})"


def _tokenize(text: str) -> List[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


class PolicyStore:
    def __init__(self, path: Path | str = C.POLICY_PATH):
        self.path = Path(path)
        self.clauses: List[Clause] = []
        self._df: Counter = Counter()
        self._vectors: List[Dict[str, float]] = []
        self._load()

    # -- loading -----------------------------------------------------------

    def _load(self) -> None:
        raw = self.path.read_text(encoding="utf-8")
        section_id, section_title = "TE-00", "Preamble"
        buffer_id, buffer_text = None, []

        def flush():
            if buffer_id:
                self.clauses.append(Clause(buffer_id, section_id, section_title,
                                           " ".join(buffer_text).strip()))

        for line in raw.splitlines():
            stripped = line.strip()
            m_sec = SECTION_RE.match(stripped)
            if m_sec:
                flush()
                buffer_id, buffer_text = None, []
                section_id, section_title = m_sec.group(1), m_sec.group(2).strip()
                continue
            m_cl = CLAUSE_RE.match(stripped)
            if m_cl:
                flush()
                buffer_id, buffer_text = m_cl.group(1), [m_cl.group(2)]
                continue
            if stripped and buffer_id:
                buffer_text.append(stripped)
        flush()

        # build the TF-IDF index
        docs = [_tokenize(f"{c.clause_id} {c.section_title} {c.text}") for c in self.clauses]
        for d in docs:
            self._df.update(set(d))
        n = max(1, len(docs))
        for d in docs:
            tf = Counter(d)
            length = max(1, len(d))
            vec = {t: (count / length) * math.log((1 + n) / (1 + self._df[t])) + 1e-9
                   for t, count in tf.items()}
            self._vectors.append(_normalize(vec))

    # -- retrieval ---------------------------------------------------------

    def search(self, query: str, k: int = 4) -> List[Tuple[Clause, float]]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        n = max(1, len(self.clauses))
        tf = Counter(q_tokens)
        qvec = _normalize({t: (c / len(q_tokens)) * math.log((1 + n) / (1 + self._df[t])) + 1e-9
                           for t, c in tf.items()})
        scored = [(self.clauses[i], _cosine(qvec, self._vectors[i]))
                  for i in range(len(self.clauses))]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s in scored[:k] if s[1] > 0]

    def get(self, clause_id: str) -> Clause | None:
        for c in self.clauses:
            if c.clause_id == clause_id:
                return c
        return None

    def context_for(self, query: str, k: int = 4) -> str:
        """A compact citable context block for a language model prompt."""
        hits = self.search(query, k)
        if not hits:
            return "(no matching policy clause found)"
        return "\n".join(f"[{c.clause_id}] {c.text}" for c, _ in hits)

    def __len__(self) -> int:
        return len(self.clauses)


def _normalize(vec: Dict[str, float]) -> Dict[str, float]:
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


@lru_cache(maxsize=1)
def get_policy_store() -> PolicyStore:
    return PolicyStore()
