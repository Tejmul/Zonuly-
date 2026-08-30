# GEMINI — Targeted Multi-Agent Orchestration & Guardrails Specification

> **Status:** ARCHITECTURAL BLUEPRINT
> **Focus:** Aligned Agent Pipelines, Security Guardrails, and Clickable Reference Provenance.

This document specifies the core technical architecture for **ZoNuLy (JobHunter)**. It defines a highly structured, sequential multi-agent pipeline, enforces strict, agent-specific safety guardrails, and maps out a verifiable, clickable provenance system for all scraped leads and contacts.

---

## 1. Sequential Multi-Agent Orchestration

Instead of a complex, non-deterministic hierarchy, the system operates as a **Sequential Pipeline** where specialized, single-purpose agents pass typed, validated handoffs down the funnel.

```
 [ Scout Agent ] ──(RawJob)──► [ Scorer Agent ] ──(ScoredJob)──► [ Contact Miner ] ──(Contact)──► [ Drafter Agent ]
```

### The Agent Funnel Contracts

1.  **Scout Agent:**
    *   **Goal:** Crawls and fetches raw job postings from targeted ATS APIs (Greenhouse, Lever, Ashby) and developer boards (HN, YC).
    *   **Output:** Returns a validated list of `RawJob` schemas.
2.  **Scorer Agent:**
    *   **Goal:** Evaluates the `RawJob` text against the candidate's resume using a multi-dimensional rubric (skills, experience, domain alignment).
    *   **Output:** Generates a structured `ScoredJob` including a `match_score` (0-100) and explicit, logical reasoning.
3.  **Contact Miner Agent:**
    *   **Goal:** For companies with a `match_score` exceeding the shortlist threshold, mines public git repositories and websites for developer/recruiter contacts.
    *   **Output:** Generates a list of `Contact` schemas, each carrying a mandatory, verifiable proof source.
4.  **Drafter Agent:**
    *   **Goal:** Synthesizes the candidate's profile, the job requirements, and the mined contact's public work into a personalized referral email draft.
    *   **Output:** Generates the finished outreach draft bound to explicit evidence reference citations.

---

## 2. Agent-Specific Guardrails

To prevent non-deterministic behavior, runaway costs, and API failures, we enforce two critical, hard-coded **Agent Guardrails** at the runtime engine layer.

```
                  ┌──────────────────────────────────────────┐
                  │            AGENT ENGINE RUNTIME          │
                  └─────┬──────────────────────────────┬─────┘
                        │                              │
                        ▼                              ▼
          [ Tool Loop Guardrail ]            [ Structured Validation ]
          - Max 5 tool calls / turn          - Pydantic schema validation
          - Raise exception on loop          - Max 2 retries on failure
```

### Guardrail A: Infinite Tool Loop Limit
*   **The Hazard:** When an agent is granted tool access, it can enter a recursive loop (e.g., repeatedly calling a failing Google search or files search in a loop), consuming thousands of tokens in minutes.
*   **The Enforcement:** 
    *   The execution runner wrapping the agent’s loop maintains an atomic counter of tool executions: `tool_call_count`.
    *   A strict limit of **`max_tool_calls = 5`** is enforced per agent turn.
    *   If the agent attempts to execute a 6th tool call, the runner immediately halts execution, revokes tool access, raises a `ToolLoopLimitExceeded` exception, and flags the run in the database for human inspection.

```python
# Conceptual Agent Runner Loop
def execute_agent_turn(agent, prompt, max_tool_calls=5):
    tool_call_count = 0
    state = init_state(prompt)
    
    while not state.is_finished():
        action = agent.predict_next_action(state)
        if action.is_tool_call():
            tool_call_count += 1
            if tool_call_count > max_tool_calls:
                raise ToolLoopLimitExceeded(
                    f"Agent {agent.name} exceeded the tool loop limit of {max_tool_calls}."
                )
            result = execute_tool(action.tool_name, action.args)
            state.update_with_tool_result(result)
        else:
            state.update_with_message(action.message)
    return state.output
```

### Guardrail B: Structured Output Validation & Self-Correction
*   **The Hazard:** LLMs frequently output malformed JSON, miss required fields, or include conversational text surrounding the requested schema structure.
*   **The Enforcement:**
    *   All agent outputs must strictly conform to a defined **Pydantic model** (e.g., `ScoredJobSchema`, `DraftSchema`).
    *   When the LLM returns an output, the runner attempts to parse and validate it against the target Pydantic model.
    *   **Auto-Correction / Retry Loop:** If validation fails, the runner intercepts the error and triggers a maximum of **2 self-correction retries**. It feeds the specific validation error messages back to the model, instructing it to correct the schema. If it fails on the 3rd attempt, the task is marked as failed, preventing malformed data from entering the database.

---

## 3. Reference Mapping (The Provenance Panel)

To establish complete transparency, the frontend features a dedicated **Provenance Panel** on the right side of the Job Details page. Every single scraped company and contact lead must display a clear, clickable verification trail showing exactly *why* and *how* the lead was generated.

```
 ┌────────────────────────────────────────────────────────┐
 │  PROVENANCE PANEL (VERIFICATION REFERENCE)             │
 ├────────────────────────────────────────────────────────┤
 │                                                        │
 │  Sourcing Trigger (Why we scraped this company)         │
 │  - Source: Hacker News Hiring Thread (Aug 2026)        │
 │  - Comment Link: Clickable URL (Comment #24098)       │
 │                                                        │
 │  Lead Sourcing Proof (How we found Suresh's email)     │
 │  - Source Repository: mstack-core                      │
 │  - Git Commit: Clickable Commit SHA (e5a9c1f...)      │
 │  - Metadata Proof: Suresh <suresh@mstack.com>          │
 │                                                        │
 └────────────────────────────────────────────────────────┘
```

### A. Company Sourcing References
The Provenance Panel renders an auditable record of the company's source trigger:
*   **Hacker News leads:** Renders the name of the month's thread, a clickable link to the exact HN comment, and the comment author's username.
*   **ATS Feeds (Greenhouse/Lever/Ashby):** Renders the exact public board API endpoint query and the fetched timestamp.
*   **YC Directory:** Renders the company's YC profile URL and their active batch (e.g., `W26`).

### B. Contact Sourcing References
Every contact shown in the list must feature a clickable proof block in the Provenance Panel:
*   **Git Commits:** Renders a clickable link directly to the commit on GitHub, the specific **Git Commit SHA**, and the raw author metadata line (e.g., `Author: Suresh <suresh@mstack.com>`) mined from the public git history.
*   **Site Scraping:** Renders the exact company team/careers URL and the specific text snippet surrounding the found contact details.

---

*This targeted specification defines the complete, aligned multi-agent orchestration, guardrail system, and verification mapping guidelines for ZoNuLy.*
