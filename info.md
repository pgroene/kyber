# Kyber — AI-Powered Smart Home Assistant

Kyber brings a local AI chat assistant directly into your Home Assistant sidebar. Powered by your own **Ollama** instance — 100% local, nothing leaves your network.

## What can Kyber do?

- 💬 **Chat with your smart home** — ask questions, give commands, control entities in natural language
- 📋 **Proposal cards** — the AI proposes changes; you review and approve before anything executes
- ✏️ **Edit automations & dashboards** — CodeMirror YAML editor with AI assistance
- 🧠 **Persistent memory** — Kyber learns facts about your home and uses them in future conversations
- 🔒 **100% local** — all AI inference runs on your own Ollama instance
- 🤖 **Entity Narrator** — on startup, Kyber generates natural-language descriptions and search aliases for all your entities
- ⚡ **Autopilot mode** — auto-execute approved proposals for hands-free operation
- 🐞 **Debug panel** — full transparency into AI reasoning, knowledge used, tool calls, and system prompt

## Requirements

- Home Assistant 2025.1.0 or newer
- A running [Ollama](https://ollama.ai) instance accessible from HA
- A capable model (recommended: `qwen2.5:14b` or `llama3.1:8b`)

## Getting started

After installing via HACS and restarting Home Assistant:

1. Go to **Settings → Devices & Services → Add Integration** → search for **Kyber**
2. Enter your Ollama URL and select a model
3. Open the **Kyber** sidebar panel and start chatting
