---
title: Blueshift Onboarding Proposal — Stormfront Inc
output_pdf: Stormfront-Onboarding-Proposal.pdf
date: 1 April 2026
product: Nova Analytics + Pulse Monitor
contract_start: 1 May 2026
seats: 25
tier: Enterprise
---

{% include "company-header.md" %}

# {{ title }}

**Prepared for:** {{ client_contact }}, {{ client }}
**Account Manager:** {{ account_manager }}
**Date:** {{ date }}
**Status:** {{ status | upper }}

---

## Welcome to Blueshift

We're excited to bring {{ client }} onto the Blueshift platform. This proposal covers your {{ tier }} onboarding for **{{ product }}**, starting {{ contract_start }}.

---

## What You're Getting

### Nova Analytics — {{ seats }} seats

Real-time dashboards, AI-assisted anomaly detection, and a custom formula engine for {{ client }}'s data team. Your workspace will be pre-loaded with starter dashboards for web sessions, revenue metrics, and user retention.

### Pulse Monitor — Unlimited checks

Always-on infrastructure monitoring for {{ client }}'s production environment. We'll configure alert routing to your PagerDuty account and set up a dedicated `#blueshift-alerts` Slack channel as part of kickoff.

---

## Onboarding Timeline

| Week | Activity | Owner |
|---|---|---|
| 1 | Kickoff call, credential handover | {{ account_manager }} + {{ client_contact }} |
| 2 | Nova workspace setup, SSO configuration | Blueshift Platform |
| 2 | Pulse agent install on {{ client }} infra | {{ client }} DevOps |
| 3 | Dashboard customisation workshop (2hr) | {{ account_manager }} |
| 4 | Alert tuning & runbook review | Blueshift + {{ client }} |
| 5 | Go-live sign-off | Both parties |

---

## Pricing

| Product | Tier | Seats | Monthly |
|---|---|---|---|
| Nova Analytics | Enterprise | {{ seats }} | $4,250 |
| Pulse Monitor | Enterprise | Unlimited checks | $1,800 |
| Onboarding & support | Dedicated CSM | — | Included |
| **Total** | | | **$6,050/mo** |

*Billed annually. First invoice raised on {{ contract_start }}.*

---

## Next Steps

1. Review and sign this proposal
2. Return signed copy to {{ account_manager }} at hello@blueshift.io
3. We'll issue your workspace credentials within 24 hours of signing

Questions? Contact {{ account_manager }} or reach us at hello@blueshift.io.

---

{% include "legal-footer.md" %}
