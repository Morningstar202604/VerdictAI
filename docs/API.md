# API Reference

Base URL: `http://localhost:8787`

All request/response bodies are JSON unless noted. When `ACCESS_PASSWORD` is set
in `backend/.env`, every endpoint except `/login`, `/api/health` and
`/static/assets/*` requires the session cookie issued by `POST /login`.

## Health

### `GET /api/health`

```json
{ "status": "ok", "provider": "openai_compatible", "mock": false }
```

## Settings

### `GET /api/settings`

Returns the full runtime configuration (provider, model, rounds, judge mode,
HITL timeout, memory window, context limit, concurrency, call timeout,
web-search toggle, sandbox settings). Values persist to `backend/.env`.

### `POST /api/settings`

Update any subset of the configuration. Accepted keys include:
`llm_provider`, `llm_api_key`, `llm_base_url`, `llm_model`, `ollama_base_url`,
`ollama_model`, `temperature`, `max_rounds`, `human_in_the_loop`, `judge_mode`
(`ai`|`human`), `hitl_timeout`, `memory_rounds`, `context_char_limit`,
`max_concurrency`, `llm_timeout`, `web_search_enabled`, `intake_model`,
`code_sandbox_enabled`, `code_sandbox_python`.

Returns the updated configuration.

## Roles

### `GET /api/roles`

Returns the full roster: `key`, `name`, `color`, `stance`, `duty`, `group`,
`enabled`, `order`, `tools`, `model` per agent.

## Agent Config

### `GET /api/agent-config`

Per-agent runtime configuration: `enabled`, `order`, `system_prompt`,
`tools`, `model` (per-agent model override, `null` = main model).

### `POST /api/agent-config`

Persists the same shape. Used by Settings → 专家配置 and by config import.

## Cases

### `GET /api/cases`

Lists all cases (id, title, summary, `brief.intake_done` marker).

### `GET /api/cases/{id}`

Full case JSON: `summary`, `persons`, `evidence`, `timeline`, `statutes`,
`finance`, `dna_persons`, `contacts`, `charts`, `brief` (AI intake result with
`per_role_material`), optional `pdf_text`, `ai_extracted`.

### `POST /api/cases/generate`

Generates a sample case into the library. Returns `{ "path", "case" }`.

### `POST /api/cases/upload`

Upload a case. Two forms (both `application/json`):

1. **PDF**: `{ "file_type": "pdf", "file_content": "<base64>", "file_name":
"report.pdf", "title": "..." }` — text is extracted (PyMuPDF) and the AI intake
extracts persons / evidence / timeline / statutes / finance for unstructured
reports.
2. **Case JSON**: a case object (at minimum `summary`) — or a full structured
case. AI intake runs unless disabled.

Response: `{ "case": { ...case with brief, charts... } }`.

### `DELETE /api/cases/{id}`

Deletes a case file. Returns `{ "deleted": id }`.

## Debates

### `GET /api/debates`

Lists persisted trials (newest first): `session_id`, `case_title`,
`started_at`, `model`, `rounds`, `truth`, `usage` (`calls`, `in_chars`,
`out_chars`).

### `GET /api/debates/{session_id}`

Full transcript: every event, final verdict, usage.

## Knowledge Base

### `GET /api/knowledge?q=<keyword>`

Lists all entries (custom first, then built-in statutes & doctrine) or searches
by keyword.

### `POST /api/knowledge`

Add a custom entry: `{ "title", "text", "keywords": ["...", ...] }`.

### `DELETE /api/knowledge/{id}`

Deletes a custom entry (built-in statutes cannot be deleted).

## Presets (Strategy Templates)

### `GET /api/presets`

All templates: built-in (「刑事·严格证据攻防」, 「民事·责任划分」) + custom.

### `POST /api/presets`

`{ "name", "guidance", "agents": { "<role_key>": "<system_prompt>" } }` — saves
a custom template.

### `POST /api/presets/apply`

`{ "name" }` — writes the template's agent prompts into agent config
(persisted). Returns `{ "applied", "guidance", "agents" }`.

### `DELETE /api/presets/{name}`

Deletes a custom template.

## Verdict Q&A

### `POST /api/verdict-qa`

Ask a follow-up question about a delivered verdict.

**Request:** `{ "question", "verdict": { ...verdict object... }, "case_id" }`

**Response:** `{ "answer": "Markdown, cites evidence IDs" }`

## Sandbox

### `POST /api/sandbox/run`

`{ "code": "<python>" }` — executes in the isolated sandbox (60s timeout).
Chart files saved to `SANDBOX_OUT` are served under `/sandbox/`.

### `POST /api/sandbox/install`

`{ "package": "scipy" }` — installs a package into the sandbox environment.

## WebSocket

### `WS /ws/{session_id}`

Real-time debate event stream.

**Client → server:**

```json
{ "type": "start", "case_id": "case_001", "judge_mode": "ai",
  "intent": "...", "reasoning_intensity": "high",
  "global_guidance": "...", "agents": ["scene", "forensic", "..."] }
{ "type": "human", "text": "...", "subtype": "intervene" }
{ "type": "human", "text": "confirm", "subtype": "final" }
```

**Server → client (event kinds):**

| Kind | Description |
|---|---|
| `session_start` | Trial session initialized |
| `intake` | AI preprocessing result (intent, guidance, summary) |
| `round_start` | `{round, max_rounds}` |
| `agent_start` | `{id, role, name}` — expert begins |
| `token` | Streaming text chunk (`id` links to agent) |
| `tool` | Tool invocation `{tool, args, result}` |
| `agent_end` | Expert finished |
| `agent_note` | Clerk summary `{role, name, note:{claim, evidence_ids, doubts, implicates}}` |
| `round_end` | Round completed |
| `critic_start` / `critic_end` | Contradiction scan (`contradictions` list) |
| `judge_start` | Judge convergence begins |
| `verdict` | Full verdict `{truth_hypothesis, evidence_chain, doubts, recommendation, next_steps, disclaimer}` |
| `judge_end` | `{consensus}` |
| `awaiting_human` | HITL pause (human judge mode) |
| `human_reminder` | Nudge while waiting for the human verdict |
| `human_timeout` | HITL timeout — AI draft adopted automatically |
| `human_inject` | Mid-trial intervention echoed into the transcript |
| `usage` | `{calls, in_chars, out_chars}` for this trial |
| `done` | Trial complete |
| `error` | Failure (`message` field) |

Client disconnect cancels a running trial. On reconnect the client starts a
new session; past trials remain available via `/api/debates`.
