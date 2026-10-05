"""
engines/rag.py
--------------
WHAT IT DOES:
    Retrieval-Augmented Generation (RAG) over the network-operations knowledge base
    and similarity search over historical incidents.

    KnowledgeBase:
      * loads every document in data/sop_docs/*.md
      * CHUNKS each document by section ("## heading")  -> doc + section + text
      * builds TF-IDF vectors (word 1-2 grams) and retrieves by cosine similarity
      * search(query) returns: document, section, procedure text, score, reference id
      The retrieved chunks are then given to the LLM (see agents + /kb/ask) so answers are
      grounded in approved procedures and always cite the source document/section.

    HistoricalIndex:
      * vectorises past incidents (title + alarm pattern + root cause + device type)
      * similar(query, device_type, downstream_count) = text similarity
        + structural bonus (same device type, similar number of downstream sites)
      * results are EVIDENCE only - the RCA agent never assumes the cause is identical.

    WHY TF-IDF instead of a hosted embedding API: zero cost, deterministic, runs on the
    free Render tier (no 400 MB embedding model), and SOP text is keyword-heavy
    (alarm names, interface terms) where lexical retrieval performs well.
    Upgrade path: swap the vectorizer for sentence embeddings + pgvector without
    changing the agent code (same search() interface).
"""
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from ..config import DATA_DIR


class KnowledgeBase:
    def __init__(self, folder=DATA_DIR / "sop_docs"):
        self.chunks = []
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            for sec in re.split(r"\n(?=## )", text):
                lines = sec.strip().splitlines()
                if not lines or lines[0].startswith("# "):
                    continue
                heading = lines[0].lstrip("# ").strip()
                body = "\n".join(l for l in lines[1:] if not l.startswith("<!--")).strip()
                self.chunks.append({"doc_id": path.stem.split("_")[0], "document": title, "file": path.name,
                                    "section": heading, "text": body})
        self.vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        self.matrix = self.vec.fit_transform([f"{c['document']} {c['section']} {c['text']}" for c in self.chunks])

    def search(self, query: str, k: int = 4, min_score: float = 0.03):
        q = self.vec.transform([query.replace("_", " ")])
        sims = cosine_similarity(q, self.matrix)[0]
        order = sims.argsort()[::-1][:k]
        return [{**self.chunks[i], "score": round(float(sims[i]), 3),
                 "reference": f"{self.chunks[i]['doc_id']} / {self.chunks[i]['section']}"}
                for i in order if sims[i] >= min_score]

    def documents(self):
        docs = {}
        for c in self.chunks:
            docs.setdefault(c["file"], {"document": c["document"], "file": c["file"], "sections": []})["sections"].append(c["section"])
        return list(docs.values())


class HistoricalIndex:
    def __init__(self, incidents: list):
        self.items = incidents
        self.vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        corpus = [f"{h.title} {h.alarm_pattern} {h.device_type} {h.root_cause_category}".replace("_", " ") for h in incidents]
        self.matrix = self.vec.fit_transform(corpus) if incidents else None

    def similar(self, query: str, device_type: str = "", downstream_count: int = 0, k: int = 3):
        if self.matrix is None:
            return []
        sims = cosine_similarity(self.vec.transform([query.replace("_", " ")]), self.matrix)[0]
        scored = []
        for i, h in enumerate(self.items):
            bonus = (0.15 if h.device_type == device_type else 0) + (0.1 if downstream_count and abs(h.downstream_impact - downstream_count) <= 1 else 0)
            scored.append((float(sims[i]) + bonus, h))
        scored.sort(key=lambda t: -t[0])
        return [{"id": h.id, "date": h.date, "title": h.title, "root_cause": h.root_cause,
                 "root_cause_category": h.root_cause_category, "resolution": h.resolution,
                 "downstream_impact": h.downstream_impact, "mttr_minutes": h.mttr_minutes,
                 "similarity": round(s, 3),
                 "note": "Historical evidence only - current root cause must be verified independently"}
                for s, h in scored[:k] if s > 0.12]
