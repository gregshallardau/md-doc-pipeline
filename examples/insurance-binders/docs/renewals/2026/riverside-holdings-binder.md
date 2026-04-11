---
title: Insurance Binder — Riverside Holdings Pty Ltd
client: Riverside Holdings Pty Ltd
product: Commercial Package Policy
insurer: QBE Insurance (Australia) Limited
policy_number: QPK-2026-00441
output_pdf: Riverside-Holdings-Binder-2026.pdf
output_docx: Riverside-Holdings-Binder-2026.docx
---

{% include "templates/aib-header.md" %}

# {{ title }}

**Insured:** {{ client }}
**Policy Number:** {{ policy_number }}
**Insurer:** {{ insurer }}
**Renewal Date:** {{ renewal_date }}
**Version:** {{ version }}
**Status:** {{ status | upper }}

---

## Confirmation of Cover

We are pleased to confirm that cover has been bound for **{{ client }}** under the above policy for the period commencing **{{ renewal_date }}**.

This binder is issued pending receipt of the formal policy document from {{ insurer }}.

---

## Schedule of Cover

| Section | Cover | Limit of Liability | Excess |
|---|---|---|---|
| Property — Material Damage | Buildings & Contents | $5,000,000 | $2,500 |
| Property — Business Interruption | Loss of Revenue | $2,000,000 (12 months) | 7 days |
| General Liability | Public & Products | $20,000,000 | $2,500 |
| Management Liability | D&O / Employment Practices | $5,000,000 | $5,000 |
| Machinery Breakdown | All plant & equipment | $500,000 | $1,000 |

---

## Key Conditions

1. **Premium** is due and payable within 30 days of the renewal date.
2. **Security** must be maintained at the insured premises at all times.
3. Any **material change** in risk must be notified to the broker immediately.
4. This binder is subject to the full terms and conditions of the **{{ insurer }}** Commercial Package policy wording.

---

## Next Steps

- [ ] Review and sign the client authority form
- [ ] Confirm premium payment method
- [ ] Return a signed copy of this binder to Acme IB
- [ ] Await formal policy documents (expected 14 days)

---

{% include "templates/confidentiality-footer.md" %}
