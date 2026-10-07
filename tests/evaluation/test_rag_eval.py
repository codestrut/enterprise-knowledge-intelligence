"""End-to-end evaluation of the RAG pipeline."""

from src.evaluation.retrieval_eval import EVALUATION_DATASET
from src.rag_pipeline import RAGPipeline


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def evaluate_query(pipeline, item):
    """Run one evaluation query and calculate deterministic metrics."""

    result = pipeline.query(item["query"])

    grounding = result["grounding"]

    total_claims = len(grounding)

    grounded_claims = sum(
        evaluation["status"] == "grounded"
        for evaluation in grounding
    )

    unsupported_claims = sum(
        evaluation["status"] == "unsupported"
        for evaluation in grounding
    )

    contradicted_claims = sum(
        evaluation["status"] == "contradicted"
        for evaluation in grounding
    )

    fully_grounded = (
        total_claims > 0
        and grounded_claims == total_claims
    )

    citation_valid = (
        len(result["invalid_citations"]) == 0
    )

    return {
        "query": item["query"],
        "answerable": item["answerable"],
        "refused": result["refused"],
        "answered": not result["refused"],
        "citation_valid": citation_valid,
        "citation_count": len(result["citations"]),
        "invalid_citation_count": len(
            result["invalid_citations"]
        ),
        "total_claims": total_claims,
        "grounded_claims": grounded_claims,
        "unsupported_claims": unsupported_claims,
        "contradicted_claims": contradicted_claims,
        "fully_grounded": fully_grounded,
        "evidence_score": result["evidence"]["score"],
        "evidence_sufficient": result["evidence"]["sufficient"],
        "result": result,
    }


def test_end_to_end_rag_evaluation():
    """Evaluate the complete RAG pipeline against the benchmark."""

    pipeline = RAGPipeline(PDF_PATH)

    evaluations = [
        evaluate_query(pipeline, item)
        for item in EVALUATION_DATASET
    ]

    assert len(evaluations) == len(EVALUATION_DATASET)

    answerable_evaluations = [
        evaluation
        for evaluation in evaluations
        if evaluation["answerable"]
    ]

    unanswerable_evaluations = [
        evaluation
        for evaluation in evaluations
        if not evaluation["answerable"]
    ]

    correct_answerable_answers = sum(
        not evaluation["refused"]
        for evaluation in answerable_evaluations
    )

    correct_refusals = sum(
        evaluation["refused"]
        for evaluation in unanswerable_evaluations
    )

    valid_citations = sum(
        evaluation["citation_valid"]
        for evaluation in evaluations
    )

    total_claims = sum(
        evaluation["total_claims"]
        for evaluation in evaluations
    )

    grounded_claims = sum(
        evaluation["grounded_claims"]
        for evaluation in evaluations
    )

    unsupported_claims = sum(
        evaluation["unsupported_claims"]
        for evaluation in evaluations
    )

    contradicted_claims = sum(
        evaluation["contradicted_claims"]
        for evaluation in evaluations
    )

    fully_grounded_answers = sum(
        evaluation["fully_grounded"]
        for evaluation in evaluations
    )

    answerable_count = len(answerable_evaluations)
    unanswerable_count = len(unanswerable_evaluations)
    total_count = len(evaluations)

    answer_success_rate = (
        correct_answerable_answers / answerable_count
        if answerable_count
        else 0.0
    )

    refusal_accuracy = (
        correct_refusals / unanswerable_count
        if unanswerable_count
        else 0.0
    )

    citation_validity_rate = (
        valid_citations / total_count
        if total_count
        else 0.0
    )

    grounded_claim_rate = (
        grounded_claims / total_claims
        if total_claims
        else 0.0
    )

    unsupported_claim_rate = (
        unsupported_claims / total_claims
        if total_claims
        else 0.0
    )

    contradicted_claim_rate = (
        contradicted_claims / total_claims
        if total_claims
        else 0.0
    )

    grounded_answer_rate = (
        fully_grounded_answers / answerable_count
        if answerable_count
        else 0.0
    )

    assert 0.0 <= answer_success_rate <= 1.0
    assert 0.0 <= refusal_accuracy <= 1.0
    assert 0.0 <= citation_validity_rate <= 1.0
    assert 0.0 <= grounded_claim_rate <= 1.0
    assert 0.0 <= unsupported_claim_rate <= 1.0
    assert 0.0 <= contradicted_claim_rate <= 1.0
    assert 0.0 <= grounded_answer_rate <= 1.0

    # These are core correctness guarantees already established
    # by the locked RAG evaluation benchmark.
    assert answer_success_rate == 1.0
    assert refusal_accuracy == 1.0
    assert citation_validity_rate == 1.0
    assert contradicted_claim_rate == 0.0