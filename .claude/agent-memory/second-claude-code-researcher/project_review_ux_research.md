---
name: project-review-ux-research
description: ontologylab local tool's proposed→verified entity/relation review UX — research findings on HITL curation patterns for planning next features
metadata:
  type: project
---

ontologylab is a local-first tool where every LLM-extracted entity/relation is born "proposed" and requires human approval to become "verified" before shipping. Current UX (as of 2026-07-14): CLI approve/reject + a minimal web review queue with bulk-approve-by-filter.

A research pass (2026-07-14) was done on HITL curation/verification UX for LLM-extracted knowledge graphs (2025-2026 sources) to plan next features. Full brief was returned inline in that conversation (not saved to a file per house rule against report .md files) — key takeaways below for continuity.

**Why:** planning next iteration of the review UX/pipeline beyond the current CLI + minimal bulk-filter web queue.

**Ranked improvement candidates identified (see conversation for full brief with sources):**
1. Confidence-ordered queue + auto-approve/auto-reject thresholds with an ops-exposed threshold control (S)
2. Entity-centric review mode (review one entity + all its mentions/relations together) instead of row-by-row (M)
3. Second-LLM-as-critic pre-scoring for triage ONLY, not auto-approve — disagreement between extractor and critic model routes to top of queue (M)
4. Source-span highlighting + rationale/citation display in the review UI to build reviewer trust and speed (S/M)
5. Merge-review UI for entity resolution (side-by-side diff, confidence + accept/reject fuzzy-duplicate merges) (M)
6. Keyboard-first review flow (single-key approve/reject/skip, no mouse) (S)

**Key risk flagged in research:** LLM pre-labels can induce anchoring/automation bias in human reviewers (2025 studies: Gu et al. and a 2,784-participant randomized experiment cited in HDSR "Bias in the Loop", Spring 2026) — reviewers become less likely to correct AI suggestions, especially when correction requires extra effort. This argues for NOT auto-approving on LLM-critic score, and for UI patterns that don't visually anchor on a single suggested answer (e.g. showing rationale/evidence rather than a pre-filled verdict).

**Tools referenced as prior art:** Prodigy (active learning, uncertainty sampling), Argilla (suggestion scores + filters, agreement metrics, span highlighting), Label Studio (prediction-score sort, review workflow), CleanGraph (github.com/nlp-tlp/CleanGraph — plugin-based KG refinement with one-click accept suggestions), PaperTrail (CHI'26 claim-evidence provenance interface), ProVe (automated provenance verification against text sources).

**How to apply:** when scoping the next review-UX feature work in ontologylab, check whether these candidates are still relevant (re-verify against current code/UI state before recommending, per verify-before-recommend rule) rather than assuming this snapshot is current.
