"""Claim and citation parsing utilities."""

import re


_CITATION_GROUP = re.compile(
    r"(?P<citations>(?:\[Source\s+\d+\][ \t]*)+)[.!?]?"
)
_SOURCE_NUMBER = re.compile(r"\[Source\s+(\d+)\]")
_CITATION_METADATA = re.compile(
    r"\[Citations:\s*(?:Source\s+\d+\s*(?:[,;]\s*)?)+\]",
    re.IGNORECASE,
)
_ANAPHOR_PREFIX = re.compile(
    r"^(?:it|this|these|those|they|that|such)\b", re.IGNORECASE
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\r?\n+")
_BULLET_PREFIX = re.compile(
    r"(?m)^[ \t]*(?:[-*•]|\d+[.)])[ \t]+"
)
_SCOPE_BOUNDARY = re.compile(
    r"(?:\r?\n[ \t]*\r?\n)+|(?=^[ \t]*(?:[-*•]|\d+[.)])[ \t]+)",
    re.MULTILINE,
)

_STRUCTURAL_LEAD_IN = re.compile(
    r"^(?:(?:specific|key|main|following)\s+(?:points|items|details|examples)\s+"
    r"(?:include|are|follow)|the following(?:\s+points|\s+items|\s+details)?\s+"
    r"(?:include|are|follow)|examples\s+include)\s*:?$",
    re.IGNORECASE,
)


def _split_sentences(text):
    """Split a piece of answer text into non-empty sentence claims."""
    text = _BULLET_PREFIX.sub("", text.strip())
    sentences = _SENTENCE_BOUNDARY.split(text)
    result = []
    for sentence in sentences:
        sentence = sentence.strip()
        sentence = sentence.lstrip(" \t\r\n")
        if not sentence.strip(" .!?-•\t\r\n"):
            continue
        result.append(sentence)
    return result


def _citation_scope(segment, *, allow_all_sentences):
    """Select text to which the citation immediately following it applies.

    A single citation group at the end of a response follows the legacy
    convention: it applies to every sentence in the preceding answer block.
    With multiple groups, citation association is conservative. A group
    applies to the immediately preceding sentence, unless an explicit
    paragraph or bullet boundary defines a larger local scope.
    """
    if allow_all_sentences:
        return _split_sentences(segment)

    scopes = [part for part in _SCOPE_BOUNDARY.split(segment) if part.strip()]
    if not scopes:
        return []

    scope = scopes[-1]
    sentences = _split_sentences(scope)
    leading_text = segment.lstrip(" \t")
    starts_new_paragraph = bool(
        re.match(r"^(?:\r?\n[ \t]*\r?\n)+", leading_text)
    )
    starts_new_bullet = bool(
        re.match(r"^(?:\r?\n)?[ \t]*(?:[-*•]|\d+[.)])[ \t]+", leading_text)
    )
    is_explicit_scope = (
        len(scopes) > 1
        or bool(_BULLET_PREFIX.match(scope))
        or starts_new_paragraph
        or starts_new_bullet
    )
    if is_explicit_scope:
        return sentences
    return sentences[-1:]


def _uncited_prefix(all_sentences, scoped_sentences):
    """Return segment sentences that no citation group claims.

    Scoped sentences are normally a suffix of the segment's sentences (the
    sentence or block directly before the citation). Everything earlier in the
    segment is uncited text that must still be evaluated, not discarded.
    """
    if not scoped_sentences:
        return list(all_sentences)
    count = len(all_sentences) - len(scoped_sentences)
    if count > 0 and all_sentences[count:] == scoped_sentences:
        return list(all_sentences[:count])
    if count <= 0:
        return []
    return [s for s in all_sentences if s not in scoped_sentences]


def _uncited_record(sentence):
    """Build a claim record for a sentence that carries no citation."""
    return {"claim": sentence, "source_numbers": [], "uncited": True}


def parse_claims(answer):
    """Extract sentence claims and associate each with its citation group.

    Citation groups at the end of a single-cited answer apply to all claims
    in the preceding answer block. When a response contains multiple citation
    groups, each group is associated with its local preceding sentence or
    explicit paragraph/bullet, avoiding accidental attribution to intervening
    uncited statements.

    Uncited sentences (before, between or after citation groups, or in an
    answer with no citations) are returned with ``source_numbers == []`` and
    ``uncited == True`` so that they are counted and reported instead of being
    silently excluded from grounding metrics. They are never attributed to a
    neighbouring citation.
    """
    if not answer or not answer.strip():
        return []

    # Some model outputs emit a non-standard metadata marker in addition to
    # valid citations. Do not treat that marker as a factual claim. It does
    # not count as a valid citation; only the exact [Source N] form is parsed.
    answer = _CITATION_METADATA.sub("", answer)
    matches = list(_CITATION_GROUP.finditer(answer))
    if not matches:
        return [
            _uncited_record(sentence)
            for sentence in _split_sentences(answer)
            if not _STRUCTURAL_LEAD_IN.fullmatch(sentence.strip())
        ]

    claims = []
    cursor = 0
    single_group = len(matches) == 1
    # Retain prior answer sentences across citation groups so pronouns such as
    # "It" can still resolve to a named entity introduced several sentences
    # earlier (rather than to a noun mentioned in the immediately prior clause).
    context_history = []

    for index, match in enumerate(matches):
        segment = answer[cursor:match.start()]
        all_segment_sentences = _split_sentences(segment)
        source_numbers = list(dict.fromkeys(
            int(number)
            for number in _SOURCE_NUMBER.findall(match.group("citations"))
        ))

        # A lone final citation group may cover an entire answer block.
        # With multiple groups, later citations use a local preceding scope.
        allow_all = single_group or index == 0
        scoped_sentences = _citation_scope(segment, allow_all_sentences=allow_all)

        for sentence in _uncited_prefix(all_segment_sentences, scoped_sentences):
            if _STRUCTURAL_LEAD_IN.fullmatch(sentence.strip()):
                continue
            claims.append(_uncited_record(sentence))

        # Resolve pronoun-like openings only as context for decomposing and
        # evaluating the claim. Keep the original claim unchanged for display.
        search_from = 0
        for sentence in scoped_sentences:
            matched_index = None
            for candidate_index in range(search_from, len(all_segment_sentences)):
                if all_segment_sentences[candidate_index] == sentence:
                    matched_index = candidate_index
                    break

            antecedent_parts = list(context_history)
            if matched_index is not None and matched_index > 0:
                # Include earlier sentences in this segment as well as those
                # from prior citation groups. This preserves referent chains
                # across both paragraph-final and sentence-local citations.
                antecedent_parts.extend(
                    all_segment_sentences[:matched_index]
                )
                search_from = matched_index + 1
            elif matched_index is not None:
                search_from = matched_index + 1
            antecedent = " ".join(antecedent_parts).strip() or None

            # List-introducing labels such as "Specific points include:" are
            # formatting scaffolding, not factual claims. Excluding them keeps
            # claim-level metrics from counting a heading as unsupported.
            if _STRUCTURAL_LEAD_IN.fullmatch(sentence.strip()):
                continue

            record = {
                "claim": sentence,
                "source_numbers": source_numbers.copy(),
            }
            if antecedent and _ANAPHOR_PREFIX.match(sentence):
                record["context"] = antecedent
            claims.append(record)

        # Adjacent citation groups with no text between them are one citation
        # set for the preceding claim when citations are adjacent. Do not
        # silently lose the later source number.
        if (
            not scoped_sentences
            and claims
            and not segment.strip(" \t\r\n.!?")
        ):
            claims[-1]["source_numbers"] = list(dict.fromkeys(
                claims[-1]["source_numbers"] + source_numbers
            ))

        context_history.extend(all_segment_sentences)
        cursor = match.end()

    for sentence in _split_sentences(answer[cursor:]):
        if _STRUCTURAL_LEAD_IN.fullmatch(sentence.strip()):
            continue
        claims.append(_uncited_record(sentence))

    return claims
