---
title: Pulse Monitor — On-Call Handbook
output_pdf: Pulse-On-Call-Handbook-1.8.pdf
date: 1 April 2026
---

{% include "company-header.md" %}

# {{ title }}

{% include "product-disclaimer.md" %}

---

## What is Pulse?

**{{ product }}** is Blueshift's infrastructure monitoring platform. It watches your services, evaluates alert rules in real time, and pages the right people when something breaks — so you can sleep through the nights that matter.

This handbook tells on-call engineers what to do when Pulse wakes them up.

---

## Alert Severity Levels

| Level | Colour | Response Time | Wake? |
|---|---|---|---|
| P1 — Critical | 🔴 Red | 5 minutes | Yes |
| P2 — High | 🟠 Orange | 30 minutes | Yes (business hours: 15 min) |
| P3 — Medium | 🟡 Yellow | 4 hours | No |
| P4 — Low | ⚪ Grey | Next business day | No |

All P1 and P2 alerts route to the on-call rotation via PagerDuty. P3/P4 alerts go to Slack only.

---

## Responding to a P1

1. **Acknowledge** the alert in PagerDuty within 5 minutes to stop escalation.
2. **Join** the incident Slack channel — Pulse creates it automatically (`#inc-YYYYMMDD-HHmm`).
3. **Assess** — check the Pulse dashboard for the blast radius. What's healthy? What's not?
4. **Communicate** — post an initial update in the channel within 10 minutes, even if it's just *"Investigating, no impact confirmed yet."*
5. **Escalate** if you need more hands. Page secondary via PagerDuty or post in `#engineering`.
6. **Resolve** — mark the alert resolved in Pulse once the issue is confirmed fixed.
7. **Write an incident report** within 24 hours (use the `#post-mortems` Notion template).

---

## Common Alert Runbooks

### High Error Rate (`error_rate > 5%`)

- Check recent deploys — correlate with the Pulse deploy marker timeline
- Look at the top error types in Nova Analytics → *Error Breakdown* dashboard
- If a bad deploy: roll back via `deploy rollback --service <name> --env prod`
- Alert {{ alert_email }} if customer impact is confirmed

### Database Connection Pool Exhausted

- Check slow query log — `pulse-cli logs db --last 30m --filter slow`
- Kill long-running queries if safe to do so
- Scale the connection pool in `config/db.yml` (requires a deploy)

### Memory Usage > 90%

- Identify the process: `pulse-cli top --env prod --sort mem`
- Restart the affected pod if safe: `kubectl rollout restart deployment/<name>`
- Check for memory leaks in the last 7 days of memory trend data in Nova

---

## Escalation Contacts

| Role | Contact | When |
|---|---|---|
| On-call primary | PagerDuty rotation | First response |
| Platform lead | Slack @platform | DB / infrastructure issues |
| Product manager | Slack @product-oncall | Customer-facing P1s |
| Support | {{ alert_email }} | When customers are impacted |

---

{% include "legal-footer.md" %}
