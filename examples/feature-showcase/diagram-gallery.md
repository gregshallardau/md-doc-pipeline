---
title: All supported diagram families
---

# Diagram gallery

Every Mermaid diagram family md-doc draws, each with the syntax people use in practice. The
diagrams share one design system: structural diagrams take their colours from the theme, data
charts start from the brand colours then continue with an accessible palette, and everything renders at body-text size.

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

<!-- pagebreak -->

## Class

```mermaid
classDiagram
    class Animal {
        <<abstract>>
        +String name
        -int age
        +makeSound()* void
        +getCount()$ int
    }
    class Duck {
        +swim()
        +quack()
    }
    class Fish {
        -int sizeInFeet
        -canEat()
    }
    class Pond {
        +List~Duck~ ducks
    }
    Animal <|-- Duck
    Animal <|-- Fish
    Pond "1" *-- "many" Duck : contains
    Duck ..> Fish : eats
```

## User journey

```mermaid
journey
    title My working day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 4: Me, Cat
```

## Git graph

```mermaid
gitGraph
    commit id: "init"
    commit
    branch develop
    checkout develop
    commit id: "feature-a"
    branch feature
    checkout feature
    commit id: "wip" type: HIGHLIGHT
    checkout main
    merge develop tag: "v1.0"
    checkout feature
    commit
    checkout develop
    merge feature
    checkout main
    commit tag: "v1.1"
```

## Dark diagram

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart LR
    A([Request]) --> B{Cached?}
    B -->|yes| C[Serve cache]
    B -->|no| D[Render page]
    D --> C
```

<!-- pagebreak -->

## Quadrant chart

```mermaid
quadrantChart
    title Reach and engagement of campaigns
    x-axis Low Reach --> High Reach
    y-axis Low Engagement --> High Engagement
    quadrant-1 We should expand
    quadrant-2 Need to promote
    quadrant-3 Re-evaluate
    quadrant-4 May be improved
    Campaign A: [0.3, 0.6]
    Campaign B: [0.45, 0.23]
    Campaign C: [0.57, 0.69]
    Campaign D: [0.78, 0.34]
    Campaign E: [0.40, 0.34]
    Campaign F:::hot: [0.35, 0.78]
    classDef hot color: #d03b3b, radius : 7
```

## Sankey

```mermaid
sankey
Electricity grid,Heating and cooling - homes,113.726
Electricity grid,Industry,342.165
Electricity grid,Losses,56.691
Wind,Electricity grid,289.366
Solar,Electricity grid,59.901
Nuclear,Electricity grid,839.978
Gas,Electricity grid,26.861
Gas,Industry,46.477
Electricity grid,"Heating and cooling, commercial",88.14
```

<!-- pagebreak -->

## Radar

```mermaid
radar-beta
  title Restaurant comparison
  axis food["Food"], service["Service"], price["Price"]
  axis ambiance["Ambiance"], wait["Wait time"]
  curve a["Restaurant A"]{4, 3, 2, 4, 3}
  curve b["Restaurant B"]{3, 4, 3, 3, 5}
  max 5
```

## Treemap

```mermaid
treemap-beta
"Products"
    "Electronics"
        "Phones": 50
        "Computers": 30
        "Accessories": 20
    "Clothing"
        "Men's": 40
        "Women's": 40
"Services"
    "Support": 35
    "Training": 15
```

<!-- pagebreak -->

## Packet

```mermaid
---
title: "TCP Packet"
---
packet
0-15: "Source Port"
16-31: "Destination Port"
32-63: "Sequence Number"
64-95: "Acknowledgment Number"
96-99: "Data Offset"
100-105: "Reserved"
106: "URG"
107: "ACK"
108: "PSH"
109: "RST"
110: "SYN"
111: "FIN"
112-127: "Window"
128-143: "Checksum"
144-159: "Urgent Pointer"
160-191: "(Options and Padding)"
192-255: "Data (variable length)"
```

## Block

```mermaid
block
columns 1
  db(("DB"))
  blockArrowId6(down)
  block:ID
    A
    B["A wide one in the middle"]
    C
  end
  space
  D
  ID --> D
  C --> D
  style B fill:#e8eefc,stroke:#3c5aa8
```

<!-- pagebreak -->

## Kanban

```mermaid
kanban
  Todo
    [Create Documentation]
    docs[Create Blog about the new diagram]
  [In progress]
    id6[Create renderer so that it works in all cases]@{ priority: 'High' }
  id9[Ready for deploy]
    id8[Design grammar]@{ assigned: 'knsv' }
  id10[Ready for test]
    id4[Create parsing tests]@{ ticket: MC-2038, assigned: 'K.Sveidqvist', priority: 'High' }
    id66[last item]@{ priority: 'Very Low', assigned: 'knsv' }
  id11[Done]
    id5[define getData]
    id2[Title of diagram is more than 100 chars]@{ ticket: MC-2036, priority: 'Very High'}
```

## Architecture

```mermaid
architecture-beta
    group api(cloud)[API]
    service db(database)[Database] in api
    service disk1(disk)[Storage] in api
    service disk2(disk)[Storage] in api
    service server(server)[Server] in api
    service web(internet)[Internet]
    db:L -- R:server
    disk1:T -- B:server
    disk2:T -- B:db
    web:R --> L:server
```

<!-- pagebreak -->

## C4 container

```mermaid
C4Container
    title Container diagram for Internet Banking System
    System_Ext(email_system, "E-Mail System", "The internal Microsoft Exchange system")
    Person(customer, Customer, "A customer of the bank, with personal bank accounts")
    Container_Boundary(c1, "Internet Banking") {
        Container(spa, "Single-Page App", "JavaScript, Angular", "Provides all the Internet banking functionality to customers via their web browser")
        Container_Ext(mobile_app, "Mobile App", "C#, Xamarin", "Provides a limited subset of the Internet banking functionality")
        Container(web_app, "Web Application", "Java, Spring MVC", "Delivers the static content and the SPA")
        ContainerDb(database, "Database", "SQL Database", "Stores user registration information, hashed credentials, access logs")
        ContainerDb_Ext(backend_api, "API Application", "Java, Docker Container", "Provides Internet banking functionality via API")
    }
    System_Ext(banking_system, "Mainframe Banking System", "Stores all of the core banking information")
    Rel(customer, web_app, "Uses", "HTTPS")
    Rel(customer, spa, "Uses", "HTTPS")
    Rel(customer, mobile_app, "Uses")
    Rel_Back(database, backend_api, "Reads from and writes to", "sync, JDBC")
    Rel(email_system, customer, "Sends e-mails to")
    Rel(backend_api, email_system, "Sends e-mails using", "sync, SMTP")
    Rel(backend_api, banking_system, "Uses", "sync/async, XML/HTTPS")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Requirement

```mermaid
requirementDiagram
  requirement checkout_req {
    id: 1
    text: Orders must be payable online.
    risk: high
    verifymethod: test
  }
  functionalRequirement payment_req {
    id: 1.1
    text: Card payments must be authorised.
    risk: high
    verifymethod: test
  }
  element checkout_service {
    type: service
    docref: docs/checkout.md
  }
  checkout_req - contains -> payment_req
  checkout_service - satisfies -> payment_req
```

<!-- pagebreak -->

## ZenUML

```mermaid
zenuml
    title Order service
    @Actor Client
    @Database DB
    Client->OrderService.create(order) {
      valid = Validator.check(order)
      if(valid) {
        DB.save(order)
        return id
      } else {
        @return
        OrderService->Client: rejected
      }
    }
    par {
      OrderService->Email: confirmation
      OrderService->Analytics: track
    }
```

<!-- pagebreak -->

## Use case

```mermaid
usecase-beta
direction LR
actor Customer
actor Support
systemBoundary Storefront
  Browse("Browse catalogue")
  Checkout("Checkout")
end
systemBoundary Fulfilment
  Track("Track delivery")
end
Customer --> Browse
Customer --> Checkout
Customer --> Track
Support --> Track
Checkout ..> : include Browse
```

## Swimlanes

```mermaid
swimlane-beta LR
  subgraph Customer
    request[Request service]
    receive[Receive update]
  end
  subgraph Support
    triage[Triage request]
    answer[Send answer]
  end
  subgraph Engineering
    investigate[Investigate issue]
    fix[Prepare fix]
  end
  request --> triage
  triage -->|Known issue| answer
  triage -->|Needs code| investigate
  investigate --> fix --> answer
  answer --> receive
```

<!-- pagebreak -->

## Agent flow

```mermaid
agentflow-beta TB
  brief@{ shape: input, label: "Release brief" }
  flow drafting["Drafting Agent"]
    draft@{ shape: task, label: "Draft the notes" }
    search@{ shape: tool, label: "changelog_search" }
    tone@{ shape: refdoc, label: "Tone of voice" }
    draft --> search
    draft -.-> tone
  end
  flow review["Review Agent"]
    check@{ shape: task, label: "Check the claims" }
    ok@{ shape: decision, label: "Accurate?" }
    check --> ok
  end
  publish@{ shape: action, label: "Publish" }
  brief --> draft
  tone --> check
  ok -->|yes| publish
  ok --x|no| draft
```

## Tree view

```mermaid
treeView-beta
src/
  App.tsx :::highlight ## main component
  index.ts ## entry point
  components/
    Button.tsx
    Card.tsx
.env ## environment variables
package.json
```

<!-- pagebreak -->

## Ishikawa

```mermaid
ishikawa-beta
Blurry photo
  Process
    Out of focus
    Shutter speed too slow
  Equipment
    Lens
      Dirty lens
    Sensor
  User
    Shaky hands
  Environment
    Too dark
    Subject moved
```

## Venn

```mermaid
venn-beta
  title What makes a good feature
  set Desirable
  set Feasible
  set Viable
  union Desirable,Feasible["Buildable"]
  union Feasible,Viable["Sustainable"]
  union Desirable,Viable["Marketable"]
  union Desirable,Feasible,Viable["Ship it"]
```

<!-- pagebreak -->

## Cynefin

```mermaid
cynefin-beta
  title Incident response
  complex
    "Investigate root cause"
    "Run chaos experiment"
  complicated
    "Analyse performance data"
  clear
    "Restart service"
    "Apply known fix"
  chaotic
    "Page on-call immediately"
  confusion
    "Unknown failure mode"
  chaotic --> complex : "Stabilised"
  complex --> complicated : "Pattern found"
```

<!-- pagebreak -->

## Wardley map

```mermaid
wardley-beta
title Tea shop value chain
anchor Business [0.95, 0.63]
component Cup of Tea [0.79, 0.61]
component Tea [0.63, 0.81]
component Hot Water [0.52, 0.80]
component Kettle [0.43, 0.35] (build)
component Power [0.10, 0.70] (outsource)
Business -> Cup of Tea
Cup of Tea -> Tea
Cup of Tea -> Hot Water
Hot Water -> Kettle
Kettle -> Power
evolve Kettle 0.62
note "Standard power lets kettles evolve" [0.28, 0.40]
```

## Railroad

```mermaid
railroad-ebnf-beta
title "Arithmetic expressions"
expression = term ( ( "+" | "-" ) term )* ;
term = factor ( ( "*" | "/" ) factor )* ;
factor = number | "(" expression ")" ;
number = digit+ ;
```

<!-- pagebreak -->

## Event modeling

```mermaid
eventmodeling
tf 01 ui CartUI
tf 02 cmd AddItem { description: string, price: number }
tf 03 evt ItemAdded
tf 04 rmo CartItems ->> 03
tf 05 ui CartUI
rf 06 evt External.InventoryChanged
tf 07 pcr InventoryProcessor
tf 08 cmd ChangeInventory
tf 09 evt Cart.InventoryChanged
```
