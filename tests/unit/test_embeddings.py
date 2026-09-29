"""Test the embedding model."""

from src.embeddings.embedder import Embedder


embedder = Embedder()

text = "Cybersecurity risk management requires continuous assessment."

embedding = embedder.embed_text(text)

print(f"Embedding type: {type(embedding)}")
print(f"Embedding shape: {embedding.shape}")
print(f"Embedding dimensions: {len(embedding)}")
print(f"First 10 values: {embedding[:10]}")