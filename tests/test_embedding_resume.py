from types import SimpleNamespace

import numpy as np
import pytest

from app.config import Settings
from app.matching.embeddings import EmbeddingError, SentenceTransformerEmbedder
from app.matching.skills import extract_skills


class FakeTokenizer:
    def encode(self, text, **kwargs):
        return list(map(int, text.split()))

    def decode(self, tokens, **kwargs):
        return " ".join(map(str, tokens))


def fake_model(encode):
    return SimpleNamespace(tokenizer=FakeTokenizer(), max_seq_length=10, encode=encode)


def test_interrupted_embeddings_resume_from_completed_chunks(tmp_path):
    settings = Settings(_env_file=None, embedding_cache_dir=tmp_path, embedding_batch_size=1)
    texts = ["1 2 3 4 5 6 7 8 9", "10 11", "12 13"]
    calls = []

    def interrupt(windows, **kwargs):
        calls.append(windows)
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        return np.array([[1.0, 0.0], [0.0, 1.0]])

    backend = SentenceTransformerEmbedder(settings)
    backend.model = fake_model(interrupt)
    with pytest.raises(EmbeddingError):
        backend.encode(texts)
    assert len(list(tmp_path.glob("*.npy"))) == 1

    resumed_calls = []

    def resume(windows, **kwargs):
        resumed_calls.extend(windows)
        return np.array([[0.0, 1.0]] * len(windows))

    resumed = SentenceTransformerEmbedder(settings)
    resumed.model = fake_model(resume)
    result = resumed.encode(texts)
    assert resumed_calls == ["10 11", "12 13"]
    np.testing.assert_allclose(result[0], [1 / np.sqrt(2), 1 / np.sqrt(2)])
    np.testing.assert_allclose(result[1:], [[0, 1], [0, 1]])
    assert len(list(tmp_path.glob("*.npy"))) == 3

    # A fully cached run needs neither the model nor the network.
    cached = SentenceTransformerEmbedder(settings)
    np.testing.assert_array_equal(cached.encode(texts), result)
    assert cached.model is None


def test_cached_skill_results_cannot_be_modified_by_a_caller():
    first = extract_skills("Python SQL FastAPI")
    first.clear()
    assert extract_skills("Python SQL FastAPI") == ["FastAPI", "Python", "SQL"]
