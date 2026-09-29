"""Context building utilities for the RAG generation pipeline."""


def build_context(documents):
    """Build LLM context and a map of source references."""

    context_parts = []
    source_map = {}

    for rank, document in enumerate(documents, start=1):

        metadata = document["metadata"]

        source = metadata.get("source", "Unknown source")
        page = metadata.get("page", "Unknown page")
        chunk_id = metadata.get("chunk_id", "Unknown chunk")

        source_map[rank] = {
            "source": source,
            "page": page,
            "chunk_id": chunk_id,
        }

        context_parts.append(
            f"[Source {rank}]\n"
            f"Document: {source}\n"
            f"Page: {page}\n"
            f"Chunk: {chunk_id}\n"
            f"Content:\n{document['text']}"
        )

    context = "\n\n".join(context_parts)

    return context, source_map