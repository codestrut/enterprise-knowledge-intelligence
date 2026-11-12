
"""Claim-level grounding evaluation for the RAG pipeline.

Each evaluated claim has one status: ``grounded``, ``unsupported``,
``contradicted`` or ``uncited`` (the sentence carried no citation).
"""

import re

from src.generation.claim_parser import parse_claims
from src.generation.claim_decomposer import ClaimDecomposer
from src.generation.evidence_selector import EvidenceSelector
from src.generation.semantic_grounder import SemanticGrounder


class GroundingEvaluator:
    """Evaluate whether answer claims are supported by cited evidence."""

    MIN_CONTRADICTION_EVIDENCE_SCORE = 0.40
    MIN_ENTAILMENT_PROBABILITY = 0.50
    MIN_CONTRADICTION_PROBABILITY = 0.80
    MIN_CONTENT_OVERLAP_RATIO = 0.25

    # Common words that contribute little to identifying whether a claim
    # and an evidence passage discuss the same subject or concept.
    CONTRADICTION_STOPWORDS = {
        "a", "an", "the",
        "is", "are", "was", "were",
        "be", "been", "being",
        "do", "does", "did",
        "has", "have", "had",
        "use", "uses", "used", "using",
        "of", "in", "on", "at", "to", "for",
        "and", "or", "but", "by", "with", "from",
        "that", "this", "these", "those",
        "it", "its",
        "system", "systems",
        "organization", "organizations",
        "organizational",
        "require", "requires", "required",
    }

    def __init__(
        self,
        evidence_selector=None,
        semantic_grounder=None,
        embedder=None,
        claim_decomposer=None,
    ):
        """Initialize the grounding evaluator and its dependencies."""

        self.evidence_selector = (
            evidence_selector
            if evidence_selector is not None
            else EvidenceSelector(embedder=embedder)
        )

        self.grounder = (
            semantic_grounder
            if semantic_grounder is not None
            else SemanticGrounder()
        )

        self.claim_decomposer = (
            claim_decomposer
            if claim_decomposer is not None
            else ClaimDecomposer()
        )

    @staticmethod
    def _normalize_list_item(text):
        """Normalize a short list item for exact source-membership checks."""
        return " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold()))

    @classmethod
    def _is_exact_enumerated_list_item(cls, claim, evidence):
        """Return True when a claim exactly matches an item in a source list.

        This narrowly handles answer bullets such as ``Identify [Source 1]``
        when the cited evidence explicitly enumerates ``Govern, Identify, ...``.
        It is not general lexical-overlap support: the item must match an entry
        in a colon-introduced list containing at least three entries.
        """
        normalized_claim = cls._normalize_list_item(claim)
        if not normalized_claim:
            return False

        # Source lists are typically introduced by a label, e.g.
        # "There are six CSF Functions: Govern, Identify, ...". Limit the
        # deterministic check to the text after a colon and before sentence end.
        for match in re.finditer(r":\s*([^.!?]+)", str(evidence or "")):
            list_text = match.group(1).strip()
            if not re.search(r",", list_text) or not re.search(r"\b(?:and|or)\b", list_text, re.IGNORECASE):
                continue

            # Normalize the Oxford comma first so the final item does not
            # retain a leading conjunction ("and Recover").
            list_text = re.sub(
                r",\s*(?:and|or)\s+", ", ", list_text, flags=re.IGNORECASE
            )
            items = re.split(r",\s*|\s+(?:and|or)\s+", list_text, flags=re.IGNORECASE)
            normalized_items = [cls._normalize_list_item(item) for item in items]
            normalized_items = [item for item in normalized_items if item]
            if len(normalized_items) >= 3 and normalized_claim in normalized_items:
                return True

        return False

    @classmethod
    def _has_content_overlap(cls, claim, evidence):
        """
        Check whether a claim and evidence share meaningful content terms.

        This is a conservative lexical safeguard for contradiction decisions.
        It is not, by itself, proof that two statements contradict each other.
        """

        def extract_terms(text):
            return {
                token
                for token in re.findall(
                    r"[a-z0-9]+",
                    text.lower(),
                )
                if len(token) > 1
                and token not in cls.CONTRADICTION_STOPWORDS
            }

        claim_terms = extract_terms(claim)
        evidence_terms = extract_terms(evidence)

        if not claim_terms or not evidence_terms:
            return False

        overlapping_terms = claim_terms & evidence_terms

        overlap_ratio = (
            len(overlapping_terms) / len(claim_terms)
        )

        return (
            bool(overlapping_terms)
            and overlap_ratio >= cls.MIN_CONTENT_OVERLAP_RATIO
        )

    def evaluate_predecomposed(self, answer, source_map, source_documents):
        """Independently ground claims that have already been decomposed.

        This dedicated entry point preserves the original three-argument
        evaluate() interface for injected evaluators while avoiding a second
        decomposition of grounded-subset candidates.
        """
        return self.evaluate(
            answer,
            source_map,
            source_documents,
            decompose_claims=False,
        )

    def evaluate(self, answer, source_map, source_documents, *, decompose_claims=True):
        """Evaluate and classify every cited answer claim."""

        claims = parse_claims(answer)
        evaluations = []

        for claim_data in claims:
            original_claim = claim_data["claim"]
            source_numbers = claim_data["source_numbers"]

            # A sentence without a citation cannot be verified against cited
            # evidence. Report it explicitly (no LLM decomposition, no NLI)
            # instead of dropping it or labelling it with a neighbour's source.
            if claim_data.get("uncited") or not source_numbers:
                evaluations.append({
                    "claim": original_claim,
                    "atomic_claims": [],
                    "status": "uncited",
                    "reason": (
                        "The claim has no [Source N] citation, so it was "
                        "not verified against evidence."
                    ),
                })
                continue

            atomic_evaluations = []

            claim_context = claim_data.get("context")
            if decompose_claims:
                if claim_context:
                    atomic_claims = self.claim_decomposer.decompose(
                        original_claim,
                        context=claim_context,
                    )
                else:
                    atomic_claims = self.claim_decomposer.decompose(
                        original_claim
                    )
            else:
                # Grounded-subset candidates are already atomic claims
                # approved by an earlier evaluation. Do not decompose them
                # again; still run evidence selection and semantic grounding.
                atomic_claims = [original_claim]

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

                    if (
                        source_index < 0
                        or source_index >= len(source_documents)
                    ):
                        claim_evidence.append({
                            "source_number": source_number,
                            "label": "invalid",
                            "reason": (
                                "Source does not map to retrieved evidence."
                            ),
                        })
                        continue

                    evidence = source_documents[source_index]["text"]

                    selected_evidence = self.evidence_selector.select(
                        claim=atomic_claim,
                        evidence=evidence,
                        top_k=2,
                    )

                    if not selected_evidence:
                        claim_evidence.append({
                            "source_number": source_number,
                            "label": "unsupported",
                            "reason": (
                                "No sufficiently relevant evidence was found."
                            ),
                        })
                        continue

                    source_results = []

                    for evidence_item in selected_evidence:
                        result = self.grounder.check_claim(
                            claim=atomic_claim,
                            evidence=evidence_item["text"],
                        )

                        probabilities = result.get(
                            "probabilities",
                            {},
                        )

                        exact_list_item_match = self._is_exact_enumerated_list_item(
                            atomic_claim, evidence_item["text"]
                        )
                        source_results.append({
                            # Exact membership in an explicitly enumerated source
                            # list is direct support even when NLI rejects a bare
                            # noun fragment such as "Identify" as non-sentential.
                            "label": (
                                "entailment" if exact_list_item_match else result["label"]
                            ),
                            "raw_label": result.get("raw_label", result["label"]),
                            "exact_list_item_match": exact_list_item_match,
                            "relation_guard": result.get("relation_guard", {}),
                            "support_guard": result.get("support_guard", {}),
                            "probabilities": probabilities,
                            "evidence": evidence_item["text"],
                            "evidence_score": evidence_item["score"],
                        })

                    # Supporting evidence must pass its own NLI confidence
                    # threshold. Relevance thresholds for contradictions
                    # must not suppress valid supporting evidence.
                    has_entailment = any(
                        item["label"] == "entailment"
                        and (
                            item["probabilities"].get("entailment", 0.0)
                            >= self.MIN_ENTAILMENT_PROBABILITY
                            or item.get("support_guard", {}).get("applied", False)
                            or item.get("exact_list_item_match", False)
                        )
                        for item in source_results
                    )

                    # A contradiction must satisfy all three conditions:
                    # 1. The NLI model predicts contradiction.
                    # 2. Contradiction confidence is sufficiently high.
                    # 3. The evidence is relevant and shares meaningful
                    #    content terms with the claim.
                    #
                    # Lexical overlap is a safeguard, not proof of
                    # contradiction; it can also miss valid paraphrases.
                    has_contradiction = any(
                        item["label"] == "contradiction"
                        and item["probabilities"].get(
                            "contradiction",
                            0.0,
                        ) >= self.MIN_CONTRADICTION_PROBABILITY
                        and item["evidence_score"]
                        >= self.MIN_CONTRADICTION_EVIDENCE_SCORE
                        and self._has_content_overlap(
                            atomic_claim,
                            item["evidence"],
                        )
                        for item in source_results
                    )

                    # If a source has sufficiently confident supporting
                    # evidence, do not allow a separate NLI false positive
                    # to override it. Record the conflict for diagnostics.
                    if has_entailment:
                        source_label = "entailment"
                    elif has_contradiction:
                        source_label = "contradiction"
                    else:
                        source_label = "neutral"

                    claim_evidence.append({
                        "source_number": source_number,
                        "label": source_label,
                        "conflict_detected": (
                            has_entailment and has_contradiction
                        ),
                        "evidence": source_results,
                    })

                status = self._classify_claim(claim_evidence)

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
        """Classify an atomic claim using its cited source evaluations.

        Supporting evidence can neutralize an NLI false positive within the
        same source (handled before this method). It must not hide a conflict
        between two distinct cited sources: if one source supports the claim
        and another strongly contradicts it, require repair or an explicit
        source-by-source explanation instead of marking the claim grounded.
        """

        labels = [
            source["label"]
            for source in source_evaluations
        ]

        # A cross-source disagreement is materially different from mixed NLI
        # predictions for two passages inside one source. Do not silently pick
        # the supporting source and suppress a separate source's contradiction.
        if "entailment" in labels and "contradiction" in labels:
            return "contradicted"

        if "entailment" in labels:
            return "grounded"

        if "contradiction" in labels:
            return "contradicted"

        return "unsupported"

    @staticmethod
    def _classify_atomic_claims(atomic_evaluations):
        """Aggregate the results of all atomic claims."""

        statuses = [
            evaluation["status"]
            for evaluation in atomic_evaluations
        ]

        if not statuses:
            return "unsupported"

        if all(status == "grounded" for status in statuses):
            return "grounded"

        if any(status == "contradicted" for status in statuses):
            return "contradicted"

        return "unsupported"
