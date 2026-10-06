"""RAG evaluation dataset and retrieval metrics."""


EVALUATION_DATASET = [
    {
        "query": "What is an Organizational Profile?",
        "relevant_chunks": [22, 110, 111],
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
        "relevant_chunks": [77],
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
        "relevant_chunks": [77],
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
        "relevant_chunks": [52],
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
        "relevant_chunks": [101, 102, 111],
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
        "relevant_chunks": [68, 71, 72, 79, 80, 82],
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
        "relevant_chunks": [75],
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
        "relevant_chunks": [89],
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
        "relevant_chunks": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "Which encryption algorithm does the NIST CSF 2.0 require organizations to use?",
        "relevant_chunks": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "What is the default password for a Cisco firewall?",
        "relevant_chunks": [],
        "answerable": False,
        "expected_concepts": [],
    },
    {
        "query": "What is the latest Windows security vulnerability?",
        "relevant_chunks": [],
        "answerable": False,
        "expected_concepts": [],
    },
]


def resolve_relevant_chunks(chunks, relevant_chunks):
    """Return explicitly annotated relevant chunk IDs."""

    available_chunk_ids = {
        chunk["metadata"]["chunk_id"]
        for chunk in chunks
    }

    return [
        chunk_id
        for chunk_id in relevant_chunks
        if chunk_id in available_chunk_ids
    ]


def hit_at_k(retrieved_chunks, relevant_chunks, k):
    """Return 1 if at least one relevant chunk appears in top-k."""

    retrieved_top_k = retrieved_chunks[:k]

    return int(
        any(
            chunk_id in relevant_chunks
            for chunk_id in retrieved_top_k
        )
    )


def recall_at_k(retrieved_chunks, relevant_chunks, k):
    """Calculate the fraction of relevant chunks retrieved in top-k."""

    relevant_chunks = set(relevant_chunks)

    if not relevant_chunks:
        return 0.0

    retrieved_top_k = set(retrieved_chunks[:k])

    retrieved_relevant = retrieved_top_k.intersection(
        relevant_chunks
    )

    return len(retrieved_relevant) / len(relevant_chunks)


def reciprocal_rank(retrieved_chunks, relevant_chunks):
    """Return the reciprocal rank of the first relevant chunk."""

    relevant_chunks = set(relevant_chunks)

    if not relevant_chunks:
        return 0.0

    for rank, chunk_id in enumerate(
        retrieved_chunks,
        start=1,
    ):
        if chunk_id in relevant_chunks:
            return 1 / rank

    return 0.0