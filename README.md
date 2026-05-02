# christoalto-ai01-agents

Curated **Athena internal** LobeHub assistants merged with the public [lobe-chat-agents](https://github.com/lobehub/lobe-chat-agents) catalog.

## Layout

- `agents/<group>/` — source JSON per assistant. `group` is one of: `nova`, `chris`, `development`, `custom`.
- Published wire identifier: `<group>-<filename>` (e.g. `nova-lyrics-and-song-gen.json` → `nova-lyrics-and-song-gen`).
- `scripts/build.py` — downloads upstream `index.json`, mirrors each upstream `<identifier>.json`, prepends internal agents, writes `dist/`.
- GitHub Actions pushes **`dist/`** to the orphan branch **`dist`** (used by `agents-sync` on AppServer).

## First-time setup (operator)

1. Create the GitHub repo `cjam28/christoalto-ai01-agents` (if it does not exist) and push `main`.
2. Run **Actions → Build merged agent catalog → Run workflow** once so branch **`dist`** exists before enabling `agents-sync` on the proxy stack.
3. **Repository visibility:** `agents-sync` uses anonymous `git clone` / `git fetch` over HTTPS. Keep this repo **public**, or change `REPO` in the proxy stack to embed a read-only token (e.g. `https://x-access-token:TOKEN@github.com/cjam28/christoalto-ai01-agents.git`) via Portainer env (not committed to git).
4. On Athena, add the **music MCP** once per LobeHub user if you use Lyrics and Song Gen: Streamable HTTP `https://athena.christoalto.com/music-api/mcp/` with your `MUSIC_API_KEY` (see `AI01/scripts/music-gen/README.md`).
5. After pushing [christoalto-ai01-stacks](https://github.com/cjam28/christoalto-ai01-stacks) `lobehub` + `proxy` changes, wait for Portainer GitOps (or recreate the `lobehub` service) so `AGENTS_INDEX_URL=http://agents.internal/agents/index.json` is present inside the container (`docker exec lobehub printenv AGENTS_INDEX_URL`).

## Local build

```bash
python3 scripts/build.py                 # full mirror (many HTTP requests)
python3 scripts/build.py --skip-upstream-files   # index + internal JSON only (dev)
```

Output: `dist/index.json` and `dist/*.json` (gitignored on `main`).

## Related infra

Stack changes live in [christoalto-ai01-stacks](https://github.com/cjam28/christoalto-ai01-stacks): `proxy` (nginx `agents.internal`, `agents-sync`) and `lobehub` (`AGENTS_INDEX_URL`).
