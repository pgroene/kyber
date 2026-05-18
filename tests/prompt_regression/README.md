# Prompt Regression Testing System

Track whether prompt pipeline changes improve or hurt response quality across Kyber versions and models.

## Quick start

### 1. Capture a test case
1. Ask Kyber a question in Home Assistant
2. Open the **Debug panel → Prompt** tab
3. Click **"📋 Capture test"** in the feedback bar
4. In the modal: review auto-filled assertions, add expected keywords, describe the ideal response
5. Click **Download** → extract the zip into `tests/prompt_regression/cases/`

### 2. Run the test suite
```bash
# Against the live HA AI task entity
python scripts/run_prompt_tests.py

# Against a local Ollama model (offline, no HA needed)
python scripts/run_prompt_tests.py --model local:ollama/mistral

# Compare models
python scripts/run_prompt_tests.py --model local:ollama/llama3
```

After running, open `tests/prompt_regression/report.html` in your browser.

### 3. Interpret results
- `run_history.json` in each case directory stores every run: `{version, model, score, latency_ms, passed, failed, assertion_details, response}`
- The HTML report shows: version × model score matrix, trend charts, latency comparison
- **Always run before AND after a prompt change** — commit both so score trends are visible in PRs

## Batch capture
Drop prompts (one per line) into `prompts.txt`, then in the debug panel "🧪 Tests" tab click **"📁 Batch capture"**. Kyber runs each prompt on the live instance and downloads all test cases at once.

## Regenerate after entity format changes
If the entity description format changes (narrator output, TF-IDF, etc.), old `tool_mocks.json` / `memory.json` snapshots may be stale. In the debug panel "🧪 Tests" tab, click **"🔄 Regenerate"** to re-run all test questions through live HA and refresh the snapshots — assertions are not changed.

## Test case directory structure
```
cases/tc_my_test_001/
├── test.json           # Question, assertions, label, ideal result description
├── memory.json         # Knowledge store snapshot for offline replay
├── tool_mocks.json     # Expected tool inputs + mock responses
└── run_history.json    # Per-run results (version, model, score, latency_ms, ...)
```

## When to run the test suite
Run whenever you change:
- Prompt templates or system instructions
- TF-IDF ranking or knowledge retrieval
- Entity narrator or deep analyzer
- Intent classification
- Tool call loop logic

Commit `run_history.json` files so score trends are visible across versions.
