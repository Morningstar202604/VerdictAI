# API Reference

Base URL: `http://localhost:8787`

## Health

### `GET /api/health`

Returns server health status.

**Response:**
```json
{
  "status": "ok",
  "provider": "openai_compatible",
  "mock": false
}
```

## Configuration

### `GET /api/settings`

Returns current server configuration.

**Response:**
```json
{
  "llm_provider": "openai_compatible",
  "llm_model": "step-explore",
  "llm_base_url": "https://api.example.com/v1",
  "max_rounds": 3,
  "human_in_the_loop": false,
  "judge_mode": "ai"
}
```

## Roles

### `GET /api/roles`

Returns the list of expert roles.

**Response:**
```json
[
  {
    "key": "crime_scene",
    "name": "现场勘查专家",
    "name_en": "Crime Scene Analyst",
    "stance": "prosecution"
  },
  ...
]
```

## Cases

### `GET /api/cases`

Returns all stored cases.

**Response:**
```json
[
  {
    "id": "case_001",
    "title": "江城「3·15」别墅命案",
    "created_at": "2026-08-27T10:00:00"
  }
]
```

### `GET /api/cases/{id}`

Returns full case details including evidence, timeline, suspects, etc.

### `POST /api/cases`

Create a new case manually.

**Request Body:**
```json
{
  "id": "my_case",
  "title": "Case Title",
  "summary": "Brief description",
  "suspects": [...],
  "victims": [...],
  "evidence": [...],
  "timeline": [...]
}
```

### `DELETE /api/cases`

Delete a case by ID (passed as query parameter or body).

### `POST /api/upload`

Upload a PDF file for case preprocessing.

**Request:** `multipart/form-data` with `file` field.

**Response:**
```json
{
  "case_id": "case_abc123",
  "title": "Extracted Case Title",
  "status": "preprocessed"
}
```

## Debates

### `GET /api/debates`

Lists all persisted debate transcripts.

**Response:**
```json
[
  {
    "session_id": "abc-123",
    "case_id": "case_001",
    "model": "step-explore",
    "max_rounds": 3,
    "events_count": 85,
    "started_at": "2026-08-29T10:00:00",
    "done": true,
    "error": false
  }
]
```

### `GET /api/debates/{session_id}`

Returns full debate transcript with all events and verdict.

## WebSocket

### `WS /ws/{session_id}`

Real-time debate event stream.

**Connect with:**
```javascript
const ws = new WebSocket(`ws://localhost:8787/ws/${sessionId}`);
```

**Send to start:**
```json
{
  "type": "start",
  "case_id": "case_001",
  "judge_mode": "ai"
}
```

**Receive events:**
```json
{"kind": "session_start", "session_id": "...", "model": "..."}
{"kind": "intake", "case_id": "...", "title": "..."}
{"kind": "round_start", "round": 1, "max_rounds": 3}
{"kind": "agent_start", "id": "a1", "role": "crime_scene", "round": 1}
{"kind": "token", "id": "a1", "role": "crime_scene", "text": "...", "round": 1}
{"kind": "tool", "id": "a1", "role": "crime_scene", "tool": "search_evidence", "args": {...}, "result": "..."}
{"kind": "agent_end", "id": "a1", "role": "crime_scene", "tokens": 245, "round": 1}
{"kind": "agent_note", "role": "crime_scene", "text": "..."}
{"kind": "round_end", "round": 1}
{"kind": "critic_start"}
{"kind": "critic_end", "contradictions": [...]}
{"kind": "judge_start"}
{"kind": "verdict", "truth_hypothesis": "...", "evidence_chain": [...], "open_questions": [...]}
{"kind": "judge_end"}
{"kind": "done"}
```

**Event kinds reference:**

| Kind | Description |
|---|---|
| `session_start` | Debate session initialized |
| `intake` | Case loaded |
| `round_start` | New debate round |
| `agent_start` | Expert agent begins processing |
| `token` | Streaming text token from agent |
| `tool` | Tool invocation result |
| `agent_end` | Expert agent finished |
| `agent_note` | Expert's summary for recording |
| `round_end` | Round completed |
| `critic_start` | Contradiction analysis begins |
| `critic_end` | Contradiction analysis complete |
| `judge_start` | Judge convergence begins |
| `verdict` | Final verdict delivered |
| `judge_end` | Judge finished |
| `done` | Debate complete |
| `error` | Error occurred (see `message` field) |
