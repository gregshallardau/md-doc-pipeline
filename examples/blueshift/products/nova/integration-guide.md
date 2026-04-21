---
title: Nova Analytics — REST API Integration Guide
output_pdf: Nova-Integration-Guide-3.2.pdf
date: 1 April 2026
---

{% include "company-header.md" %}

# {{ title }}

{% include "product-disclaimer.md" %}

---

## Overview

The {{ product }} REST API lets you push event data, pull computed metrics, and trigger report generation from your own systems. All endpoints use HTTPS and authenticate with a Bearer token issued from your workspace settings.

**Base URL:** `https://api.nova.blueshift.io/v2`

---

## Authentication

Generate an API key from **Settings → Integrations → API Keys**. Keys are scoped to a workspace and carry a `read`, `write`, or `admin` permission level.

```http
Authorization: Bearer nva_live_xxxxxxxxxxxxxxxxxxxx
```

---

## Sending Events

```http
POST /events
Content-Type: application/json

{
  "stream": "web_sessions",
  "timestamp": "2026-04-01T09:00:00Z",
  "properties": {
    "user_id": "usr_abc123",
    "page": "/dashboard",
    "session_duration_s": 142
  }
}
```

Responses:

| Code | Meaning |
|---|---|
| 200 | Event accepted |
| 400 | Malformed payload |
| 429 | Rate limit exceeded (retry after header set) |

---

## Querying Metrics

```http
GET /metrics?name=revenue_per_user&from=2026-03-01&to=2026-03-31&granularity=day
```

Returns a JSON array of `{ date, value }` objects. Dates are ISO 8601, values are floats.

---

## Rate Limits

Free tier: 1,000 events/min, 100 queries/min.
Pro and Enterprise: contact {{ support_email }} for custom limits.

---

{% include "legal-footer.md" %}
