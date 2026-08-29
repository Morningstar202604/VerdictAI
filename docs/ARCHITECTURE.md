# Architecture

VerdictAI is a multi-agent judicial debate system built on **LangGraph** (state machine) + **FastAPI** (HTTP/WebSocket) + a zero-dependency single-page frontend.

## System Overview

```
                    ┌─────────────────────┐
                    │   Browser (SPA)      │
                    │   index.html          │
                    └──────────┬──────────┘
                               │ WebSocket
                    ┌──────────▼──────────┐
                    │   FastAPI Server     │
                    │   app/main.py        │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  LangGraph Graph     │
                    │  app/graph/builder.py│
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                 │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
    │  Experts Node  │  │ Critic Node │  │  Judge Node  │
    │  (7 parallel)  │  │ (per round) │  │ (verdict)    │
    └───────────────┘  └─────────────┘  └─────────────┘
```

## State Machine (LangGraph)

The debate is modeled as a `StateGraph` with the following flow:

1. **`experts_node`** — 7 agents run in parallel via `asyncio.gather`. Each receives:
   - The case dossier (evidence, timeline, persons, finance, etc.)
   - Previous rounds' arguments (via `round_summaries` for cross-round memory)
   - Tool access (evidence search, timeline check, statute lookup, etc.)

2. **`critic_node`** — Scans all 7 arguments for contradictions. Returns a structured JSON array of `{round, issue, parties}`. If contradictions are found, they are injected into the next round's context.

3. **`judge_node`** — Checks convergence criteria:
   - At least `min(2, max_rounds)` rounds completed
   - Either no contradictions remain, or max rounds reached
   - If not converged → loop back to step 1
   - If converged → produce final verdict (truth hypothesis, evidence chain, open questions, recommendations)

4. **`done`** — Returns the final `DebateState` with verdict and all events.

## Expert Roles

| # | Role | System Key | Focus |
|---|------|-----------|-------|
| 1 | Crime Scene Analyst | `crime_scene` | Physical evidence, spatial relationships, timeline |
| 2 | Forensic Specialist | `forensics` | Medical examiner findings, DNA, cause of death |
| 3 | Evidence Analyst | `evidence` | Chain of custody, forensic integrity, gaps |
| 4 | Criminal Psychologist | `psychology` | Behavioral patterns, motive, psychological profile |
| 5 | Evidence Law Expert | `evidence_law` | Legal admissibility, procedural compliance |
| 6 | Prosecutor | `prosecution` | Case for guilt, burden of proof |
| 7 | Defense Attorney | `defense` | Reasonable doubt, alternative theories |

## Tool System

Each expert has access to 5 tools:

| Tool | Description |
|------|-------------|
| `search_evidence` | Search case evidence by keyword |
| `check_timeline` | Verify event timing and sequence |
| `list_contradictions` | Get known contradictions from critic |
| `search_statutes` | Look up relevant legal statutes |
| `annotate_evidence` | Mark evidence with analysis notes |

Tools are invoked via the LLM's tool-calling mechanism. Failed tool calls are caught gracefully (never crash the debate).

## Cross-Round Memory

Arguments from previous rounds are summarized and stored in `round_summaries` (a list appended via LangGraph's `operator.add`). In each new round, experts receive:

- The full case dossier
- Summaries of all previous rounds' arguments
- Contradictions flagged by the critic

This allows experts to address counter-arguments and evolve their positions.

## Event Stream

Every debate action emits a typed event over WebSocket:

| Event Kind | Data | Description |
|---|---|---|
| `session_start` | `{session_id, model}` | Debate session begins |
| `intake` | `{case_id, title}` | Case loaded |
| `round_start` | `{round, max_rounds}` | New debate round begins |
| `agent_start` | `{id, role, round}` | Expert begins speaking |
| `token` | `{id, role, text, round}` | Streaming token from expert |
| `tool` | `{id, role, tool, args, result}` | Tool invocation result |
| `agent_end` | `{id, role, tokens, round}` | Expert finished |
| `agent_note` | `{role, text}` | Expert's summary note (for recording) |
| `round_end` | `{round}` | Round completed |
| `critic_start/end` | `{}` | Critic analysis phase |
| `judge_start/end` | `{}` | Judge convergence phase |
| `verdict` | `{truth_hypothesis, evidence_chain, ...}` | Final verdict |
| `done` | `{}` | Debate complete |
| `error` | `{message}` | Error occurred |

## Persistence

Each completed debate is saved to `data/debates/{session_id}.json` containing:
- All events (full timeline)
- Final verdict
- Configuration (model, rounds, etc.)

Past debates can be replayed via the "复盘记录" (Replay) tab in the UI.

## PDF Case Processing

1. User uploads PDF via drag-and-drop
2. PyMuPDF (`fitz`) extracts text (capped at 50 pages / 60,000 characters)
3. Text is structured into a case dossier with: title, summary, suspects, victims, evidence list, timeline, finance, DNA persons, contacts
4. Demo charts are auto-generated (7 PNG charts: timeline, evidence, motive, DNA, communication, bloodstain, scene)
5. Dossier is stored in `data/cases/` and becomes available for debate
