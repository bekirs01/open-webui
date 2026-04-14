# MWS Auto routing

`auto` and `mws:auto` are routing modes (not upstream model IDs). Resolution happens in `decide_mws_model` → `resolve_mws_chat_model`.

## Pipeline

1. **Modality** — `classify_task_modality` (attachments, memory/context, export, code, vision, image generation, default text).
2. **Complexity** (text/code only, when orchestration is on) — `estimate_complexity` (`simple` / `medium` / `hard`).
3. **Model pick** — tiered lists in `orchestrator.py` (`AUTO_TEXT_*_ORDER`) and `team_registry.py` (`AUTO_*_ORDER` for vision/code/image).
4. **Fallback** — `MODEL_CAPABILITY.fallback_candidates` then text list (`_pick_fallback`).
5. **Explainability** — `RoutingDecision` in `router.py` plus `classify_detailed_task` in `routing_tasks.py` (`detailed_task`, `requires_tools`).

Structured logs: `[MWS-Routing-JSON]` with `routing_decision` dict.

## Policies

- **Embedding / ASR**: never chosen for normal chat completion; ASR runs in the file/STT pipeline; chat uses a text model.
- **Greetings**: short “Merhaba, bugün nasılsın?” stays `simple` tier (not promoted to `medium` by “bugün” web heuristics).
- **General chat (medium)**: general-purpose text models lead the list; very large reasoning models are reserved for `hard` / deep-thinking paths.
- **Vision**: `pick_auto_target_model('vision', …)` can resolve IDs from the full provider list (casing / alias), similar to image models.
- **Documents**: PDF/office-like uploads set attachment kind `document`; routing stays on **text** models with `file_extraction_pipeline` in `requires_tools` where applicable.
- **Export / conversion**: `export` modality + `export_or_conversion_pipeline` in `requires_tools` (not plain LLM-only flows).

## Manual selection

If the user picks a concrete model ID (not `auto` / `mws:auto`), `decide_mws_model` returns `manual_override` and does not replace the model.
