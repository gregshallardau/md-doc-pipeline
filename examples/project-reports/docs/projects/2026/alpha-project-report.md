---
title: Project Report — Alpha Initiative
client: Beta Systems Ltd
product: Software Delivery Project
project_number: PRJ-2026-001
output_pdf: Alpha-Project-Report-2026.pdf
output_docx: Alpha-Project-Report-2026.docx
---

{% include "templates/org-header.md" %}

# {{ title }}

**Client:** {{ client }}
**Project Number:** {{ project_number }}
**Project:** {{ product }}
**Report Date:** {{ report_date }}
**Version:** {{ version }}
**Status:** {{ status | upper }}

---

## Project Summary

This report confirms the current status of **{{ product }}** for **{{ client }}** as at **{{ report_date }}**.

---

## Deliverables

| Deliverable | Description | Budget | Status |
|---|---|---|---|
| Phase 1 — Discovery | Requirements gathering & scoping | $25,000 | Complete |
| Phase 2 — Build | Core feature development | $80,000 | In Progress |
| Phase 3 — Testing | QA and user acceptance testing | $20,000 | Pending |
| Phase 4 — Deployment | Production release & handover | $15,000 | Pending |
| Support — Year 1 | Post-launch support retainer | $24,000 | Pending |

---

## Key Conditions

1. **Invoices** are due and payable within 30 days of issue.
2. **Scope changes** must be approved in writing before work commences.
3. Any **material change** to requirements must be notified to the project manager immediately.
4. This report is subject to the full terms and conditions of the **{{ client }}** project agreement.

---

## Next Steps

- [ ] Review and sign the project authority form
- [ ] Confirm payment schedule
- [ ] Return a signed copy of this report to {{ author }}
- [ ] Await Phase 2 milestone delivery (expected 14 days)

---

{% include "templates/confidentiality-footer.md" %}
