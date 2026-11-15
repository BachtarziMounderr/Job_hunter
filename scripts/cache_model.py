"""Download the pinned multilingual model at image build time, without CVs or API keys."""

import logging

from app.config import Settings
from app.matching.embeddings import SentenceTransformerEmbedder

if __name__ == "__main__":
    settings = Settings()
    embedder = SentenceTransformerEmbedder(settings)
    embedder._load()
    logging.basicConfig(level=logging.INFO)
    logging.info("Multilingual embedding model cached")
