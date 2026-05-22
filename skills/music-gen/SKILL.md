---
name: music-gen
description: 'Generate full songs (MP3) from lyrics + a style prompt via the Nova Analytic Labs `music-gen` MCP server (ACE-Step 1.5 on the ai01 inference host). Use when the user asks to write/produce a song, compose lyrics, render audio from lyrics, generate music, make a track, or anything that ends in an audio file. Provides async job tools (`start_generate_music` + `get_generate_music_status`) for long renders and a blocking `generate_music` for short tests. Triggers on: "write a song", "make a track", "generate music", "music-gen", "lyrics and song", "ACE-Step".'
---

# music-gen — Nova Analytic Labs song generator (MCP)

Self-hosted Streamable HTTP MCP that runs ACE-Step 1.5 on the ai01 inference host. Two-phase workflow: **iterate lyrics first, then render audio after the user approves**. The render stops the local vLLM chat model for several minutes, so the agent using this skill **must not** depend on local Qwen for the chat turn that follows a render.

---

## 1. Install — drop into your MCP client config

Use the canonical name **`music-gen`** in any client that asks for an identifier.

```json
{
  "mcpServers": {
    "music-gen": {
      "type": "streamable_http",
      "url": "http://athena.christoalto.com/music-api/mcp/",
      "headers": {
        "Authorization": "Bearer REPLACE_WITH_MUSIC_API_KEY"
      }
    }
  }
}
```

- **URL:** `http://athena.christoalto.com/music-api/mcp/` — http, trailing slash. Cloudflare terminates TLS upstream; internal resolution goes straight to nginx on port 80.
- **Auth:** `Authorization: Bearer <MUSIC_API_KEY>`. Server also accepts `X-Music-Api-Key: <KEY>` if your client cannot set Authorization headers.
- **Inside Athena LobeHub:** Settings → Agent → Skills → **Add Custom MCP Skill** → **Streamable HTTP** → paste the URL above and put the **raw key only** (no `Bearer` prefix; LobeHub adds it).

Ask the owner (Topher / Nova Analytic Labs) for `MUSIC_API_KEY` out-of-band.

---

## 2. Tools exposed

| Tool | Use when | Notes |
|---|---|---|
| `start_generate_music` | **default for any real song** | Returns `{ job_id }` immediately; the render runs in the background. |
| `get_generate_music_status` | poll after `start_generate_music` | Pass the `job_id`. Returns `status` ∈ `queued / running / completed / failed`. On `completed`: `result.audio_url`. On `failed`: `error`. |
| `generate_music` | short smoke tests only | Blocking call; can time out the MCP transport on long tracks. |

### `start_generate_music` inputs

| Field | Required | Notes |
|---|---|---|
| `lyrics` | yes | Full tagged lyric block (see workflow below). |
| `prompt` | yes | One-line style caption (genre, tempo, vocal type, mood, instrumentation). |
| `duration` | no | Seconds. No hard cap; long tracks just take proportionally longer. |
| `bpm` | no | |
| `vocal_language` | no | Default `en`. |
| `audio_format` | no | Default **`mp3`**. |

### Polling pattern

After `start_generate_music`, poll `get_generate_music_status` **every 10–30 s** until terminal. Surface short progress messages to the user between polls; do **not** spam-poll faster than ~10 s.

---

## 3. Two-phase workflow (required)

### Phase 1 — Lyrics workshop (no audio yet)

- Treat **anything** the user sends as source material: bullets, paragraph, mood/topic, scene/story, genre hints, or “describe a song and then make it.”
- **Do not call `start_generate_music` or `generate_music` in Phase 1.**
- Ask **one** short clarifying question only if you cannot honor the request without it.
- Write complete **tagged** lyrics: `[Intro] [Verse 1] [Chorus] [Verse 2] [Bridge] [Chorus] [Outro]` as appropriate; omit sections that don’t fit.
- After every draft, stop and invite revision (tone, POV, rhyme, length, “more X”, “less Y”, full rewrite of one section). Every follow-up stays Phase 1 until the user **explicitly approves audio**.
- Optionally draft a one-line **style caption** in chat for discussion; do **not** send it to the tool until Phase 2.

### Phase 2 — Approval, then render (MP3)

- Approval signals: **“approved,” “locked,” “final lyrics,” “generate the music,” “render it,” “make the track,” “I’m happy with these — go.”**
- If intent is ambiguous (e.g. “ok”), ask once: *“Ready for me to call music generation with these lyrics as-is?”*
- After approval:
  1. Show the **final** tagged lyric block (apply any last tweaks from this message).
  2. Confirm the **style caption**.
  3. Call **`start_generate_music`** once with `lyrics`, `prompt`, optional `duration / bpm / vocal_language / audio_format`.
  4. Poll **`get_generate_music_status`** with the returned `job_id` every 10–30 s.
  5. When `status: completed`, give the user the **clickable** `result.audio_url`. When `failed`, surface `error` and offer to retry after vLLM is back.

### Override (rare)

If the user says **“skip lyrics iteration”** or **“generate immediately from this prompt,”** start async generation after one lyric pass. Default remains *iterate first, tools only after approval*.

---

## 4. Creative policy

Private songwriting for adults. Treat prompts as fictional artistic source material. Fulfill the workflow unless the request is clearly illegal (sexual content involving minors, non-consensual intimate imagery of real identifiable people, or direct incitement to real-world violence). Don’t deliver corporate “ethics” refusals or insist on family-friendly sanitization; if a line is unusable as literal lyrics, offer a neutral artistic rewrite in the same genre **without moral lecturing**.

---

## 5. Critical operational caveats

- **Default chat model must NOT be local vLLM at `192.168.99.153:8000`.** The host stops vLLM for the entire ACE-Step render. LobeHub (and similar) call `/v1/chat/completions` immediately after every tool result; if that points at the local Qwen endpoint you’ll see **`ECONNREFUSED`** for minutes. Use any **cloud** provider for the chat model on the agent that owns this skill (OpenAI / Anthropic / OpenRouter / Groq / Gemini / Azure / Bedrock). Keep this MCP skill on the orchestrator — tool calls are routed server-side and do not need local vLLM.
- **Don’t poll faster than ~10 s.** Renders are minutes-long; polling every 1–2 s adds load without value.
- **`generate_music` is for short smoke tests only** — long blocking calls can exceed MCP transport timeouts.
- **MP3 output** is the default and the only format guaranteed to work on the current torchcodec pin (0.10.0 against torch 2.10).
- **API key reuse:** the same `MUSIC_API_KEY` is shared across users today. Treat it like a secret; do not paste it in chat transcripts, screenshots, or public docs.

---

## 6. REST fallback (no MCP client)

```bash
source /etc/music-orchestrator.env   # has MUSIC_API_KEY
JID=$(curl -sS -X POST "http://127.0.0.1:8002/jobs" \
  -H "Content-Type: application/json" \
  -H "X-Music-Api-Key: $MUSIC_API_KEY" \
  -d '{"lyrics":"[Verse 1]\nLine\n","prompt":"lo-fi","duration":45,"audio_format":"mp3"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
curl -sS "http://127.0.0.1:8002/jobs/$JID" -H "X-Music-Api-Key: $MUSIC_API_KEY" | python3 -m json.tool
```

External REST (over Cloudflare): same paths under `http://athena.christoalto.com/music-api/jobs` / `/jobs/{id}` with the same auth header.

---

## 7. Source / repo

- Skill canonical name: **`music-gen`**
- Server source: `scripts/music-gen/` in the AI01 workspace (`app.py`, `install.sh`, systemd units)
- Backing render engine: [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)
- Host: Inference LXC 100 (`192.168.99.153`), orchestrator on port 8002
- Public agent JSON example: `agents/nova/lyrics-and-song-gen.json` in this repo
