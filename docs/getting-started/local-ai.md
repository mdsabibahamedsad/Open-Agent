# Local AI (Ollama) and Cloud Providers

OpenAgent supports three model configurations through the backend Model Router (`openai`, `anthropic`, `google`, `ollama`, `openai-compatible` adapters in `apps/api/src/openagent/runtime/model_adapters.py`).

## Local AI with Ollama (optional)

Ollama is **not** installed by the setup — it is an optional local model server.

```bash
ollama serve
ollama pull llama3
```

The built-in `OllamaAdapter` talks to `http://localhost:11434` by default and needs no API key. Supported models include `llama3`, `mistral`, `mixtral`, `codellama`, `phi3`, `gemma`, `qwen2` (see `model_adapters.py` for the current list).

```text
Ollama
  ↓
OpenAgent Model Router
  ↓
AI Agent Runtime
```

## Cloud AI (optional)

Set the relevant key in `.env` (placeholders live in `.env.example` — never commit real keys):

```text
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

## Hybrid

Mix providers per task: the router selects across all configured providers. Leave everything unset to run the platform UI, workflows, and integrations without any model calls.
