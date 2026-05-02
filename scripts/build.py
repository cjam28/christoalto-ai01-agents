#!/usr/bin/env python3
"""
Merge Athena internal agents (agents/<group>/*.json) with chat-agents.lobehub.com catalog.
Writes dist/index.json and dist/<identifier>.json for the dist branch consumed by agents-sync.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_SRC = REPO_ROOT / "agents"
DIST = REPO_ROOT / "dist"
CACHE_PATH = REPO_ROOT / "scripts" / ".upstream_cache.json"
UPSTREAM_INDEX = "https://chat-agents.lobehub.com/index.json"
UPSTREAM_AGENT = "https://chat-agents.lobehub.com/{identifier}.json"
FETCH_WORKERS = 12
HOMEPAGE = "https://github.com/cjam28/christoalto-ai01-agents"

GROUPS = ("nova", "chris", "development", "custom")
GROUP_AUTHORS = {
    "nova": "Nova Analytic Labs",
    "chris": "Chris Altomare",
    "development": "Development",
    "custom": "Custom",
}
INTERNAL_TAG_LABELS = list(GROUPS)


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "christoalto-ai01-agents-build/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_cache() -> dict:
    if not CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def discover_internal_sources() -> list[tuple[str, Path]]:
    """Return list of (group, path) for each agents/<group>/*.json."""
    out: list[tuple[str, Path]] = []
    for group in GROUPS:
        d = AGENTS_SRC / group
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if p.name.startswith("."):
                continue
            out.append((group, p))
    return out


def build_internal_agent(group: str, path: Path) -> tuple[dict, dict]:
    """Return (manifest_entry, full_agent_json)."""
    slug = path.stem
    identifier = f"{group}-{slug}"
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = dict(raw.get("meta") or {})
    config = dict(raw.get("config") or {})
    if "systemRole" not in config:
        raise ValueError(f"{path}: missing config.systemRole")

    meta["category"] = group
    tags = list(meta.get("tags") or [])
    if not tags or tags[0] != group:
        meta["tags"] = [group] + [t for t in tags if t != group]

    system_role = config.get("systemRole") or ""
    token_usage = max(1, len(system_role) // 4)

    author = raw.get("author") or meta.get("author") or GROUP_AUTHORS.get(group, group.title())
    meta.pop("author", None)
    mtime = int(path.stat().st_mtime)
    created_at = time.strftime("%Y-%m-%d", time.gmtime(mtime))

    examples = raw.get("examples") or []
    summary = raw.get("summary") or meta.get("description", "")[:500]

    manifest = {
        "author": author,
        "createdAt": created_at,
        "homepage": HOMEPAGE,
        "identifier": identifier,
        "knowledgeCount": int(raw.get("knowledgeCount", 0)),
        "meta": meta,
        "pluginCount": int(raw.get("pluginCount", 0)),
        "schemaVersion": 1,
        "tokenUsage": int(raw.get("tokenUsage", token_usage)),
    }

    full = {
        "author": author,
        "config": {
            "systemRole": config["systemRole"],
            "openingMessage": config.get("openingMessage", ""),
            "openingQuestions": config.get("openingQuestions") or [],
        },
        "createdAt": created_at,
        "examples": examples,
        "homepage": HOMEPAGE,
        "identifier": identifier,
        "knowledgeCount": manifest["knowledgeCount"],
        "meta": meta,
        "pluginCount": manifest["pluginCount"],
        "schemaVersion": 1,
        "summary": summary,
        "tokenUsage": manifest["tokenUsage"],
    }
    om = config.get("openingMessage")
    if om:
        full["openingMessage"] = om
    oq = config.get("openingQuestions")
    if oq:
        full["openingQuestions"] = oq

    return manifest, full


def fetch_one_upstream(
    row: dict, dist_dir: Path, cache_snapshot: dict
) -> tuple[str | None, str | None, bytes | None, str | None]:
    """
    Returns (identifier, row_sig_or_none, body_or_none, error_message).
    body is None when skipped (cache hit). row_sig when body written or skipped with known sig.
    """
    ident = row.get("identifier")
    if not ident:
        return None, None, None, None
    url = UPSTREAM_AGENT.format(
        identifier=urllib.parse.quote(ident, safe="")
    )
    row_sig = hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    prev = cache_snapshot.get(ident)
    out_path = dist_dir / f"{ident}.json"
    if isinstance(prev, dict) and prev.get("row_sig") == row_sig and out_path.is_file():
        return ident, row_sig, None, None
    try:
        body = http_get(url)
    except urllib.error.HTTPError as e:
        return ident, None, None, f"HTTP {e.code}"
    except OSError as e:
        return ident, None, None, str(e)
    return ident, row_sig, body, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--skip-upstream-files",
        action="store_true",
        help="Only write merged index + internal JSONs (no per-upstream .json mirror).",
    )
    args = ap.parse_args()

    DIST.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    upstream_raw = http_get(UPSTREAM_INDEX)
    upstream = json.loads(upstream_raw.decode("utf-8"))
    upstream_agents: list = list(upstream.get("agents") or [])
    upstream_tags: list = list(upstream.get("tags") or [])

    internal_manifest: list[dict] = []
    seen_identifiers: set[str] = set()

    for group, path in discover_internal_sources():
        manifest, full = build_internal_agent(group, path)
        ident = manifest["identifier"]
        if ident in seen_identifiers:
            print(f"duplicate identifier {ident}", file=sys.stderr)
            return 1
        seen_identifiers.add(ident)
        internal_manifest.append(manifest)
        (DIST / f"{ident}.json").write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"internal {ident} <- {path.relative_to(REPO_ROOT)}")

    merged_tags = list(dict.fromkeys(INTERNAL_TAG_LABELS + upstream_tags))
    merged_index = {
        "schemaVersion": upstream.get("schemaVersion", 1),
        "agents": internal_manifest + upstream_agents,
        "tags": merged_tags,
    }
    (DIST / "index.json").write_text(
        json.dumps(merged_index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    cache_agents = cache.setdefault("agents", {})
    errors = 0
    total = len(upstream_agents)

    if not args.skip_upstream_files:
        snap = dict(cache_agents)
        done = 0
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
            futures = [
                ex.submit(fetch_one_upstream, row, DIST, snap)
                for row in upstream_agents
            ]
            for fut in as_completed(futures):
                ident, row_sig, body, err = fut.result()
                done += 1
                if err and ident:
                    print(f"warn: {ident} {err}", file=sys.stderr)
                    errors += 1
                elif ident and row_sig and body is not None:
                    (DIST / f"{ident}.json").write_bytes(body)
                    cache_agents[ident] = {
                        "row_sig": row_sig,
                        "fetched_at": int(time.time()),
                    }
                if done % 100 == 0:
                    print(f"upstream progress {done}/{total}…", flush=True)
    else:
        print("skip-upstream-files: index + internal agents only", flush=True)

    save_cache(cache)
    print(f"wrote {DIST / 'index.json'} ({len(merged_index['agents'])} agents)")
    if errors:
        print(f"completed with {errors} upstream fetch errors", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
