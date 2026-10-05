"""Claim-level grounding evaluation."""

from src.generation.claim_parser import parse_claims
from src.generation.claim_decomposer import ClaimDecomposer
from src.generation.evidence_selector import EvidenceSelector
from src.generation.semantic_grounder import SemanticGrounder


class GroundingEvaluator:
    """Evaluate whether answer claims are supported by cited evidence."""

    def __init__(
        self,
        evidence_selector=None,
        semantic_grounder=None,
        embedder=None,
        claim_decomposer=None,
    ):
        self.evidence_selector = (
            evidence_selector
            or EvidenceSelector(
                embedder=embedder,
            )
        )

        self.grounder = (
            semantic_grounder
            or SemanticGrounder()
        )

        self.claim_decomposer = (
            claim_decomposer
            or ClaimDecomposer()
        )

    def evaluate(
        self,
        answer,
        source_map,
        source_documents,
    ):
        """Evaluate and classify every cited claim."""

        claims = parse_claims(answer)

        evaluations = []

        for claim_data in claims:

            original_claim = claim_data["claim"]
            source_numbers = claim_data["source_numbers"]

            atomic_claims = self.claim_decomposer.decompose(
                original_claim
            )

            atomic_evaluations = []

            for atomic_claim in atomic_claims:

                claim_evidence = []

                for source_number in source_numbers:

                    if source_number not in source_map:

                        claim_evidence.append({
                            "source_number": source_number,
                            "label": "invalid",
                            "reason": "Source does not exist.",
                        })

                        continue

                    source_index = source_number - 1

                    if source_index >= len(
                        source_documents
                    ):

                        claim_evidence.append({
                            "source_number": source_number,
                            "label": "invalid",
                            "reason": (
                                "Source does not map to "
                                "retrieved evidence."
                            ),
                        })

                        continue

                    evidence = source_documents[
                        source_index
                    ]["text"]

                    selected_evidence = (
                        self.evidence_selector.select(
                            claim=atomic_claim,
                            evidence=evidence,
                            top_k=2,
                        )
                    )

                    if not selected_evidence:

                        claim_evidence.append({
                            "source_number": source_number,
                            "label": "unsupported",
                            "reason": (
                                "No sufficiently relevant "
                                "evidence was found."
                            ),
                        })

                        continue

                    source_results = []

                    for evidence_item in selected_evidence:

                        result = self.grounder.check_claim(
                            claim=atomic_claim,
                            evidence=evidence_item["text"],
                        )

                        source_results.append({
                            "label": result["label"],
                            "probabilities": result[
                                "probabilities"
                            ],
                            "evidence": evidence_item["text"],
                            "evidence_score": (
                                evidence_item["score"]
                            ),
                        })

                    source_labels = [
                        result["label"]
                        for result in source_results
                    ]

                    has_entailment = (
                        "entailment" in source_labels
                    )

                    has_contradiction = (
                        "contradiction" in source_labels
                    )

                    if (
                        has_entailment
                        and has_contradiction
                    ):
                        source_label = "conflict"

                    elif has_entailment:
                        source_label = "entailment"

                    elif has_contradiction:
                        source_label = "contradiction"

                    else:
                        source_label = "neutral"

                    claim_evidence.append({
                        "source_number": source_number,
                        "label": source_label,
                        "evidence": source_results,
                    })

                status = self._classify_claim(
                    claim_evidence
                )

                atomic_evaluations.append({
                    "claim": atomic_claim,
                    "sources": claim_evidence,
                    "status": status,
                })

            overall_status = self._classify_atomic_claims(
                atomic_evaluations
            )

            evaluations.append({
                "claim": original_claim,
                "atomic_claims": atomic_evaluations,
                "status": overall_status,
            })

        return evaluations

    @staticmethod
    def _classify_claim(source_evaluations):
        """Classify an atomic claim based on source evaluations."""

        labels = [
            source["label"]
            for source in source_evaluations
        ]

        # Conflicting evidence must never be treated as grounded.
        if "conflict" in labels:
            return "unsupported"

        if "entailment" in labels:
            return "grounded"

        if "contradiction" in labels:
            return "contradicted"

        return "unsupported"

    @staticmethod
    def _classify_atomic_claims(atomic_evaluations):
        """Aggregate atomic claim results into an overall status."""

        statuses = [
            evaluation["status"]
            for evaluation in atomic_evaluations
        ]

        if not statuses:
            return "unsupported"

        if all(
            status == "grounded"
            for status in statuses
        ):
            return "grounded"

        if any(
            status == "contradicted"
            for status in statuses
        ):
            return "contradicted"

        return "unsupported"