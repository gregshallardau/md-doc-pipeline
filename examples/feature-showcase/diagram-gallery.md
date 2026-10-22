---
title: All supported diagram families
---

# Diagram gallery

Every Mermaid diagram family md-doc draws, each with the syntax people use in practice. The
diagrams share one design system: structural diagrams take their colours from the theme, data
charts use a fixed accessible palette, and everything renders at body-text size.

## Flowchart

```mermaid
flowchart LR
    A([Customer]) -- places order --> B[/Order form/]
    B --> C{Valid?}
    C -->|yes| D[Pick and pack]
    C -->|no| G[Reject]:::bad
    D --> E[(Inventory)]
    D --> I[Ship]
    G -.-> A
    classDef bad fill:#fdecea,stroke:#d03b3b
```

## Flowchart with groups

```mermaid
flowchart TD
    S([Start]) --> A[Collect requirements]
    subgraph Build
        A --> B{Approved?}
        B -->|yes| C[Implement]
        B -->|no| A
    end
    C --> D[Release]
    D --> E([Done])
```

<!-- pagebreak -->

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant W as Web app
    participant P as Payments
    participant S as Stock service
    C->>+W: Checkout
    W->>P: Authorise card
    alt card approved
        P-->>W: Approved
        W->>S: Reserve items
        S-->>W: Reserved
    else card declined
        P-->>W: Declined
        W--xC: Payment failed
    end
    Note over W,P: All calls are idempotent
    W-->>-C: Order confirmed
```

## State

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Review : submit
    Review --> Draft : changes
    Review --> Approved : approve
    Approved --> [*]
```

<!-- pagebreak -->

## Entity-relationship

```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE_ITEM : contains
    PRODUCT ||--o{ LINE_ITEM : "appears in"
    CUSTOMER {
        string id PK
        string name
        string email
    }
    ORDER {
        int id PK
        string customer_id FK
        date placed
    }
    LINE_ITEM {
        int order_id PK,FK
        string sku FK
        int quantity
    }
```

## Mind map

```mermaid
mindmap
  root((Strategy))
    Growth
      New markets
      Partnerships
    Efficiency
      Automation
      Cost review
    People
      Hiring
      Training
```

<!-- pagebreak -->

## Timeline

```mermaid
timeline
    title Company history
    section Early days
    2021 : Founded
    2022 : First customer : Seed round
    section Growth
    2023 : Series A
    2024 : 100 staff
```

## Gantt

```mermaid
gantt
    title Launch plan
    dateFormat YYYY-MM-DD
    section Design
    Research   :done, a1, 2026-01-05, 14d
    Wireframes :active, after a1, 10d
    section Build
    Backend    :b1, 2026-01-26, 30d
    Frontend   :crit, 2026-02-09, 25d
    Launch     :milestone, 2026-03-10, 0d
```

<!-- pagebreak -->

## Pie

```mermaid
pie title Revenue by region
    "North" : 42
    "South" : 23
    "East" : 18
    "West" : 11
    "Other markets" : 6
```

## Donut

```mermaid
donut showData
    "Done" : 64
    "In progress" : 24
    "Blocked" : 12
```

## Bar and line

```mermaid
xychart-beta
    title "Quarterly revenue"
    x-axis [Q1, Q2, Q3, Q4]
    y-axis "Revenue ($K)"
    bar [120, 145, 160, 190]
    line [110, 140, 150, 170]
```

## Gauge

```mermaid
gauge
    title Customer satisfaction
    value: 72
    max: 100
```
