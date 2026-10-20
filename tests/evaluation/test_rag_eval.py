"""End-to-end evaluation of the RAG pipeline."""

from src.evaluation.retrieval_eval import EVALUATION_DATASET
from src.rag_pipeline import RAGPipeline


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def evaluate_query(pipeline, item):
    """Evaluate one query and collect its grounding metrics."""
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
    uncited_claims = sum(
        evaluation["status"] == "uncited"
        for evaluation in grounding
    )

    fully_grounded = (
        total_claims > 0
        and grounded_claims == total_claims
    )
    citation_valid = len(result["invalid_citations"]) == 0

    return {
        "query": item["query"],
        "answerable": item["answerable"],
        "refused": result["refused"],
        "answered": not result["refused"],
        "citation_valid": citation_valid,
        "citation_count": len(result["citations"]),
        "invalid_citation_count": len(result["invalid_citations"]),
        "total_claims": total_claims,
        "grounded_claims": grounded_claims,
        "unsupported_claims": unsupported_claims,
        "contradicted_claims": contradicted_claims,
        "uncited_claims": uncited_claims,
        "fully_grounded": fully_grounded,
        "evidence_score": result["evidence"]["score"],
        "evidence_sufficient": result["evidence"]["sufficient"],
        "result": result,
    }


def print_grounding_diagnostics(evaluations):
    """Print evidence behind unsupported and contradicted claims."""
    found_issue = False

    for evaluation in evaluations:
        result = evaluation["result"]

        for claim_result in result["grounding"]:
            claim_status = claim_result["status"]

            if claim_status == "uncited":
                found_issue = True
                print("\n" + "=" * 100)
                print("QUERY:", evaluation["query"])
                print("UNCITED CLAIM (not verified):", claim_result["claim"])
                continue

            if claim_status not in {"unsupported", "contradicted"}:
                continue

            for atomic in claim_result.get("atomic_claims", []):
                atomic_status = atomic["status"]

                if atomic_status not in {"unsupported", "contradicted"}:
                    continue

                found_issue = True

                print("\n" + "=" * 100)
                print("QUERY:", evaluation["query"])
                print("ANSWERABLE:", evaluation["answerable"])
                print("ANSWER:", result["answer"])
                print("CLAIM:", claim_result["claim"])
                print("CLAIM STATUS:", claim_status)
                print("ATOMIC CLAIM:", atomic["claim"])
                print("ATOMIC STATUS:", atomic_status)

                sources = atomic.get("sources", [])

                if not sources:
                    print("SOURCES: No source evaluations recorded.")

                for source in sources:
                    print("\nSOURCE NUMBER:", source.get("source_number"))
                    print("SOURCE LABEL:", source.get("label"))

                    evidence_items = source.get("evidence", [])

                    if isinstance(evidence_items, list):
                        for item in evidence_items:
                            print(
                                "\n  EVIDENCE:",
                                item.get("evidence", "N/A"),
                            )
                            print(
                                "  NLI LABEL:",
                                item.get("label", "N/A"),
                            )
                            print(
                                "  NLI PROBABILITIES:",
                                item.get("probabilities", "N/A"),
                            )
                            print(
                                "  EVIDENCE SCORE:",
                                item.get("evidence_score", "N/A"),
                            )
                    else:
                        print("  SOURCE DETAILS:", evidence_items)

    if not found_issue:
        print("\nNo unsupported or contradicted atomic claims were found.")

    print("\n" + "=" * 100)
    print("PER-QUERY GROUNDING SUMMARY")
    print("=" * 100)

    for evaluation in evaluations:
        print(
            f"Query: {evaluation['query']}\n"
            f"  Claims: {evaluation['total_claims']}\n"
            f"  Grounded: {evaluation['grounded_claims']}\n"
            f"  Unsupported: {evaluation['unsupported_claims']}\n"
            f"  Contradicted: {evaluation['contradicted_claims']}\n"
            f"  Uncited: {evaluation['uncited_claims']}\n"
            f"  Evidence score: {evaluation['evidence_score']}\n"
            f"  Evidence sufficient: {evaluation['evidence_sufficient']}\n"
        )

        # Keep the benchmark strict, but expose why an answerable query was refused.
        if evaluation["answerable"] and evaluation["refused"]:
            result = evaluation["result"]
            evidence = result.get("evidence", {})
            print("\nUNEXPECTED REFUSAL DIAGNOSTIC")
            print("  Query:", evaluation["query"])
            print("  Evidence score:", evidence.get("score"))
            print("  Evidence threshold:", evidence.get("threshold"))
            print("  Evidence sufficient:", evidence.get("sufficient"))
            print("  Evidence reason:", evidence.get("reason"))
            print("  Answer:", result.get("answer"))
            print("  Generation repair:", result.get("generation_repair"))


def test_rag_pipeline_evaluation():
    """Run the end-to-end RAG evaluation benchmark."""
    pipeline = RAGPipeline(document_path=PDF_PATH)

    evaluations = [
        evaluate_query(pipeline, item)
        for item in EVALUATION_DATASET
    ]

    print_grounding_diagnostics(evaluations)

    total_queries = len(evaluations)
    assert total_queries > 0, "Evaluation dataset must not be empty."

    answerable_evaluations = [
        item for item in evaluations if item["answerable"]
    ]
    unanswerable_evaluations = [
        item for item in evaluations if not item["answerable"]
    ]

    answer_success_rate = (
        sum(item["answered"] for item in answerable_evaluations)
        / len(answerable_evaluations)
        if answerable_evaluations
        else 0.0
    )

    refusal_accuracy = (
        sum(item["refused"] for item in unanswerable_evaluations)
        / len(unanswerable_evaluations)
        if unanswerable_evaluations
        else 0.0
    )

    citation_validity_rate = (
        sum(item["citation_valid"] for item in evaluations)
        / total_queries
    )

    total_claims = sum(item["total_claims"] for item in evaluations)
    grounded_claims = sum(item["grounded_claims"] for item in evaluations)
    unsupported_claims = sum(
        item["unsupported_claims"] for item in evaluations
    )
    contradicted_claims = sum(
        item["contradicted_claims"] for item in evaluations
    )
    uncited_claims = sum(item["uncited_claims"] for item in evaluations)

    grounded_claim_rate = (
        grounded_claims / total_claims if total_claims else 0.0
    )
    unsupported_claim_rate = (
        unsupported_claims / total_claims if total_claims else 0.0
    )
    contradicted_claim_rate = (
        contradicted_claims / total_claims if total_claims else 0.0
    )
    uncited_claim_rate = (
        uncited_claims / total_claims if total_claims else 0.0
    )

    grounded_answers = sum(
        item["fully_grounded"]
        for item in evaluations
        if item["answered"]
    )
    answered_count = sum(item["answered"] for item in evaluations)

    grounded_answer_rate = (
        grounded_answers / answered_count if answered_count else 0.0
    )

    print("\n" + "=" * 80)
    print("RAG EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total queries: {total_queries}")
    print(f"Answer success rate: {answer_success_rate:.4f}")
    print(f"Refusal accuracy: {refusal_accuracy:.4f}")
    print(f"Citation validity rate: {citation_validity_rate:.4f}")
    print(f"Total claims: {total_claims}")
    print(f"Grounded claims: {grounded_claims}")
    print(f"Unsupported claims: {unsupported_claims}")
    print(f"Contradicted claims: {contradicted_claims}")
    print(f"Uncited claims: {uncited_claims}")
    print(f"Grounded claim rate: {grounded_claim_rate:.4f}")
    print(f"Unsupported claim rate: {unsupported_claim_rate:.4f}")
    print(f"Contradicted claim rate: {contradicted_claim_rate:.4f}")
    print(f"Uncited claim rate: {uncited_claim_rate:.4f}")
    print(f"Grounded answer rate: {grounded_answer_rate:.4f}")

    # Preserve the existing benchmark's expected behavior checks.
    assert answer_success_rate == 1.0
    assert refusal_accuracy == 1.0
    assert citation_validity_rate == 1.0
    assert contradicted_claim_rate == 0.0