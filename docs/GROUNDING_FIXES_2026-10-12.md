# Grounding fixes, 12 October 2026

## What changed

1. **Uncited sentences are no longer dropped.** `parse_claims` returns every
   sentence. A sentence with no citation (before, between or after citation
   groups, or in an answer with none) has `source_numbers == []` and
   `uncited == True`. `GroundingEvaluator` gives it status `uncited` without an
   LLM decomposition or NLI call. Uncited claims are in the denominator of every
   claim rate, and an answer containing one cannot be fully grounded.
2. **A raw NLI contradiction needs a conflict cue.** After the overlap check,
   `apply_contradiction_guard` keeps a contradiction only if the pair shows a
   negation, modality, number, quantifier or antonym difference
   (`conflict_cues`). Otherwise it is downgraded to `neutral` and the reason is
   recorded. Raw labels and probabilities are still preserved. A downgrade can
   turn `contradicted` into `unsupported`; it can never produce `grounded`.
   Pass `require_conflict_cue=False` (also on `SemanticGrounder`) to compare
   with the previous behavior.
3. **Replay harness.** `scripts/record_eval_run.py` freezes answers, retrieved
   sources, claim decompositions and full grounding diagnostics from one live
   run. `scripts/replay_grounding.py` re-runs evidence selection, NLI and the
   guards, lists status changes, and preserves raw/effective labels, selected
   evidence, probabilities and guard reasons in its diagnostic report.
4. **Metric transparency.** Uncited claims are surfaced as a separate count/rate
   in the live evaluation and framework POC. Raw NLI contradictions downgraded
   by the relation guard are counted separately so that effective claim status
   does not hide the guard's intervention.

## Known limitations

* The conflict-cue list is small and heuristic. The smoke suite has only six
  labelled contradictions, all numeric or negation conflicts, so antonym and
  modality cues are unit-tested but not validated on held-out data. A genuine
  contradiction with no cue is reported as `unsupported`, not `contradicted`.
* Claim-term-coverage and conflict-cue checks, plus the evaluator's own
  content-overlap check, are three overlapping lexical layers. Consolidate them
  once held-out labelled data exists.
* Not addressed: GV.RR-04 modality drift (generation), the Organizational
  Profile NLI false negative, and compound-claim partial support. Each needs
  its exact claim and evidence recorded as a labelled test first.
* The sandbox tests used stubs for model libraries. They are not live-model
  validation.
