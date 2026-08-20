---
domain_id: consumer-electronics-support
version: 1.0.0
subdomains:
  - billing-duplicate-charge
  - billing-refund-request
  - billing-subscription-cancellation
  - billing-invoice-discrepancy
  - technical-device-wont-power-on
  - technical-connectivity-dropout
  - technical-firmware-update-failure
  - technical-app-pairing-issue
  - account-login-lockout
  - account-email-change
  - account-two-factor-recovery
  - shipping-delayed-delivery
  - shipping-wrong-item-received
  - shipping-damaged-on-arrival
  - product-warranty-claim
  - product-missing-accessory
  - product-compatibility-question
  - other-accessibility-request
  - other-data-export-request
  - other-feedback-complaint
---

# Support Domain: Consumer Electronics Retailer

Conversations are between a **customer** of a mid-sized online retailer selling consumer
electronics — headphones, smart speakers, wearables, small home devices — and a **support
agent** employed by that retailer.

The subdomains listed in the front matter above are the situations a conversation may be about.
A run assigns one to each conversation by a seeded draw, and the model elaborates a specific
situation within it. That two-level split is what lets a corpus be stratified by subdomain and
compared across runs while the specific situation stays varied (FR-008d, FR-012b).

## What a conversation looks like

- The **customer opens**, describing their problem in their own words. They are not a technical
  writer: they may be terse, frustrated, rambling, or unclear about what went wrong.
- The **agent** responds with a plausible support reply — acknowledging, asking a clarifying
  question, explaining, or resolving. They are competent and polite without being robotic.
- Turns alternate strictly. The conversation concerns **one** issue from start to finish.
- The exchange should read like a real support interaction, including ordinary friction:
  a customer who does not know their order number, an agent who needs to check something,
  a step that does not work the first time.

## What must never appear

Every value in these conversations is **fabricated**. Do not write real email addresses, real
phone numbers, real payment card numbers, or real government identifiers, and do not reproduce
any real person's details.

Where a conversation needs an identifier-shaped value, take it from a range reserved for fiction,
because those ranges cannot belong to anyone:

- **Email** — `@example.com`, `@example.org`, `@example.net`, or any `.test` / `.invalid` domain.
- **Phone** — a full ten-digit number whose exchange is `555` and whose line is `0100`–`0199`,
  such as `212-555-0142`. A seven-digit `555-0142` is not recognised as a phone number at all.
- **Payment card** — the published network test numbers, such as `4111 1111 1111 1111`.
- **Order and account numbers** — invent freely: `ORD-4417`, `AC-99812`.

Never write a Social Security number or other government identifier, even a made-up one. No range
is reserved for fiction there, so any such value blocks the record and it cannot be exempted.

This is the primary control on privacy; the automated scan is a safety net that confirms it held,
not a substitute for it (spec Assumptions).

## Tone and variation

Vary register across conversations: some customers are formal, some casual, some annoyed. Vary
resolution: not every ticket ends happily, and the assigned resolution status says how this one
ends. Vary length naturally within the turn count the run asks for — do not pad a short exchange
to fill turns, and do not compress a complex one.
