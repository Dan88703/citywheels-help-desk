"""Keyword search over the Markdown policy files.

Each file is split into sections at its "## " headings, and every section is
scored against the question with BM25 (the classic ranking formula behind
many search engines). With ~20 short sections, embeddings would add an API
dependency and non-determinism for little gain; a keyword ranker is fast,
free, testable and easy to explain.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from helpdesk.config import POLICIES_DIR

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "is", "are",
    "be", "it", "i", "my", "me", "we", "you", "your", "do", "does", "can", "what", "when",
    "how", "if", "this", "that", "there", "get", "will", "would", "much", "many", "have",
    "has", "from", "by", "as", "about", "any", "s",
}

# Customers rarely use the same words as the documents. These small maps
# bridge the most common gaps (e.g. "open" vs. the "When are you open?" FAQ).
SYNONYMS = {
    "ebike": ["e-bike", "electric"],
    "e-bike": ["electric"],
    "electric": ["e-bike"],
    "cost": ["price"],
    "costs": ["price"],
    "expensive": ["price"],
    "cheap": ["price"],
    "money": ["refund", "price"],
    "back": ["refund"],
    "cancel": ["cancelling", "refund"],
    "cancellation": ["cancelling", "refund"],
    "hours": ["open"],
    "opening": ["open"],
    "close": ["open", "closed"],
    "sunday": ["sundays", "open"],
    "saturday": ["open"],
    "old": ["age"],
    "year": ["age"],
    "years": ["age"],
    "child": ["kids", "children", "age"],
    "kid": ["kids", "children"],
    "son": ["kids", "children", "age"],
    "daughter": ["kids", "children", "age"],
    "late": ["late", "return"],
    "storm": ["weather"],
    "rain": ["weather"],
    "broken": ["breaks"],
    "accident": ["breaks", "accident"],
    "stolen": ["stolen", "lost"],
    "pay": ["payment"],
    "cash": ["payment", "pay"],
    "change": ["changing"],
    "reschedule": ["changing"],
}


@dataclass
class Section:
    source: str   # file name, e.g. "faq.md"
    title: str    # "File title > Section heading"
    text: str     # full Markdown of the section


def _stem(token: str) -> str:
    # Very light stemming so "bikes"/"bike" and "refunds"/"refund" match.
    for suffix in ("ies", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


_STEMMED_SYNONYMS: dict[str, list[str]] = {}
for _key, _values in SYNONYMS.items():
    _STEMMED_SYNONYMS.setdefault(_stem(_key), []).extend(_values)


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def expand_query(tokens: list[str]) -> list[str]:
    # Query tokens are already stemmed ("hours" -> "hour"), so the synonym
    # keys must be looked up in stemmed form too.
    expanded = list(tokens)
    for t in tokens:
        expanded.extend(_stem(s) for s in _STEMMED_SYNONYMS.get(t, []))
    return expanded


def load_sections(policies_dir: Path = POLICIES_DIR) -> list[Section]:
    sections = []
    for path in sorted(policies_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        doc_title = title_match.group(1).strip() if title_match else path.stem
        # Split right before every "## " heading; keep text before the first one too.
        parts = re.split(r"(?m)^(?=## )", content)
        for part in parts:
            part = part.strip()
            heading_match = re.match(r"## (.+)", part)
            if heading_match:
                title = f"{doc_title} > {heading_match.group(1).strip()}"
            else:
                # Intro text before the first section (strip the "# Title" line).
                part = re.sub(r"^# .+\n?", "", part).strip()
                title = doc_title
            if part:
                sections.append(Section(source=path.name, title=title, text=part))
    return sections


class PolicySearch:
    """BM25 ranking over policy sections.

    BM25 rewards a section for containing query words, more for rare words
    (IDF: "refund" matters more than "bike", which is everywhere), with
    diminishing returns for repeats (k1) and a correction so long sections
    don't win just by being long (b). Words in the heading count twice,
    because headings here are short summaries like "Are there age limits?".
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, sections: list[Section] | None = None):
        self.sections = sections if sections is not None else load_sections()
        self._docs = [tokenize(s.text) + tokenize(s.title) for s in self.sections]
        self._tf = [Counter(d) for d in self._docs]
        self._avg_len = sum(len(d) for d in self._docs) / max(len(self._docs), 1)
        df = Counter(t for d in self._docs for t in set(d))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def _score(self, query_tokens: list[str], i: int) -> float:
        tf, length = self._tf[i], len(self._docs[i])
        score = 0.0
        for t in set(query_tokens):
            if t not in tf:
                continue
            freq = tf[t]
            denom = freq + self.K1 * (1 - self.B + self.B * length / self._avg_len)
            score += self._idf.get(t, 0.0) * freq * (self.K1 + 1) / denom
        return score

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        tokens = expand_query(tokenize(query))
        scored = [(self._score(tokens, i), i) for i in range(len(self.sections))]
        scored = [(s, i) for s, i in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "source": self.sections[i].source,
                "section": self.sections[i].title,
                "score": round(s, 3),
                "text": self.sections[i].text,
            }
            for s, i in scored[:top_k]
        ]
