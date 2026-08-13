# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

## Project Overview

A minimal AI agent framework ("simple nanobot") with tool-calling support. All code, comments, error messages, and UI output are in Chinese.

## Running

```
uv run python src/main.py
```

Source lives in `src/` with flat imports (e.g. `from bus import MessageBus`), not package-style. There is no `[project.scripts]` entry point configured.

## Setup

Requires `.env` at project root with `OPENAI_API_KEY` (required). Optional: `OPENAI_MODEL`, `OPENAI_BASE_URL`. Install deps with `uv sync`.

## Architecture

- `main.py` — CLI entry point, wires everything together
- `bus.py` — async MessageBus (inbound/outbound queues)
- `events.py` — InboundMessage / OutboundMessage dataclasses
- `loop.py` — AgentLoop state machine: RESTORE → BUILD → RUN → RESPOND
- `runner.py` — AgentRunner: multi-turn tool-call loop with LLM
- `provider.py` — LLMProvider ABC + MockProvider + OpenAIProvider
- `tools.py` — Tool ABC + ToolRegistry; built-in tools: shell, read_file, create_file, list_dir
- `context.py` — ContextBuilder: assembles system prompt + history + user message

## Key Conventions

- No test framework is set up.
- Tools extend `Tool` ABC with `get_definition()` (JSON Schema) and `async execute(args)`.
- ShellTool uses `subprocess.run(shell=True)` with 30s timeout — runs cmd.exe on Windows.
