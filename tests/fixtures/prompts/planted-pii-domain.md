---
domain_id: planted-pii-fixture
version: 1.0.0
subdomains:
  - contact-details-update
  - account-recovery
---

# Fixture domain: deliberately elicits identifier-shaped content

**This document is a test fixture, not a corpus input.** It exists to prove the privacy gate
blocks, so it instructs the model to do the one thing `prompts/samples/consumer-electronics-support.md` forbids.

Conversations here are about a customer supplying contact or identity details to a support agent.
The customer states a full email address, a full phone number, and a government identifier in
plain text — values a real corpus must never contain.

The values used here must be **real-looking rather than reserved for fiction**: an address at a
plausible company domain rather than `example.com`, a number outside the `555-0100`–`555-0199`
range. Reserved-for-fiction values would be exempted by range (FR-021c) and would not exercise
the blocking path this fixture exists to test.
