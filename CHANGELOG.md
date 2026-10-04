# Changelog

## 0.2.0

First public release under the name Routapse.

- Routers with lanes: cost tiers, specialist agents, guardrails (reply directly).
- Laya as a local Python package with signals (`choice`, `score`, `noul`) and routing rules. Jev over HTTP.
- OpenAI-compatible gateway with a classify-only endpoint.
- Providers: Ollama, OpenAI, Claude (Anthropic), Gemini, any OpenAI-compatible server.
- Ollama auto-discovery of locally installed models.
- Prompt studio with saved prompts, lane forcing and decision preview.
- Request and response log in daily JSONL files, with a log page in the GUI.
- Separate gateway, admin, router and GUI services; Docker Compose setup; configurable build mirrors.
- Laya is opt-in in Docker (`INSTALL_LAYA=1`).
