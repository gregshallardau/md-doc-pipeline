---
title: All supported diagram families
---

# Flowchart diagram

```mermaid
flowchart LR
  A --> B
  B --> C
```

<!-- pagebreak -->

# Pie diagram

```mermaid
pie
"A" : 30
"B" : 70
```

<!-- pagebreak -->

# Donut diagram

```mermaid
donut
"A" : 30
"B" : 70
```

<!-- pagebreak -->

# Bar diagram

```mermaid
bar
"Jan" : 10
"Feb" : 20
```

<!-- pagebreak -->

# Gauge diagram

```mermaid
gauge
  value 42
  min 0
  max 100
```

<!-- pagebreak -->

# Sequence diagram

```mermaid
sequenceDiagram
  Alice->>Bob: Hi
  Bob-->>Alice: Hello
```

<!-- pagebreak -->

# Timeline diagram

```mermaid
timeline
  2021 : Founded
  2022 : Launched
```

<!-- pagebreak -->

# Gantt diagram

```mermaid
gantt
  section S
  Task A : a1, 2024-01-01, 3d
```

<!-- pagebreak -->

# Mindmap diagram

```mermaid
mindmap
  root
    branch1
    branch2
```

<!-- pagebreak -->

# Er diagram

```mermaid
erDiagram
  CUSTOMER ||--o{ ORDER : places
```

<!-- pagebreak -->

# State diagram

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Running
  Running --> [*]
```
