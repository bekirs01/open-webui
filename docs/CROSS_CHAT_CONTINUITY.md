# Cross-chat memory continuity

## What it is

- **User-level long-term memory** (existing `memory` table + vector retrieval) stores durable facts across all chats.
- **Chat context snapshots** (`chat_context_snapshot`) store one compact, LLM-generated summary per chat (refreshed on demand or when continuing/importing). This is **not** a transcript.
- **`chat.meta.cross_chat`** links a chat to a snapshot so the backend can inject a short “imported context” block into the model prompt.

## Flows

1. **Continue in new chat** (⋯ menu): refreshes/builds a snapshot from the current chat, creates a **new** empty chat, sets `meta.cross_chat` on the new chat, logs `context_transfer`.
2. **Import context from chat…**: picks another chat you own; refreshes (or reuses) that chat’s snapshot and attaches it to the **current** chat via `meta.cross_chat`.

Remove imported context with **Remove** in the navbar chip or `POST /api/v1/cross-chat/clear-import`.

## Prompt injection

Order in the first system message (when not using native function-calling for memory):

1. Long-term memory (vector-ranked), if enabled.
2. Imported cross-chat snapshot text, if `meta.cross_chat.snapshot_id` is set.

Environment:

- `ENABLE_CROSS_CHAT_CONTEXT` (default `true`) — toggles injection + API availability together with memories permission.
- `CROSS_CHAT_SNAPSHOT_MODEL` — optional override for snapshot LLM (defaults to `TASK_MODEL`).
- `CROSS_CHAT_SNAPSHOT_MAX_HISTORY_CHARS`, `CROSS_CHAT_PROMPT_MAX_CHARS`.

## Migrations

- `f5a6b7c8d9e0_add_chat_context_snapshot.py` — creates `chat_context_snapshot` and `context_transfer`.

## Demo (judges)

1. In Chat A, discuss a stable preference and a project goal; send a few messages.
2. Open ⋯ → **Continue in new chat**. You land in Chat B (empty thread) with a navbar note “Imported context”.
3. Ask something that should use the carried-over summary; answers should stay coherent.
4. Open another chat, use ⋯ → **Import context from chat…**, select Chat A; confirm the chip appears.
5. Open **Settings → Personalization → Memory** to inspect long-term rows separately from snapshots.

## Limitations

- Snapshot generation calls the task model; failures fall back to errors on explicit actions, but normal chat still works.
- Very large chats are truncated before summarization.
