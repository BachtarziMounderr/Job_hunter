"""Local multilingual vectors, caching and cosine math; no external inference API."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Actionable error without network or credential diagnostics."""


class Embedder(Protocol):
    version: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


def cosine_matrix(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Pairwise cosine; zero vectors give zero, invalid values are rejected."""
    if left.ndim != 2 or right.ndim != 2 or left.shape[1] != right.shape[1]:
        raise ValueError("Expected two matrices with the same vector dimension")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Embeddings must be finite")
    left_norm = np.linalg.norm(left, axis=1, keepdims=True)
    right_norm = np.linalg.norm(right, axis=1, keepdims=True)
    left_unit = np.divide(
        left, left_norm, out=np.zeros_like(left, dtype=float), where=left_norm != 0
    )
    right_unit = np.divide(
        right, right_norm, out=np.zeros_like(right, dtype=float), where=right_norm != 0
    )
    return np.clip(left_unit @ right_unit.T, -1, 1)


class TfidfEmbedder:
    """Explicit lexical baseline for offline demos; never an implicit NLP fallback."""

    version = "tfidf-char-3-5-v1"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0))
        corpus_hash = hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()[
            :16
        ]
        self.version = "tfidf-char-3-5-v1:" + corpus_hash
        try:
            return (
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(3, 5), max_features=30000, sublinear_tf=True
                )
                .fit_transform(texts)
                .toarray()
            )
        except ValueError as exc:
            raise EmbeddingError("No usable text for TF-IDF") from exc


class SentenceTransformerEmbedder:
    """CPU model with token-window pooling so long descriptions aren't silently truncated."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = None
        self.version = f"st:{settings.embedding_model}@{settings.embedding_revision}:token-pool-v1"

    def _load(self):
        if self.model is None:
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(self.settings.embedding_cpu_threads)
                self.model = SentenceTransformer(
                    self.settings.embedding_model,
                    revision=self.settings.embedding_revision,
                    cache_folder=str(self.settings.model_cache_dir),
                    device="cpu",
                    trust_remote_code=False,
                    local_files_only=self.settings.embedding_local_files_only,
                )
            except Exception as exc:
                raise EmbeddingError(
                    "Cannot load multilingual model. Install .[ml], check network/model revision, "
                    "or explicitly select EMBEDDING_BACKEND=tfidf for a lexical demo."
                ) from exc
        return self.model

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0))
        cache: Path = self.settings.embedding_cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        paths = [
            cache / (hashlib.sha256((self.version + text).encode()).hexdigest() + ".npy")
            for text in texts
        ]
        vectors: list[np.ndarray | None] = []
        for path in paths:
            try:
                vector = np.load(path, allow_pickle=False) if path.exists() else None
                if vector is not None and (vector.ndim != 1 or not np.isfinite(vector).all()):
                    vector = None
            except (OSError, ValueError):
                vector = None
            vectors.append(vector)
        missing = [index for index, vector in enumerate(vectors) if vector is None]
        if missing:
            model = self._load()
            max_tokens = max(8, int(model.max_seq_length) - 2)
            # Persist bounded groups so an interruption loses only the current group.
            chunk_size = self.settings.embedding_batch_size
            logger.info("Embedding cache: %d/%d texts", len(texts) - len(missing), len(texts))
            for start in range(0, len(missing), chunk_size):
                chunk = missing[start : start + chunk_size]
                windows: list[str] = []
                owners: dict[int, list[int]] = {index: [] for index in chunk}
                for index in chunk:
                    tokens = model.tokenizer.encode(
                        texts[index], add_special_tokens=False, verbose=False
                    )
                    for offset in range(0, max(1, len(tokens)), max_tokens):
                        owners[index].append(len(windows))
                        windows.append(
                            model.tokenizer.decode(
                                tokens[offset : offset + max_tokens], skip_special_tokens=True
                            )
                        )
                try:
                    encoded = model.encode(
                        windows,
                        batch_size=self.settings.embedding_batch_size,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                except Exception as exc:
                    raise EmbeddingError("Local embedding computation failed") from exc
                for index in chunk:
                    pooled = np.mean(encoded[owners[index]], axis=0)
                    norm = np.linalg.norm(pooled)
                    vector = pooled / norm if norm else pooled
                    vectors[index] = vector.astype(np.float32)
                    # Atomic replacement prevents partially written cache entries.
                    temporary = paths[index].with_suffix(".tmp")
                    with temporary.open("wb") as stream:
                        np.save(stream, vectors[index], allow_pickle=False)
                    temporary.replace(paths[index])
                logger.info(
                    "Embedding progress: %d/%d texts saved",
                    len(texts) - len(missing) + start + len(chunk),
                    len(texts),
                )
        return np.stack(vectors)


def create_embedder(settings: Settings) -> Embedder:
    return (
        TfidfEmbedder()
        if settings.embedding_backend == "tfidf"
        else SentenceTransformerEmbedder(settings)
    )
