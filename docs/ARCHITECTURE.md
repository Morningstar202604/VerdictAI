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

## Cross-Round Memory (tiered)

Round summaries live in `round_summaries` (LangGraph `operator.add`). Each round, experts receive:

- The full case dossier
- The last `MEMORY_ROUNDS` round summaries **in full**
- A rolling **`memory_digest`** — rounds beyond the window are compressed (~150 chars each, capped) instead of dropped, so long trials keep early clues
- Contradictions flagged by the critic

The local engine derives the round number deterministically from the number of summaries in the request, making parallel experts and repeated trials collision-free.

## Vertical Knowledge Base

`app/legal/knowledge.py` ships a built-in statute library (stable provisions of the Criminal Procedure Law, Criminal Law, Civil Code) plus evidence-review doctrine (three-factor test, chain of custody, electronic data) and precedent digests. `search_case_law` performs a **three-tier retrieval**: case-file statutes → user custom entries (`data/knowledge_base.json`, editable in Settings) → built-in library. Agents cite only retrieval hits — a miss is reported, never fabricated. Precedent references are scored by feature overlap with the case facts.

## Local Reasoning Engine

`backend/ai_engine/` is an OpenAI-compatible FastAPI service implementing the full expert/critic/judge/intake behavior deterministically over the parsed case file: role-specific structured analysis, cross-round references, tool calls (including matplotlib charts in the sandbox) and strict JSON for every node. It exists so the pipeline can run with zero network, zero cost — or be swapped for any cloud model with one settings change.

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

Post-verdict / HITL events: `awaiting_human`, `human_reminder`, `human_timeout` (auto-adopt AI draft), `human_inject`, `usage` (`{calls, in_chars, out_chars}`). Full reference: [API.md](API.md).

## Persistence

Each completed debate is saved to `data/debates/{session_id}.json` containing:
- All events (full timeline)
- Final verdict
- Configuration (model, rounds, etc.)

Past debates can be replayed via the "复盘记录" (Replay) tab in the UI.

## PDF Case Processing

1. User uploads PDF via drag-and-drop
2. PyMuPDF (`fitz`) extracts text (capped at 50 pages / 60,000 characters)
3. **AI intake structures the prose**: persons (role keywords), evidence items, timeline events (Chinese time expressions normalized to `HH:MM`), applicable statutes, insurance/finance traces — plain reports get the same structured treatment as hand-built cases
4. Charts are auto-generated (evidence reliability, timeline, contacts, finance) and the AI-extracted structure is badged in the case panel
5. Dossier (with `brief.per_role_material`) is stored in `data/cases/` and becomes available for debate
