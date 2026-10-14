"""RAG evaluation dataset and retrieval metrics.

Gold evidence is anchored to source text rather than sequential chunk IDs.
Chunk IDs are implementation artifacts and can change when chunking changes.
"""

import re
import unicodedata


EVALUATION_DATASET = [
    {
        "query": "What is an Organizational Profile?",
        "relevant_evidence": [
            "A CSF Organizational Profile describes an organization’s current and/or target cybersecurity posture in terms of the Core’s outcomes",
            "Organizational Profiles are used to understand, tailor, assess, prioritize, and communicate the Core’s outcomes",
            "CSF Organizational Profile A mechanism for describing an organization’s current and/or target cybersecurity posture in terms of the CSF Core’s outcomes",
            "Every Organizational Profile includes one or both of the following",
        ],
        "answerable": True,
        "expected_concepts": [
            "current and/or target cybersecurity posture",
            "CSF Core outcomes",
            "understand",
            "tailor",
            "assess",
            "prioritize",
            "communicate",
            "Current Profile",
            "Target Profile",
        ],
    },
    {
        "query": "What does NIST say about cybersecurity roles and responsibilities?",
        "relevant_evidence": [
            "Roles, Responsibilities, and Authorities (GV.RR): Cybersecurity roles, responsibilities, and authorities to foster accountability, performance assessment, and continuous improvement are established and communicated",
            "GV.RR-01: Organizational leadership is responsible and accountable for cybersecurity risk",
            "GV.RR-02: Roles, responsibilities, and authorities related to cybersecurity risk management are established, communicated, understood, and enforced",
            "GV.SC-02: Cybersecurity roles and responsibilities for suppliers, customers, and partners are established, communicated, and coordinated internally and externally",
        ],
        "answerable": True,
        "expected_concepts": [
            "cybersecurity roles",
            "responsibilities",
            "leadership",
            "organizational roles",
        ],
    },
    {
        "query": "What is GV.RR-01?",
        "relevant_evidence": [
            "GV.RR-01: Organizational leadership is responsible and accountable for cybersecurity risk and fosters a culture that is risk-aware, ethical, and continually improving",
        ],
        "answerable": True,
        "expected_concepts": [
            "GV.RR-01",
            "roles",
            "responsibilities",
            "cybersecurity risk management",
        ],
    },
    {
        "query": "How can an organization prioritize cybersecurity activities?",
        "relevant_evidence": [
            "Prioritize: Identify, organize, and prioritize actions for managing cybersecurity risks that align with the organization’s mission, legal and regulatory requirements, and risk management and governance expectations",
            "With an understanding of stakeholder expectations and risk appetite and tolerance (as outlined in GOVERN), an organization can prioritize cybersecurity activities to make informed decisions about cybersecurity expenditures and actions",
        ],
        "answerable": True,
        "expected_concepts": [
            "prioritize",
            "cybersecurity activities",
            "risk",
            "organizational objectives",
        ],
    },
    {
        "query": "What are the cybersecurity risk tiers?",
        "relevant_evidence": [
            "The Tiers, as shown in Fig. 4 and notionally illustrated in Appendix B, reflect an organization’s practices for managing cybersecurity risk as Partial (Tier 1), Risk Informed (Tier 2), Repeatable (Tier 3), and Adaptive (Tier 4)",
            "The Tiers characterize the rigor of an organization’s cybersecurity risk governance practices (GOVERN) and cybersecurity risk management practices (IDENTIFY, PROTECT, DETECT, RESPOND, and RECOVER)",
            "The prioritization of cybersecurity activities and protection needs is directly informed by organizational risk objectives, the threat environment, or business/mission requirements",
        ],
        "answerable": True,
        "expected_concepts": [
            "risk tiers",
            "Tier 1",
            "Tier 2",
            "Tier 3",
            "Tier 4",
            "cybersecurity risk management",
        ],
    },
    {
        "query": "What is cybersecurity supply chain risk management?",
        "relevant_evidence": [
            "Cyber supply chain risk management processes are identified, established, managed, monitored, and improved by organizational stakeholders",
            "Cybersecurity SCRM (C-SCRM) is a systematic process for managing exposure to cybersecurity risk throughout supply chains and developing appropriate response strategies, policies, processes, and procedures",
            "GV.SC-03: Cybersecurity supply chain risk management is integrated into cybersecurity and enterprise risk management, risk assessment, and improvement processes",
            "GV.SC-04: Suppliers are known and prioritized by criticality",
        ],
        "answerable": True,
        "expected_concepts": [
            "cybersecurity supply chain risk management",
            "suppliers",
            "third parties",
            "supply chain",
            "cybersecurity risks",
        ],
    },
    {
        "query": "How are cybersecurity risks integrated into enterprise risk management?",
        "relevant_evidence": [
            "Governance activities are critical for incorporating cybersecurity into an organization’s broader enterprise risk management (ERM) strategy",
            "The CSF helps organizations to translate their terminology for cybersecurity and cybersecurity risk management into general risk management language that executives will understand",
            "GV.RM-03: Cybersecurity risk management activities and outcomes are included in enterprise risk management processes",
            "GV.SC-03: Cybersecurity supply chain risk management is integrated into cybersecurity and enterprise risk management, risk assessment, and improvement processes",
        ],
        "answerable": True,
        "expected_concepts": [
            "enterprise risk management",
            "cybersecurity risk",
            "risk management",
            "organizational risk",
        ],
    },
    {
        "query": "How are access permissions and authorizations managed?",
        "relevant_evidence": [
            "PR.AA-05: Access permissions, entitlements, and authorizations are defined in a policy, managed, enforced, and reviewed, and incorporate the principles of least privilege and separation of duties",
        ],
        "answerable": True,
        "expected_concepts": [
            "access permissions",
            "authorizations",
            "access control",
            "identity",
            "privileges",
        ],
    },
    {
        "query": "What does the NIST CSF 2.0 say about implementation costs?",
        "relevant_evidence": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "Which encryption algorithm does the NIST CSF 2.0 require organizations to use?",
        "relevant_evidence": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "What is the default password for a Cisco firewall?",
        "relevant_evidence": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "What is the latest Windows security vulnerability?",
        "relevant_evidence": [],
        "answerable": False,
        "expected_concepts": [],
    },
]


def _normalize_evidence_text(text):
    """Normalize PDF line breaks, punctuation and Unicode for phrase matching."""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    # Treat smart apostrophes, dashes, line breaks and punctuation consistently.
    normalized = normalized.replace("’", "'").replace("‘", "'")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def resolve_relevant_evidence(chunks, evidence_anchors):
    """Resolve stable source-text anchors to current chunk IDs.

    For each anchor, choose the most focused chunk containing the full anchor.
    Returns (resolved_ids, unmapped_anchors). Unmapped anchors must not be silently
    removed from recall denominators.
    """
    resolved_ids = []
    unmapped_anchors = []
    normalized_chunks = []

    for chunk in chunks:
        chunk_id = chunk.get("metadata", {}).get("chunk_id")
        chunk_text = _normalize_evidence_text(chunk.get("text", ""))
        if chunk_id is not None and chunk_text:
            normalized_chunks.append((chunk_id, chunk_text))

    for anchor in evidence_anchors:
        normalized_anchor = _normalize_evidence_text(anchor)
        if not normalized_anchor:
            unmapped_anchors.append(anchor)
            continue

        matches = [
            (chunk_id, chunk_text)
            for chunk_id, chunk_text in normalized_chunks
            if normalized_anchor in chunk_text
        ]
        if not matches:
            unmapped_anchors.append(anchor)
            continue

        # If a paragraph appears in overlapping chunks, map it to the most
        # focused containing chunk rather than counting every duplicate as gold.
        best_chunk_id, _ = max(
            matches,
            key=lambda pair: (
                len(normalized_anchor) / len(pair[1]),
                -len(pair[1]),
            ),
        )
        if best_chunk_id not in resolved_ids:
            resolved_ids.append(best_chunk_id)

    return resolved_ids, unmapped_anchors


def resolve_relevant_chunks(chunks, relevant_chunks):
    """Legacy numeric-ID resolver; retain only for compatibility tests/tools."""
    available_chunk_ids = {
        chunk["metadata"]["chunk_id"]
        for chunk in chunks
    }
    return [chunk_id for chunk_id in relevant_chunks if chunk_id in available_chunk_ids]


def hit_at_k(retrieved_chunks, relevant_chunks, k):
    """Return 1 if at least one relevant chunk appears in top-k."""
    retrieved_top_k = retrieved_chunks[:k]
    return int(any(chunk_id in relevant_chunks for chunk_id in retrieved_top_k))


def recall_at_k(retrieved_chunks, relevant_chunks, k):
    """Calculate the fraction of relevant chunks retrieved in top-k."""
    relevant_chunks = set(relevant_chunks)
    if not relevant_chunks:
        return 0.0
    retrieved_top_k = set(retrieved_chunks[:k])
    return len(retrieved_top_k.intersection(relevant_chunks)) / len(relevant_chunks)


def reciprocal_rank(retrieved_chunks, relevant_chunks):
    """Return the reciprocal rank of the first relevant chunk."""
    relevant_chunks = set(relevant_chunks)
    if not relevant_chunks:
        return 0.0
    for rank, chunk_id in enumerate(retrieved_chunks, start=1):
        if chunk_id in relevant_chunks:
            return 1 / rank
    return 0.0
