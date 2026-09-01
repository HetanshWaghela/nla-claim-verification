# Phase 3b labeling notes (running)

## Rule refinement mid-run (2026-08-16)
Slice-0 worker surfaced an edge case: prediction claims with checkable FALSE premises
(e.g. "final token 'X' will be followed by Y" when the text's final token is not X).
- Slices 0-3: labeled under original rule (such claims -> UNVERIFIABLE).
- Slices 4-11: labeled under refined rule (such claims -> RELATED_FALSE, premise noted).

## MANDATORY reconciliation pass (before the merge is final)
One dedicated worker re-examines every UNVERIFIABLE+COGNITION claim from shards 000-003
whose claim_text asserts a premise about the text's actual ending/content, and relabels
under the refined rule. All relabels logged with before/after. Merge is not final until
this pass completes and its evidence file (results/phase3_label_reconciliation.json) exists.

## Observations from slice 0 (for the write-up)
- UNRELATED_FALSE count: 0/246 - all fabrications thematically on-topic, independently
  confirming the NLA paper's "thematically faithful confabulation" claim in our data.
- SWE-chat contexts: explanations frequently misquote the exact truncated final token
  (wrong timestamps/UUIDs) even when correctly identifying the truncation type.

## c141 curiosity (2026-08-16)
Context c141 (SWE-chat, stratum B - the same context that produced the Phase 2a norm
outlier) contains an embedded fake system-reminder block with directive text. Labeling
workers correctly treated it as data, not instructions. Note for the write-up: real
agent transcripts contain adversarial/instruction-shaped content; any LLM-in-the-loop
pipeline over such data must treat source text as untrusted (ours did, by explicit rule).

## OUTSTANDING DEBT (2026-08-16): human verification not yet performed
The seed-0 blind sample was invalidated (answer key viewed before/during labeling).
A fresh seed-1 sample exists (results/human_label_sample_v2.md). The human blind pass
has NOT been done. A Fable third-judge check (below) substitutes for pipeline-unlock
purposes ONLY. The write-up may not claim human verification until the human completes
a blind pass on an unburned sample. This note may not be deleted, only marked PAID.

## Recurrence-counting noise (2026-08-16, from R0's internal redundancy accident)
R0's internal forks produced independent recurrence judgments that diverged on 63/246
claims (~26%) before aggregation. Implication: recurrence counts are noisier than labels;
Phase 6 must present the recurrence-aggregated excess variant with this caveat, and the
recurrence-count baseline (Table 2) inherits it. Worker prompts from R3 on explicitly
forbid sub-delegation.

## DEBT STATUS UPDATE (2026-08-23): human verification PAID, with disclosure
The human labeled the seed-0 sample (not v2): 46/50 = 92% agreement, exactly 1
TRUE<->FALSE crossing. Disclosure: the seed-0 answer key had been viewed once ~7 days
prior; however the human disagreed with the key on 4 items (c074/0/003, c230/0/010,
c146/0/009, c130/0/007), evidencing independent judgment rather than recall. Recorded in
results/human_blindlabel_check.json (superseded by this note) and the raw comparison
above. v2 (never-seen sample) remains available for an untainted rerun; optional.
Write-up phrasing: "I hand-labeled 50 claims blind to my own prior review; 92% agreement,
one true-vs-false disagreement" + the disclosure sentence.
