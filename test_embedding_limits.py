from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf


DOCUMENT_PATH = "data/raw/nist_csf_2.0.pdf"


embedder = Embedder()

documents = load_pdf(DOCUMENT_PATH)

chunks = chunk_documents(
    documents,
    tokenizer=embedder.model.tokenizer,
    chunk_size=200,
    overlap=30,
)


tokenizer = embedder.model.tokenizer
max_sequence_length = embedder.model.max_seq_length


token_counts = []

for chunk in chunks:
    tokens = tokenizer.encode(
        chunk["text"],
        add_special_tokens=False,
    )

    token_counts.append(len(tokens))


print("=" * 80)
print("EMBEDDING MODEL LIMIT")
print("=" * 80)

print(
    f"Model max sequence length: "
    f"{max_sequence_length}"
)

print(
    f"Number of chunks: "
    f"{len(chunks)}"
)

print(
    f"Maximum model tokens: "
    f"{max(token_counts)}"
)

print(
    f"Minimum model tokens: "
    f"{min(token_counts)}"
)

print(
    f"Average model tokens: "
    f"{sum(token_counts) / len(token_counts):.2f}"
)

exceeding = [
    count
    for count in token_counts
    if count > max_sequence_length
]

print(
    f"Chunks exceeding model limit: "
    f"{len(exceeding)}"
)

print(
    f"Percentage exceeding limit: "
    f"{(len(exceeding) / len(token_counts)) * 100:.2f}%"
)

if exceeding:
    print()
    print("WARNING: Some chunks exceed the model limit.")

else:
    print()
    print("SUCCESS: All chunks fit within the model limit.")

print("=" * 80)