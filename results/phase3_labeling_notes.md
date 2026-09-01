# Labeling notes

## Rule refinement mid-run (2026-08-16)
An edge case surfaced in the first labeling slice: prediction claims with a checkable false premise, for example "the final token X will be followed by Y" when the text's final token is not X.

- Slices 0-3 were labeled under the original rule (such claims -> UNVERIFIABLE).
- Slices 4-11 were labeled under the refined rule (such claims -> RELATED_FALSE, premise noted).
- A reconciliation pass then re-examined every UNVERIFIABLE cognition claim from slices 0-3 whose text asserts a premise about the source's actual ending or content, and relabeled under the refined rule. Every relabel is logged with before and after in `phase3_label_reconciliation.json`.

## Observations from the first slice
- UNRELATED_FALSE: 0 of 246. Every fabrication was thematically on-topic, matching the NLA paper's description of thematically faithful confabulation.
- Agent-transcript contexts: explanations often misquote the exact truncated final token (wrong timestamps or UUIDs) even when they identify the truncation type correctly.

## Context c141
This agent-transcript context, the same one that produced the single activation-norm outlier, contains an embedded instruction-shaped block. The labeling prompt treats source text as data, not instructions, and the labels for this context are ordinary. Any LLM-in-the-loop pipeline over real agent transcripts needs that rule.

## Recurrence-count noise
Independent recurrence judgments on the same 246 claims diverged on 63 (about 26%) before aggregation. Recurrence counts are therefore noisier than labels. The recurrence-aggregated excess variant and the recurrence-count baseline both inherit this caveat, and the write-up says so.

## Human label checks
- Seed-0 sample (50 claims), labeled 2026-08-23: 46/50 agreement (92%), one TRUE/FALSE crossing. The answer key for this sample had been viewed once about a week before labeling, so this is not a fully unexposed pass. The four disagreements (c074/0/003, c230/0/010, c146/0/009, c130/0/007) are evidence of independent judgment rather than recall. Record: `human_blindlabel_check.json`.
- Seed-1 sample (50 claims, never previously viewed), labeled 2026-08-25: 43/50 agreement (86%), three TRUE/FALSE crossings, all cases where the human judged a model-TRUE claim RELATED_FALSE. Record: `human_blindlabel_check_v2.json`, raw labels in `human_labels_v2_hetansh.md`.
- Second model family (Claude Fable 5.1) on the seed-0 sample: 43/50. Record: `fable_thirdjudge_check.json`.

In every human disagreement the human was stricter than the labeling model, so the reported fabrication rate is more likely an undercount than an overcount.
