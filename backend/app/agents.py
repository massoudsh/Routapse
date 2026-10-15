"""OpenAI Agents SDK orchestration backed by Routapse model aliases."""
import re
import uuid

from agents import (
    Agent, AsyncOpenAI, GuardrailFunctionOutput, InputGuardrail, OpenAIChatCompletionsModel,
    OutputGuardrail, RunConfig, Runner, SQLiteSession, function_tool,
)
from fastapi import HTTPException

from . import engine
from .config import settings
from .schemas import AgentDef
from .store import store

_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def _terms_guardrail(terms: list[str], direction: str):
    lowered = [term.lower() for term in terms if term.strip()]

    async def check(_, __, value):
        text = str(value).lower()
        found = next((term for term in lowered if term in text), None)
        return GuardrailFunctionOutput(
            output_info={"direction": direction, "matched": found}, tripwire_triggered=bool(found))

    return check


def _tools(names: list[str]):
    selected = []
    if "list_models" in names:
        @function_tool(name_override="list_models", description_override="List model aliases available in Routapse.")
        async def list_models() -> list[dict]:
            return [{"id": m["id"], "description": m.get("description", "")} for m in store.list("models")]
        selected.append(list_models)
    if "route_prompt" in names:
        @function_tool(name_override="route_prompt", description_override="Classify a prompt through a saved Routapse router without calling a model.")
        async def route_prompt(router_id: str, prompt: str) -> dict:
            info, _ = await engine.run("agent-tool", [{"role": "user", "content": prompt}], {},
                                       router=engine.load_router(router_id), call_model=False)
            return info
        selected.append(route_prompt)
    return selected


def _model(model_id: str):
    if not settings.agent_gateway_url:
        raise HTTPException(503, "AGENT_GATEWAY_URL is not configured")
    if not store.get("models", model_id):
        raise HTTPException(400, f"model '{model_id}' does not exist")
    client = AsyncOpenAI(api_key=settings.gateway_key or "routapse-agent", base_url=settings.agent_gateway_url,
                         max_retries=0)
    return OpenAIChatCompletionsModel(model=model_id, openai_client=client)


def _agent(definitions: dict[str, AgentDef], id_: str, stack: tuple[str, ...] = ()) -> Agent:
    if id_ in stack:
        raise HTTPException(400, f"agent handoff cycle: {' -> '.join((*stack, id_))}")
    definition = definitions.get(id_)
    if not definition:
        raise HTTPException(400, f"agent '{id_}' does not exist")
    input_guardrails = ([InputGuardrail(_terms_guardrail(definition.input_blocked_terms, "input"))]
                        if definition.input_blocked_terms else [])
    output_guardrails = ([OutputGuardrail(_terms_guardrail(definition.output_blocked_terms, "output"))]
                         if definition.output_blocked_terms else [])
    return Agent(
        name=definition.name,
        instructions=definition.instructions or "Be helpful.",
        model=_model(definition.model_id),
        tools=_tools(definition.tools),
        handoffs=[_agent(definitions, target, (*stack, id_)) for target in definition.handoffs],
        input_guardrails=input_guardrails,
        output_guardrails=output_guardrails,
    )


def _definitions() -> dict[str, AgentDef]:
    return {item["id"]: AgentDef.model_validate(item) for item in store.list("agents")}


async def run(id_: str, input_: str, session_id: str | None = None) -> dict:
    """Run a configured agent through the internal Routapse gateway."""
    if session_id and not _SESSION_ID.fullmatch(session_id):
        raise HTTPException(400, "session_id may contain only letters, digits, dot, underscore, colon and hyphen")
    definitions = _definitions()
    definition = definitions.get(id_)
    if not definition:
        raise HTTPException(404, f"agent '{id_}' does not exist")
    trace_id = uuid.uuid4().hex
    result = await Runner.run(
        _agent(definitions, id_), input_, max_turns=definition.max_turns,
        session=SQLiteSession(session_id, settings.agent_session_db) if session_id else None,
        run_config=RunConfig(tracing_disabled=not settings.agent_tracing, workflow_name=f"Routapse agent: {id_}",
                             trace_id=trace_id, trace_metadata={"agent_id": id_}),
    )
    return {"output": str(result.final_output), "agent": result.last_agent.name, "trace_id": trace_id,
            "session_id": session_id}
