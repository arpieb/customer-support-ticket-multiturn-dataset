---
rubric_id: coherence-v1
version: 1.0.0
criteria:
  single_issue: 0.30
  role_consistency: 0.25
  conversational_flow: 0.25
  metadata_fit: 0.20
---

# Coherence Rubric v1

The judge scores a generated conversation against each criterion below on a **0.0–1.0** scale.
The pipeline computes the record's coherence score as the weighted mean using the weights in the
front matter, which must sum to 1 (FR-009p). A holistic score is not requested and would not be
used: it would mean whatever the judging model read this prose to mean, and would drift with the
model.

Scores are recorded on the record alongside this rubric's identifier, because a bare number
cannot be compared across rubric versions (FR-009i).

## single_issue (weight 0.30)

Does the whole exchange concern one support issue?

- **1.0** — One issue, raised at the start and carried through every turn.
- **0.5** — A second, loosely related concern appears but does not take over.
- **0.0** — The conversation drifts to an unrelated issue, or covers several at once.

## role_consistency (weight 0.25)

Does each speaker behave like themselves throughout?

- **1.0** — The customer stays the person with the problem; the agent stays the person helping.
  Neither has knowledge they could not have.
- **0.5** — One turn blurs the roles — the customer explains internal policy, or the agent
  describes the problem as their own.
- **0.0** — The roles are swapped or interchangeable.

## conversational_flow (weight 0.25)

Does each turn respond to the one before it?

- **1.0** — Every turn follows from the last. Questions are answered; references resolve.
- **0.5** — One or two turns are non-sequiturs, or a question goes unanswered.
- **0.0** — The turns read as independent statements rather than an exchange.

## metadata_fit (weight 0.20)

Does the conversation match the ticket metadata it was generated for?

- **1.0** — Category, priority, channel, and resolution status all fit what happens. A
  `resolved` ticket reaches a resolution; an `abandoned` one trails off; an `urgent` one reads
  urgent; a `phone` transcript reads spoken rather than written.
- **0.5** — One attribute is a poor fit — an `urgent` ticket that reads routine.
- **0.0** — The conversation contradicts its metadata.

## Notes for the judge

Judge what is written, not what could be improved. Ordinary support friction — a repeated
question, a customer who is unclear, an agent who needs to check something — is realistic and
should not lower a score. Score the exchange as an artifact of a support system, not as prose.
