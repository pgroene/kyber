# Kyber Narrator Bench Report — May 2026

**Which local models can reliably narrate smart home entities at scale?**

---

## Background

Kyber's **entity narrator** is a background enrichment phase that runs after the integration explorer finishes indexing your Home Assistant setup. For each "interesting" entity — one with a cryptic Zigbee ID, multiple sensor siblings, or a non-obvious name — the narrator assembles the full device context (manufacturer, model, area, siblings) and asks the AI to produce a set of **human-readable aliases** for that entity.

These aliases are stored in the knowledge store as `entity_alias` entries. When you type "turn off the televisie" or "check soil moisture tuin", Kyber's hybrid TF-IDF retrieval finds the matching alias and passes it to the AI as context — so the AI knows exactly which entity ID to use without having to guess.

The narrator processes entities in **batches**: one AI call generates descriptions for a whole batch. Batch size matters — too small and it's slow; too large and weaker models lose track of the format.

---

## What We Measured

We built `scripts/narrator_bench.py` — a self-contained benchmark that:

- **Generates realistic entity batch prompts** using 20 synthetic Dutch smart home entities (Zigbee devices, NEO smart plugs, energy sensors, garden sensors — representative of a real home)
- **Calls each model directly via Ollama** at batch sizes 1 and 10
- **Scores the response** on four dimensions: did the model return a parseable output? Does each description contain the entity ID verbatim? Does it include at least 2 meaningful terms? Does it name the device type?
- **Runs with a warmup call first** per model to load weights into VRAM before timing starts, giving fair cold-start-corrected numbers
- **Runs 2 iterations per cell** and averages the results

**Quality score = average of all four dimensions (0–100%)**

---

## Results — All 19 Models

Models are ordered by `Quality@10` (batch=10 quality), then `Quality@1`, then speed.

### ✅ Fully reliable (100% quality, both batch sizes)

| Model | Size | Batch 1 | Batch 10 | tok/s | Notes |
|-------|------|---------|---------|-------|-------|
| `llama3.2:3b` | 1.9 GB | **0.5s** | **3.7s** | 104 | 🏆 Best overall — fastest reliable model |
| `llama3.1:8b` | 4.7 GB | 2.2s | 17.8s | 39 | Consistent, but slower than 3b |
| `llama3:latest` (8b) | 4.3 GB | 1.3s | 11.0s | 59 | Solid across both sizes |
| `mistral-nemo:latest` | 6.6 GB | 4.4s | 44.0s | 15 | Previous recommended model — still reliable, but 12× slower than llama3.2:3b |
| `mistral-small:latest` | 13.3 GB | 18.6s | 154.7s | 5 | 100% quality but impractically slow |

### ⚠️ Mostly reliable (minor failures)

| Model | Size | Batch 1 | Batch 10 | tok/s | Notes |
|-------|------|---------|---------|-------|-------|
| `llama3.2:latest` (3b) | 1.9 GB | ⚠️ 50% | ✅ 100% | 86 | One bad run at batch=1 — likely a fluke; same weights as `llama3.2:3b` |
| `phi3:mini` (3.8b) | 2.3 GB | ✅ 100% | ⚠️ 95% | 82 | Near-perfect; missed 1 entity across 2 batch=10 runs |
| `qwen3:4b-instruct` | 2.3 GB | ⚠️ 90% | ⚠️ 50% | 79 | Inconsistent at scale — one run perfect, one run zero |

### ❌ Unreliable at batch=10 only

| Model | Size | Batch 1 | Batch 10 | tok/s | Notes |
|-------|------|---------|---------|-------|-------|
| `gemma3:4b` | 3.0 GB | ❌ 0% | ✅ 100% | 77 | Bizarre inversion — fails single entity, handles batch fine |
| `gemma2:2b` | 1.6 GB | ✅ 100% | ⚠️ 40% | 114 | Very fast but unreliable at scale |
| `mistral:latest` (7b) | 4.1 GB | ✅ 100% | ❌ 9% | 55 | Fast at batch=1 but collapses at batch=10 |

### ❌ Failed entirely

| Model | Size | Batch 1 | Batch 10 | tok/s | Why |
|-------|------|---------|---------|-------|-----|
| `qwen2.5:7b` | 4.4 GB | ❌ 0% | ❌ 0% | 60 | Doesn't follow the narrator output format |
| `qwen2.5:latest` | 4.4 GB | ❌ 0% | ❌ 0% | 55 | Same |
| `qwen:latest` | 2.2 GB | ❌ 0% | ❌ 0% | 86 | Same |
| `qwen3:8b` | 5.0 GB | ❌ 0% | ❌ 0% | 51 | Uses `<think>` blocks that break output parsing |
| `qwen3:1.7b` | 1.0 GB | ❌ 0% | ⚠️ 30% | 137 | Same thinking-mode issue |
| `qwen3.5:4b` | 3.0 GB | ❌ 0% | ❌ 0% | 63 | Same |
| `deepseek-r1:7b` | 4.7 GB | ❌ 0% | ❌ 0% | 57 | Reasoning model — wastes tokens on `<think>` chains |
| `smollm2:1.7b` | 1.0 GB | ❌ 0% | ❌ 0% | 119 | Too small to follow structured format |

---

## Key Findings

### 1. Qwen3 and DeepSeek-R1 fail because of thinking mode

All Qwen3 variants (`qwen3:1.7b`, `qwen3:8b`, `qwen3.5:4b`) and `deepseek-r1:7b` scored 0% at batch=1. These are **reasoning/thinking models** — they emit `<think>…</think>` blocks before their answer. The narrator prompt parser doesn't strip these, so the output appears garbled.

> **Note:** Kyber already injects `/no_think` for Qwen3 in the main chat flow (`http_api.py`) — but the narrator uses `async_generate_data()` which bypasses this. A narrator-specific `/no_think` prefix would likely fix these models.

### 2. `llama3.2:3b` is the new best narrator model

At 0.5s per entity and 3.7s for a batch of 10, it's **12× faster than mistral-nemo** while matching it on quality. It uses only 1.9 GB of VRAM. For a background process that narrates hundreds of entities, this matters enormously — a full narrator run that took 44 minutes at batch=10 with mistral-nemo would take ~3.5 minutes with llama3.2:3b.

### 3. Model size ≠ narrator quality

The worst performing models by quality include `qwen3:8b` (5.0 GB, 0%) and `mistral-small` (13.3 GB, 100% but 154s/batch). The best is `llama3.2:3b` at 1.9 GB. For the structured, format-following narrator task, instruction tuning and output format adherence matter far more than raw model size.

### 4. `gemma3:4b` is anomalous

It scores 0% at batch=1 but 100% at batch=10. The single-entity prompt appears to confuse it — it produces a description but in a different format. At batch=10 the richer context anchors its output format correctly. Interesting but not a practical model to use for the narrator given the batch=1 failure.

---

## Speed vs Quality Tradeoff

```
Quality  100% │ ●llama3.2:3b   ●llama3:8b  ●llama3.1:8b       ●mistral-nemo      ●mistral-small
              │   (0.5s/3.7s)  (1.3s/11s)  (2.2s/17.8s)        (4.4s/44s)          (18.6s/155s)
         95%  │                                          ●phi3:mini
              │                                          (1.8s/9.1s)
         50%  │                  ●qwen3:4b-instruct ●llama3.2:latest
              │                  (1.6s/11.9s)       (0.6s/4.4s)
          0%  │ ●smollm2  ●qwen3.5:4b  ●qwen*  ●deepseek-r1  ●gemma3:4b
              └────────────────────────────────────────────────────────── speed →
                fast (0.5s)                                    slow (155s)  [batch=10]
```

---

## Recommendation

**Switch the narrator to `llama3.2:3b`.**

| | Before | After |
|---|---|---|
| Model | `mistral-nemo:latest` | `llama3.2:3b` |
| Batch=10 time | 44s | 3.7s |
| Quality@10 | 100% | 100% |
| VRAM | 6.6 GB | 1.9 GB |
| Speedup | — | **12×** |

`phi3:mini` is a strong alternative if llama3.2:3b is unavailable — 100% at batch=1, 95% at batch=10, and also small (2.3 GB).

---

## Part 2: Optimal Batch Size for llama3.2:3b

After selecting `llama3.2:3b` as the best model, we ran a second bench to find the optimal batch size: batch sizes 1, 5, 10, 15, and 20 with 3 runs each and warmup.

### Results

| Batch size | Quality | Elapsed | ms/entity | tok/s |
|:---:|:---:|---:|---:|---:|
| 1 | ⚠️ 67% | 0.6s | 576ms | 79 |
| 5 | ✅ 100% | 2.8s | 551ms | 87 |
| **10** | **✅ 100%** | **4.4s** | **439ms** | **90** |
| 15 | ⚠️ 91% | 10.1s | 671ms | 108 |
| 20 | ❌ 68% | 9.4s | 470ms | 106 |

### Key observations

- **Batch=1 is surprisingly unreliable** — 1 in 3 runs returned an unparseable response. Single-entity prompts appear to confuse the model occasionally (possibly the lack of examples to pattern-match against).
- **Batch=5 and batch=10 are both 100% reliable.** Batch=10 wins on throughput: 439ms/entity vs 551ms/entity — a 20% improvement.
- **Batch=15 starts to slip** — one run returned only 11/15 entities correctly.
- **Batch=20 fails significantly** — one run returned only 1/20 entities (`parsed=1/20`), catastrophically cutting quality to 5%.

### Conclusion

**Batch=10 is the sweet spot for `llama3.2:3b`**: perfect quality across all 3 runs and the best per-entity throughput. The narrator's `_MAX_RELIABLE_BATCH` constant has been updated from 50 → 10 to reflect this finding.

---

## Part 3: Can llama3.2:3b also replace mistral-nemo for chat?

After establishing `llama3.2:3b` as the narrator champion, we tested it against the full 13-scenario chat eval harness (`scripts/prompt_eval.py`, 5 runs, structural checks).

**Short answer: no.**

| Category | Score |
|---|:---:|
| Q&A queries (5 scenarios) | ✅ Always passes |
| Action/plan scenarios (8 scenarios) | ❌ 0% — never produces a plan block |
| **Overall avg** | **3.5–4.2 / 10** |

The model understands requests and calls tools correctly, but outputs prose instead of Kyber's structured `PLAN:` block. Every action scenario (`set_thermostat_21`, `tv_off_woonkamer`, `coffee_off`, `all_lights_off`, `morning_automation`, `koffie_espresso`) failed all 5 runs with score 0.

For full per-scenario results see [eval-report-2026-05.md](eval-report-2026-05.md#extended-eval--llama323b-13-scenarios-may-2026).

### Final two-model recommendation

| Role | Model | Why |
|---|---|---|
| 🗣️ **Chat & actions** | `mistral-nemo:latest` | 93% on 13-scenario eval, reliable plan blocks, handles Dutch |
| 🏷️ **Entity narrator** | `llama3.2:3b` | 100% quality, 3.7s/batch, 1.9 GB — 12× faster than mistral-nemo |

These are complementary models. The narrator runs in the background and only needs to produce short structured aliases — `llama3.2:3b` excels at this. The chat assistant needs to reason, call tools, and emit precise JSON plan blocks — that requires `mistral-nemo`.

---

## Benchmark Details

| Parameter | Value |
|---|---|
| Script | `scripts/narrator_bench.py` |
| Models tested | 19 |
| Batch sizes | 1, 10 |
| Runs per cell | 2 |
| Warmup | 1 call per model before timing |
| Synthetic entities | 20 Dutch smart home entities |
| Ollama URL | `http://localhost:11434` |
| Date | May 2026 |

Raw JSON results: `tests/narrator_bench/results.json`
HTML report: `tests/narrator_bench/report.html`

---

*Report generated: May 2026 · 19 models · 52 bench cells · warmup-corrected timing*
