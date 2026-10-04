# Scenarios

Each scenario is a router you build in the GUI (**Routers → New router**). Starters exist for the first four,
and [`examples/`](../examples) has importable configs. Edit the `CHANGE-ME` model aliases first; they must match models
added under **Connections**.

```bash
ADMIN_TOKEN=your-token ./examples/import.sh examples/support-triage.json [http://localhost:8002]
```

## 1. Cost tiers: small, normal, huge

**Goal:** stop paying for a large model on easy prompts.

1. Add three models under Connections, for example a small local Ollama model, a mid-size cloud model and a
   frontier model.
2. New router → *Right-size by difficulty*. Point `small`, `normal` and `huge` at them.
3. Set the fallback lane to `normal` and raise *min confidence*, so unsure cases don't get the cheapest model.

Config: [`examples/cost-tiers.json`](../examples/cost-tiers.json).

## 2. A team of specialist agents

**Goal:** one endpoint that behaves like a team.

Each lane has a **role** (its instructions) and a model: `coder`, `researcher`, `writer`, or anything you define,
such as a SQL expert or a legal reviewer. The router picks who handles each message. Different agents can use
different providers. Start from *Team of specialists* and edit the roles.

## 3. Guardrails and triage

**Goal:** answer, refuse or hand off before any LLM is paid for.

A lane set to **Reply directly** returns fixed text and never calls a model. Use it to refuse off-topic requests,
hand complaints to a human, or answer a canned FAQ. Because the router runs first, blocked prompts cost nothing.
Start from *Guardrails and triage*.

## 4. Support triage with Laya signals

**Goal:** classify a ticket and score it in one pass.

Laya answers the routing question plus extra **signals** in the same call:

| Signal | Type | Question |
|---|---|---|
| `urgency` | score | How urgent is this? (not urgent, soon, blocking) |
| `churn_risk` | noul | Does the user threaten to cancel or leave? |

A **rule**, "if `churn_risk` is at least 0.7, send to `human`", overrides the normal lane. The decision returns every
signal, so a help desk can also use them for priority and tagging.

Config: [`examples/support-triage.json`](../examples/support-triage.json). Requires Laya.

## 5. Local first, cloud when needed

**Goal:** keep confidential text on your machine.

A `sensitive` yes/no signal with the rule "if `sensitive` is at least 0.5, send to `private`" routes confidential
prompts to a local Ollama model. Routine prompts also stay local, and only hard, non-sensitive ones go to a cloud
model. The log shows where each prompt went.

Config: [`examples/local-first.json`](../examples/local-first.json). Requires Laya.

## 6. Router as a classifier only

**Goal:** use Laya or Jev as a middle model in your own pipeline.

`POST /v1/route/{router_id}` returns the lane and signals without calling any LLM. Use it to tag tickets, pick a queue
or prompt template, or decide whether to run retrieval.

```bash
curl -s localhost:8000/v1/route/support-triage \
  -H 'Content-Type: application/json' \
  -d '[{"role":"user","content":"Our dashboard has been down for an hour"}]'
```

## 7. Model migration and comparison

Declare the old and new model as two lanes of one router, force a lane in the **Prompt studio**, and compare
answers. The log shows latency and token usage per model.

## 8. Fallback and quality ladder

Use *min confidence* and the fallback lane so uncertain prompts always land on a safe, capable model rather than the
cheapest one.
