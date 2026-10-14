"""Dependency-light tests for helper functions in the optional LlamaIndex adapter."""

from src.frameworks.llamaindex_retriever import normalize_metadata, stable_node_id


def test_normalize_metadata_preserves_provenance_fields():
    result = normalize_metadata({"source": "nist.pdf", "page": 4, "chunk_id": 11, "missing": None})
    assert result == {"source": "nist.pdf", "page": 4, "chunk_id": 11}


def test_stable_node_id_prefers_chunk_key():
    record = {"text": "example", "metadata": {"chunk_key": "doc-1:chunk-7", "chunk_id": 7}}
    assert stable_node_id(record) == "doc-1:chunk-7"


def test_stable_node_id_scopes_chunk_id_by_document():
    record = {"text": "example", "metadata": {"document_id": "doc-1", "chunk_id": 7}}
    assert stable_node_id(record) == "doc-1:7"


def test_stable_node_id_has_hash_fallback():
    first = stable_node_id({"text": "example", "metadata": {}}, ordinal=2)
    second = stable_node_id({"text": "example", "metadata": {}}, ordinal=2)
    assert first == second
    assert first.startswith("ekip-chunk-2-")


def test_adapter_preserves_ekip_record_contract_with_mocked_llamaindex(monkeypatch):
    """Exercise adapter wiring without downloading a reranker model."""
    import sys
    import types

    class QueryBundle:
        def __init__(self, query_str):
            self.query_str = query_str

    class BaseRetriever:
        def __init__(self):
            pass

        def retrieve(self, query):
            return self._retrieve(QueryBundle(query))

    class TextNode:
        def __init__(self, id_, text, metadata):
            self.node_id = id_
            self.text = text
            self.metadata = metadata

    class NodeWithScore:
        def __init__(self, node, score):
            self.node = node
            self.score = score

    class FakeReranker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def postprocess_nodes(self, nodes, query_str=None):
            assert query_str == "question"
            return list(reversed(nodes))

    root = types.ModuleType("llama_index")
    root.__path__ = []
    core = types.ModuleType("llama_index.core")
    core.__path__ = []
    core.QueryBundle = QueryBundle
    postprocessor = types.ModuleType("llama_index.core.postprocessor")
    postprocessor.SentenceTransformerRerank = FakeReranker
    retrievers = types.ModuleType("llama_index.core.retrievers")
    retrievers.BaseRetriever = BaseRetriever
    schema = types.ModuleType("llama_index.core.schema")
    schema.NodeWithScore = NodeWithScore
    schema.TextNode = TextNode
    root.core = core
    core.postprocessor = postprocessor
    core.retrievers = retrievers
    core.schema = schema

    for name, module in {
        "llama_index": root,
        "llama_index.core": core,
        "llama_index.core.postprocessor": postprocessor,
        "llama_index.core.retrievers": retrievers,
        "llama_index.core.schema": schema,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    class FakeHybrid:
        def retrieve(self, query, top_k=5, candidate_k=10):
            assert query == "question"
            return [
                {
                    "text": f"chunk-{number}",
                    "metadata": {"document_id": "doc", "chunk_id": number, "page": number + 1},
                    "score": 1.0 / number,
                }
                for number in (1, 2, 3)
            ][:top_k]

    adapter = __import__(
        "src.frameworks.llamaindex_retriever",
        fromlist=["LlamaIndexRerankedRetriever"],
    ).LlamaIndexRerankedRetriever(
        FakeHybrid(), candidate_k=3, reranker_model="test-model"
    )
    results = adapter.retrieve("question", top_k=1)

    assert len(results) == 1
    assert set(results[0]) == {"text", "metadata", "score"}
    assert results[0]["text"] == "chunk-3"
    assert results[0]["metadata"]["document_id"] == "doc"
    assert results[0]["metadata"]["chunk_id"] == 3
    assert adapter._postprocessor.kwargs["trust_remote_code"] is False
