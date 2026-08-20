---
rubric_id: coherence-v2
version: 2.0.0
criteria:
  single_issue: 0.30
  role_consistency: 0.25
  conversational_flow: 0.25
  metadata_fit: 0.20
---

# Coherence Rubric v2

The judge scores a generated conversation against each criterion below on a **continuous 0.0–1.0
scale**. The pipeline computes the record's coherence score as the weighted mean using the weights
in the front matter (FR-009p). A holistic score is not requested and would not be used.

Scores are recorded on the record alongside this rubric's identifier, because a bare number cannot
be compared across rubric versions (FR-009i).

## How to score

**Use the whole scale.** The reference points under each criterion are landmarks, not the only
permitted answers — 0.72 and 0.88 are ordinary scores. A criterion should land wherever the
conversation actually sits between the landmarks.

**Reserve 1.0.** It means *no observable flaw of this kind*, not "good enough" or "nothing jumped
out". Most competent conversations have some small imperfection and belong in the 0.75–0.95 band.
If you find yourself giving 1.0 to most conversations, you are grading leniently rather than
observing carefully; re-read the turns and find the weakest moment.

**Score what is written**, not what could be improved. Ordinary support friction — a repeated
question, an unclear customer, an agent who needs to check something — is realistic and must not
lower a score. Judge the exchange as an artifact of a support system, not as prose.

**Score each criterion independently.** A conversation can flow beautifully while ignoring its
assigned metadata; do not let one judgement drag the others toward it.

> **v2 note.** v1 offered exactly three landmarks per criterion (1.0 / 0.5 / 0.0). Judges took
> them as the only options and defaulted to the top one: a 20-record sample produced three
> distinct scores, 70% of them a perfect 1.0, which left the 0.8 threshold unable to separate
> anything. The criteria below are unchanged in substance; what changed is that the scale is
> continuous and the top of it has to be earned.

## single_issue (weight 0.30)

Does the whole exchange concern one support issue?

- **1.0** — One issue, raised at the start and carried through every turn with no digression.
- **0.8** — One issue throughout, with a brief aside that resolves immediately.
- **0.5** — A second, loosely related concern appears but does not take over.
- **0.2** — Two issues share the conversation roughly equally.
- **0.0** — The conversation drifts to an unrelated issue, or covers several at once.

## role_consistency (weight 0.25)

Does each speaker behave like themselves throughout?

- **1.0** — The customer stays the person with the problem; the agent stays the person helping.
  Neither has knowledge they could not have.
- **0.8** — Consistent, but one turn is slightly out of register — an unusually technical customer,
  an oddly informal agent.
- **0.5** — One turn blurs the roles: the customer explains internal policy, or the agent describes
  the problem as their own.
- **0.2** — Repeated blurring; the reader has to work out who is speaking.
- **0.0** — The roles are swapped or interchangeable.

## conversational_flow (weight 0.25)

Does each turn respond to the one before it?

- **1.0** — Every turn follows from the last. Questions are answered; references resolve.
- **0.8** — Follows throughout, with one transition that is abrupt but not broken.
- **0.5** — One or two turns are non-sequiturs, or a question goes unanswered.
- **0.2** — Several turns ignore what preceded them.
- **0.0** — The turns read as independent statements rather than an exchange.

## metadata_fit (weight 0.20)

Does the conversation match the ticket metadata it was generated for?

- **1.0** — Category, priority, channel, and resolution status all fit what happens. A `resolved`
  ticket reaches a resolution; an `abandoned` one trails off; an `urgent` one reads urgent; a
  `phone` transcript reads spoken rather than written.
- **0.8** — All four fit, though one is carried more by assertion than by the content.
- **0.5** — One attribute is a poor fit — an `urgent` ticket that reads routine.
- **0.2** — Two or more attributes are a poor fit.
- **0.0** — The conversation contradicts its metadata.
