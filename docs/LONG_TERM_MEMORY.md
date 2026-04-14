# Long-term Memory (Feature #9)

## What it does

- **Manual:** Settings -> Personalization -> Memory -> Manage: add, edit, archive, or delete memories.
- **Automatic:** After each chat turn (`/api/chat/completed`), a background task model evaluates the last user+assistant exchange(s). If a durable, user-specific fact is found, it is saved to the database and vector collection.
- **Batch extraction:** Up to `LONG_TERM_MEMORY_BATCH_PAIRS` (default 3) user/assistant pairs per turn are evaluated, so longer conversations also get their earlier facts captured.
- **In-response usage:** For each new message, the last user query is embedded and top-K memories are retrieved via vector search + importance/confidence/recency ranking, then injected as a system message.
- **Cross-chat continuity:** See [CROSS_CHAT_CONTINUITY.md](./CROSS_CHAT_CONTINUITY.md).

## Architecture

| Layer | File / location |
|-------|-----------------|
| Schema | `memory` table + Alembic `c3d4e5f6a7b8_add_long_term_memory_columns.py` |
| Model | `backend/open_webui/models/memories.py` |
| Safety / PII | `backend/open_webui/utils/long_term_memory/safety.py` |
| Dedup (fuzzy + semantic) | `backend/open_webui/utils/long_term_memory/dedupe.py` |
| LLM extraction | `backend/open_webui/utils/long_term_memory/extraction.py` |
| Pipeline / scheduling | `backend/open_webui/utils/long_term_memory/pipeline.py` <- `chat_completed` |
| Retrieval + ranking | `backend/open_webui/utils/long_term_memory/retrieval.py` <- `chat_memory_handler` |
| API | `backend/open_webui/routers/memories.py` (CRUD + `/stats`) |
| Frontend | `Personalization.svelte`, `ManageModal.svelte` |

## Data flow

```
User sends message
       |
       v
middleware.process_chat_payload
  -> chat_memory_handler
       -> fetch_ranked_memories (embed query -> vector search -> rank)
       -> inject system message with top-K memories
  -> ... (RAG, tools, web search)
  -> generate_chat_completion
       |
       v
chat_completed (outlet)
  -> schedule_memory_extraction
       -> extract last N user+assistant pairs
       -> LLM evaluates each pair
       -> safety filter (PII, secrets, Turkish TCKN/IBAN/phone)
       -> dedupe (fuzzy SequenceMatcher + optional semantic cosine)
       -> insert or update memory + vector upsert
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_MEMORIES` | `true` | Master switch for the memory system |
| `USER_MEMORY_TOP_K` | `10` | How many memories to inject per request (max 32) |
| `LONG_TERM_MEMORY_AUTO_EXTRACT` | `true` | Enable/disable automatic extraction after chat turns |
| `LONG_TERM_MEMORY_TASK_MODEL` | (empty -> `TASK_MODEL`) | Override model for extraction LLM |
| `LONG_TERM_MEMORY_MIN_CONFIDENCE` | `0.45` | Minimum LLM confidence to save a memory |
| `LONG_TERM_MEMORY_DEDUPE_THRESHOLD` | `0.88` | Fuzzy string match threshold for near-duplicate merging |
| `LONG_TERM_MEMORY_BATCH_PAIRS` | `3` | How many user+assistant pairs to extract per turn |
| `LONG_TERM_MEMORY_SEMANTIC_DEDUPE_THRESHOLD` | `0.92` | Cosine similarity threshold for semantic dedup |
| `LONG_TERM_MEMORY_EXTRACTION_MAX_USER_CHARS` | `4000` | Max chars from user message sent to extraction LLM |
| `LONG_TERM_MEMORY_EXTRACTION_MAX_ASSISTANT_CHARS` | `8000` | Max chars from assistant message sent to extraction LLM |
| `LTM_VECTOR_SCORE_IS_DISTANCE` | `true` | `true` = ChromaDB distance (0-2); `false` = similarity (0-1) |
| `LTM_RECENCY_HALF_LIFE_DAYS` | `60` | Exponential half-life for time-decay in ranking |

## Safety

- `safety.py` rejects:
  - API keys (OpenAI `sk-`, Slack `xox`, AWS `AKIA`, Bearer tokens, private keys)
  - Password/credential fields (English + Turkish: `password`, `parola`, `sifre`)
  - Government/financial IDs: TCKN (11-digit), Turkish IBAN (TR + 24 digits), credit card numbers
  - Phone numbers: Turkish mobile (`+90 5xx` / `05xx` patterns)
  - Sensitive keywords: credit card, passport, social security, TC kimlik, IBAN, etc. (EN + TR)
- Only concise single-sentence candidates are stored; full chat transcripts are never saved.

## Memory management UI

- **Status toggle:** Each memory can be toggled between `active` and `archived`. Archived memories are excluded from retrieval.
- **Category filter:** Filter memories by category (preference, profile, project, task, constraint, etc.)
- **Statistics:** Total / active / archived counts and category distribution shown in the header.
- **Bulk operations:** "Clear memory" deletes all memories for the user.

## Auto mode context sharing

When MWS Auto mode runs multi-step workflows (vision->text, text->polish, code->review), the second model now receives the **complete conversation history** including:
- All previous chat turns (user + assistant messages)
- Images and file attachments
- Long-term memory injections
- RAG/web search context
- Cross-chat imported context

The first model's output is appended as an assistant message, followed by a synthesis directive. This eliminates the previous context-loss problem where polisher/synthesizer models had no access to the conversation.

## Demo scenario

1. Settings -> Personalization: Memory ON, Auto-save memories from chat ON.
2. New chat: *"I always prefer concise technical answers."*
3. Get a short reply; wait a few seconds (background extraction).
4. Memory -> Manage: new row should appear (source_type: `chat_auto`, category: `preference`).
5. Open a **new chat**: *"What should I focus on in this project?"* — response should reflect your preference.
6. Edit or archive the memory; verify behavior updates.

## Tests

```bash
cd backend && pytest open_webui/test/unit/test_long_term_memory.py -q
```

## Limitations

- Extraction depends on the task model and embedding API; if either fails, the chat still works normally.
- For very large memory collections, use `/memories/reset` to re-embed all vectors.
- Semantic dedup requires the vector collection to already contain embeddings; new users won't benefit until a few memories exist.
