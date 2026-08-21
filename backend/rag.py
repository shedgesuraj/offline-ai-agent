"""Small dependency-free local vector retrieval layer.

Uses a deterministic hashed bag-of-words embedding and cosine similarity, so
no cloud/vector service is required. It is intentionally simple and transparent
for an offline V1; documents remain in SQLite and are user-controlled.
"""
import hashlib
import math
import re
from backend.db import get_memories, get_documents

DIM = 384
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def tokens(text):
    return TOKEN_RE.findall((text or "").lower())


def vector(text):
    v = [0.0] * DIM
    for token in tokens(text):
        idx = int(hashlib.blake2b(token.encode("utf-8"), digest_size=4).hexdigest(), 16) % DIM
        v[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


def similarity(query, text):
    a, b = vector(query), vector(text)
    return sum(x * y for x, y in zip(a, b))


def retrieve(username, query, top_k=5):
    candidates = []
    for item in get_documents(username):
        candidates.append((similarity(query, item["content"]), f'DOCUMENT: {item["path"]}\n{item["content"][:6000]}'))
    for item in get_memories(username):
        candidates.append((similarity(query, item["content"]), f'MEMORY:\n{item["content"]}'))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [text for score, text in candidates[:top_k] if score > 0]
