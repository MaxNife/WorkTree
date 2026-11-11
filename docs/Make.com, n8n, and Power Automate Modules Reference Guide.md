# **Integration Platform Architecture Catalog**

## **A technical comparison of visual processing engines, execution primitives, and integration ecosystems across Make.com, n8n, and Microsoft Power Automate.**

---

# **Executive Summary & Architectural Overview**

Modern Integration Platform as a Service (iPaaS) solutions enable automated data flow across disparate software systems. While all major platforms achieve cross-application connectivity, their internal execution models, node primitive classifications, pricing tiers, and logic control structures differ significantly.

* **Make.com**: Focuses on a visual graph-based visual interface where operations represent single atomic executions. Data flows through strict JSON object mapping with explicit array iterators and aggregators.  
* **n8n**: Employs a node-based pipeline designed for technical flexibility. Data is passed between nodes as standard arrays of JSON objects, supporting both native UI configuration and inline JavaScript/Python script transformation.  
* **Microsoft Power Automate**: Built around sequential flow templates deeply tied to the Azure and Microsoft 365 ecosystem. Utilizes a block-based structure driven by Azure Logic Apps definitions and Expression Language (OData/WCF).

---

# **High-Level Architectural Comparison**

| Core Feature | Make.com | n8n | Microsoft Power Automate |
| :---- | :---- | :---- | :---- |
| **Execution Model** | Graph / Scenario-based | Node Workflow (DAG) | Sequential / Step-based Flow |
| **Primary Execution Unit** | Operation | Node Execution | Step / Action |
| **Data Payload Format** | Bundles (JSON objects) | Items (Array of JSON objects) | Dynamic Content / Outputs (JSON) |
| **Primary Logic Engine** | Built-in UI Directives & Formulas | Native JS/Python Code Nodes | Power Automate Expressions (WCF) |
| **Hosting Models** | SaaS (Cloud) | Self-Hosted (Docker/K8s), Cloud | Cloud (SaaS), On-Prem (Gateway) |
| **Extensibility** | Custom App Editor (JSON/REST) | Custom Nodes (TypeScript), Community | Custom Connectors (OpenAPI/Swagger) |

---

# **Platform 1: Make.com**

## **Scenario Structure & Data Model**

Make.com processes data via **Scenarios**. Scenarios consist of interconnected **Modules** that pass structured data containers called **Bundles**.

* **Triggers**: Initiate scenario execution (Instant/Webhook or Scheduled/Polling).  
* **Actions**: Perform CRUD operations or perform tasks in target applications.  
* **Searches**: Retrieve multiple records based on dynamic filter criteria.  
* **Iterators**: Break down arrays into individual data bundles.  
* **Aggregators**: Combine multiple data bundles into a single array structure.

## **Built-In System & Logic Tools**

| Module Category | Module Name | Architectural Purpose |
| :---- | :---- | :---- |
| **Flow Control** | Router | Splits scenario execution into multiple parallel or conditional paths |
| **Flow Control** | Iterator | Converts an array within a bundle into individual bundles for batch processing |
| **Flow Control** | Array Aggregator | Combines data from multiple bundles back into a single array |
| **Flow Control** | Text Aggregator | Concatenates text strings across incoming data bundles |
| **Flow Control** | Numeric Aggregator | Computes SUM, AVG, MIN, MAX over numerical bundle values |
| **Logic & Utilities** | Tools (Set/Get Variable) | Temporarily stores or retrieves dynamic variables during execution |
| **Logic & Utilities** | Increment Function | Generates sequential integer values across scenario iterations |
| **Logic & Utilities** | Sleep | Pauses execution for a specified duration (up to 300 seconds) |
| **HTTP / API** | Make an HTTP Request | Executes custom REST API calls (GET, POST, PUT, DELETE, PATCH) |
| **HTTP / API** | OAuth 2.0 Request | Handles authenticated API requests using stored credentials |
| **Data Structure** | JSON Parser / Generator | Converts raw JSON strings to dynamic objects and vice versa |
| **Data Structure** | CSV Parser / Generator | Parses bulk CSV text into structured records or formats tabular data |

## **Ecosystem & Tiering**

Make.com classifies integration connectors into structural availability levels:

* **Core Apps**: Standard modules available across all plan tiers (e.g., Slack, Google Workspace, Airtable).  
* **Premium Apps**: Apps requiring higher-tier subscription levels or custom API authorization allocations.  
* **Custom Apps**: Private integrations built via the Make App Builder using API endpoints and JSON specifications.

*Official Directory Link*: [Make.com Apps Directory](https://www.make.com/en/integrations)

---

# **Platform 2: n8n (Nodemation)**

## **Workflow Structure & Data Model**

n8n utilizes a Directed Acyclic Graph (DAG) model where workflows consist of **Nodes**. Each node receives an array of JSON items, processes them sequentially or via vectorized evaluation, and outputs an array of transformed items.

* **Trigger Nodes**: Start workflow execution via Webhooks, Schedules, or Application Events.  
* **Core Nodes**: Provide data transformation, conditional branching, and code execution.  
* **Integration Nodes**: API wrappers for third-party services.

## **Built-In System & Logic Nodes**

| Node Category | Node Name | Architectural Purpose |
| :---- | :---- | :---- |
| **Code Execution** | Code (JS / Python) | Executes custom JavaScript or Python scripts against input items |
| **Flow Control** | Switch | Routes items along distinct paths based on expression evaluations |
| **Flow Control** | If | Filters items based on true/false conditional checks |
| **Flow Control** | Loop Over Items | Iterates over items or arrays in controlled batches |
| **Data Management** | Edit Fields (Set) | Creates, updates, or strips properties from incoming data items |
| **Data Management** | Item Lists | Summarizes, splits, sorts, or de-duplicates items in the data stream |
| **Data Management** | Aggregate | Merges multiple items into a single item containing arrays |
| **Core Utilities** | HTTP Request | Fully configurable REST/GraphQL client supporting all auth modes |
| **Core Utilities** | Webhook | Exposes an HTTP endpoint to accept incoming payloads |
| **Sub-Workflows** | Execute Workflow | Calls child n8n workflows for modular pipeline architectures |

## **Ecosystem & Tiering**

n8n operates an open-ecosystem model with clear functional distribution:

* **Built-in / Core Nodes**: Included natively in all deployments (Open-source & Enterprise).  
* **Community Nodes**: Custom nodes created by the developer community, pullable via npm.  
* **Enterprise Nodes**: Advanced operational nodes reserved for licensed instances (e.g., advanced audit logs, external secret store management).

*Official Directory Link*: [n8n Integrations Directory](https://n8n.io/integrations/)

---

# **Platform 3: Microsoft Power Automate**

## **Flow Structure & Data Model**

Microsoft Power Automate structures execution via sequential **Flows** (Cloud Flows, Desktop Flows, or Business Process Flows). Flows are driven by an underlying Open API execution engine utilizing JSON dynamic content schema mapping.

* **Triggers**: Automated (Event-driven), Instant (Manual/Button), or Scheduled (Time-interval).  
* **Actions**: Sequential steps executed within the flow.  
* **Control Block**: Structural wrappers surrounding actions for looping, branching, and error handling.

## **Built-In Logic & Control Actions**

| Category | Action Name | Architectural Purpose |
| :---- | :---- | :---- |
| **Control** | Condition | Evaluates logical expressions to split path into If Yes / If No branches |
| **Control** | Apply to each | Loops execution across an array of dynamic content items |
| **Control** | Do until | Repeats a block of actions until a specified condition evaluates to true |
| **Control** | Switch | Multi-branching control block driven by a single input variable match |
| **Data Operations** | Compose | Constructs arbitrary JSON objects, strings, or complex expressions |
| **Data Operations** | Select | Transforms shape of JSON objects within an array via key-value mapping |
| **Data Operations** | Filter array | Filters array items based on specific logical criteria |
| **Data Operations** | Create HTML Table | Formats array data into clean HTML tables for reporting/notifications |
| **Variables** | Initialize / Set Variable | Defines global variables with static types (String, Integer, Array, etc.) |
| **HTTP** | HTTP / HTTP \+ Azure AD | Invokes external REST endpoints with optional Entra ID authentication |

## **Connector Tiers & Licensing**

Microsoft classifies its connectors into distinct operational tiers governing licensing requirements:

```
[Standard Connectors] ---> Included in basic M365 Licensing (e.g., SharePoint, OneDrive, Teams)
[Premium Connectors]  ---> Requires Power Automate Premium Per-User / Per-Flow Licenses (e.g., SQL Server, HTTP, Salesforce)
[Custom Connectors]   ---> Wrapper for private APIs built using OpenAPI / Swagger definitions
```

*Official Directory Link*: [Microsoft Power Automate Connectors Directory](https://learn.microsoft.com/en-us/connectors/connector-reference/)

---

# **Direct Architectural Comparison Matrix**

| Feature Dimension | Make.com | n8n | Microsoft Power Automate |
| :---- | :---- | :---- | :---- |
| **Data Flow Style** | Visual Graph / Canvas | Node Graph (DAG) | Sequential Vertical Flow |
| **Native Code Support** | Limited (Inline Formulas) | Native (Full JavaScript & Python) | Expressions / Power Fx (Limited) |
| **Error Handling** | Direct Directives (Ignore, Break, Resume, Rollback) | Error Trigger Node / Continue on Fail | Scope Blocks & "Configure Run After" |
| **Custom Integration Method** | Custom App Builder (JSON) | Node Building (TypeScript/npm) | Custom Connector (OpenAPI / Swagger) |
| **Enterprise Governance** | Teams, Roles, Organization Units | Environment Variables, Role-Based Access Control | Environments, DLP Policies, Solution Packages |

