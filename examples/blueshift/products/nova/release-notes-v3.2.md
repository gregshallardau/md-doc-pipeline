---
title: Nova Analytics — Release Notes v3.2
output_pdf: Nova-Release-Notes-3.2.pdf
date: 1 April 2026
---

{% include "company-header.md" %}

# {{ title }}

{% include "product-disclaimer.md" %}

---

## What's New in {{ version }}

**Codename: {{ codename }}** — our biggest release yet.

### Real-Time Collaboration

Multiple analysts can now work on the same dashboard simultaneously. Changes sync in under 200ms across all connected sessions — no more "last save wins" conflicts.

### AI-Assisted Anomaly Detection

{{ product }} now surfaces statistical anomalies automatically using an embedded ML model trained on your historical data. Flagged events appear inline with a confidence score and a one-click drill-down.

### Custom Formula Engine

Write formulas in plain English using the new expression language:

```
revenue_per_user = total_revenue / active_users WHERE active_users > 0
rolling_7d_avg = ROLLING_AVG(daily_sessions, 7)
```

### Performance Improvements

| Metric | v3.1 | v3.2 | Improvement |
|---|---|---|---|
| Dashboard load | 2.8s | 0.9s | 68% faster |
| Export (10k rows) | 14s | 3s | 79% faster |
| Query compile | 400ms | 80ms | 80% faster |

---

## Bug Fixes

- Fixed an issue where date filters would reset on page refresh in Safari
- Resolved a race condition in scheduled report delivery that caused duplicate emails
- Corrected timezone handling for UTC+13 and UTC+14 offsets

---

## Upgrading

{{ product }} {{ version }} is a drop-in upgrade. No schema migrations required.

Run `nova-cli upgrade --channel stable` or update via your organisation's admin panel.

Contact {{ support_email }} with any questions.

---

{% include "legal-footer.md" %}
