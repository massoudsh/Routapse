# API reference

## Gateway (`:8000`)

Authentication: `Authorization: Bearer $GATEWAY_API_KEY` when `GATEWAY_API_KEY` is set.

### `POST /v1/chat/completions`

OpenAI-compatible. `model` is either:

- `router:<router_id>`: the router picks a lane, then the lane's model answers (or the lane replies directly).
- a model alias declared under Connections: direct pass-through, no routing.

Supported fields: `messages`, `stream`, `temperature`, `max_tokens`, `top_p`.

The response is a standard chat completion plus:

- headers `X-Routapse-Route` and `X-Routapse-Model`
- a `routapse` field with the decision:

```json
{
  "label": "billing",
  "confidence": 1.0,
  "reason": "laya",
  "latency_ms": 120,
  "action": "forward",
  "model_id": "gpt-4o",
  "signals": {"urgency": 2, "churn_risk": 0.12},
  "laya_model": "english"
}
```

`stream: true` returns valid SSE, but the whole answer arrives as one chunk.

### `POST /v1/route/{router_id}`

Returns the same decision object without calling any LLM. Body: a list of `{"role", "content"}` messages.

### `GET /v1/models`

Lists `router:<id>` entries and model aliases.

## Admin (`:8002`)

Authentication: `Authorization: Bearer $ADMIN_TOKEN` when `ADMIN_TOKEN` is set.

| Method and path | Purpose |
|---|---|
| `GET/PUT/DELETE /admin/providers[/{id}]` | Providers (`ollama`, `openai`, `openai_compat`, `anthropic`, `gemini`). Stored API keys are returned masked as `***`. |
| `GET/PUT/DELETE /admin/models[/{id}]` | Model aliases: provider, model name at the provider. |
| `GET/PUT/DELETE /admin/routers[/{id}]` | Routers: lanes, signals, rules, fallback, minimum confidence. |
| `GET/PUT/DELETE /admin/prompts[/{id}]` | Saved prompts for the prompt studio. |
| `POST /admin/test` | Route (and optionally run) a prompt against a saved or draft router. |
| `POST /admin/chat` | Prompt studio: send messages through a router or model, optionally forcing a lane. |
| `GET /admin/logs` | Request log. Query: `limit`, `offset`, `router_id`, `source`, `q`. |
| `GET /admin/logs/info` | Log directory, files and whether bodies are logged. |
| `GET /admin/ollama/models` | Models installed on an Ollama server. Query: `base_url` (optional). |

## Router object

```json
{
  "id": "support-triage",
  "name": "Support triage",
  "mode": "custom",
  "router_model": "laya",
  "routes": [
    {"label": "billing", "description": "invoices, payments, refunds", "examples": [],
     "action": "forward", "model_id": "gpt-4o", "system_prompt": "", "response_text": "", "color": "#2E9E6B"}
  ],
  "fallback_label": "billing",
  "min_confidence": 0.0,
  "signals": [{"name": "churn_risk", "type": "noul", "instructions": "Does the user threaten to cancel?"}],
  "rules": [{"signal": "churn_risk", "op": "gte", "value": "0.7", "route_label": "human"}]
}
```

- `action`: `forward` (call `model_id`) or `respond` (return `response_text`).
- `signals` and `rules` apply to `router_model: "laya"` only.
- Rule `op`: `is` (text match), `gte`, `lte` (numeric).

## Request log format

One JSON object per line in `<LOG_DIR>/requests-YYYY-MM-DD.jsonl`:

`id`, `ts`, `source` (`gateway`, `gateway-route`, `studio`, `test`), `router_id`, `requested_model`,
`request` (messages, params), `decision`, `target_model`, `response` (text, usage), `status`, `error`,
`latency_ms`, `client`.
