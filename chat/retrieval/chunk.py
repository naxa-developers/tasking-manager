#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter  # python-frontmatter
from slugify import slugify
import tiktoken

CHUNK_TOKENS = 600
# Tokenizer for chunk budgeting only (o200k-family BPE), not a model reference.
CHUNK_ENCODING = "o200k_base"
_enc = tiktoken.get_encoding(CHUNK_ENCODING)


def count_tokens(text: str) -> int:
    return len(_enc.encode(text)) if text else 0


CHAT_DIR = Path(__file__).resolve().parents[1]
RETRIEVAL_DIR = Path(__file__).resolve().parent
# RETRIEVAL_DIR is <repo>/chat/retrieval, so parents[1] is the repo root.
REPO_ROOT = (
    RETRIEVAL_DIR.parents[1]
    if RETRIEVAL_DIR.name == "retrieval"
    else RETRIEVAL_DIR.parent
)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
NEEDS_VERIFICATION_MARKER = "Needs verification"
NEEDS_VERIFICATION_RE = re.compile(
    r"\*\*Needs verification\s*[:\u2014\u2013-]\s*(M-\d{2})\s*:\*\*\s*(.*)$", re.DOTALL
)


def extract_banners(text: str) -> List[Dict[str, str]]:
    """Extract ``> **Needs verification — M-XX:** ...`` banner blocks."""
    banners: List[Dict[str, str]] = []
    block: List[str] = []
    for line in (text or "").splitlines():
        if line.startswith(">"):
            block.append(line.lstrip(">").strip())
        else:
            _flush_banner_block(block, banners)
            block = []
    _flush_banner_block(block, banners)
    return banners


def _flush_banner_block(block: List[str], out: List[Dict[str, str]]) -> None:
    if not block:
        return
    joined = " ".join(block)
    for match in NEEDS_VERIFICATION_RE.finditer(joined):
        out.append({"id": match.group(1), "text": match.group(2).strip()})


def needs_verification_node_meta(text: str) -> Dict[str, Any]:
    """Per-chunk ``Needs verification`` metadata (README §8.1).

    A chunk is flagged only when the banner text lies in that chunk; clean
    chunks of a flagged document stay unflagged.
    """
    banners = extract_banners(text)
    ids = sorted({b["id"] for b in banners})
    return {
        "needs_verification": bool(banners),
        "needs_verification_ids": ids,
        "needs_verification_banners": len(banners),
        "needs_verification_text": "; ".join(
            f"{b['id']}: {b['text']}" for b in banners
        ),
    }


def normalize_sources(raw_sources: Any) -> List[Dict[str, str]]:
    """Flatten frontmatter ``sources`` ([{type: path}]) to [{type, path}]."""
    result: List[Dict[str, str]] = []
    for entry in raw_sources or []:
        if isinstance(entry, dict):
            for stype, spath in entry.items():
                result.append({"type": str(stype), "path": str(spath)})
        else:
            result.append({"type": "unknown", "path": str(entry)})
    return result


def _frozen_commit(path: Path) -> str:
    """Provenance: git rev-parse HEAD or env FROZEN_COMMIT."""
    import os

    env = os.getenv("FROZEN_COMMIT") or os.getenv("GIT_COMMIT")
    if env:
        return env.strip()
    for root in (path, path.parent, RETRIEVAL_DIR, CHAT_DIR, REPO_ROOT):
        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(root), stderr=subprocess.DEVNULL
            )
            return out.decode().strip()[:12]
        except Exception:
            continue
    return "unknown"


def _discover_kb(kb_root: Path) -> List[Path]:
    # Section-aware discovery scoped to chat/knowledge-base
    if not kb_root.exists():
        raise FileNotFoundError(f"KB root not found: {kb_root}")
    # Governance/provenance files are not chunked (live doc count prints at runtime)
    exclude = {"06-provenance.md", "README.md"}
    docs = [p for p in kb_root.rglob("*.md") if p.name not in exclude and p.is_file()]
    docs.sort()
    return docs


def _parse_frontmatter(path: Path) -> Tuple[Dict[str, Any], str]:
    post = frontmatter.load(str(path))
    meta = dict(post.metadata) if post.metadata else {}
    body = post.content or ""
    return meta, body


def _heading_anchor(heading: str) -> str:
    return slugify(heading, lowercase=True, separator="-")


def _split_sections(
    body: str, heading_path_prefix: str = ""
) -> List[Tuple[int, str, str, str]]:
    """Split markdown into (level, heading, heading_path, section_text) on #{1,6} headings."""
    lines = body.splitlines()
    sections: List[Tuple[int, str, str, str]] = []
    cur_level = 0
    cur_heading = ""
    cur_path = heading_path_prefix
    cur_lines: List[str] = []
    stack: List[str] = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            # flush previous
            if cur_lines or cur_heading:
                text = "\n".join(cur_lines).strip()
                if text or cur_heading:
                    sections.append((cur_level, cur_heading, cur_path, text))
                cur_lines = []
            hashes, title = m.groups()
            level = len(hashes)
            title = title.strip()
            # maintain stack for path
            while len(stack) >= level:
                stack.pop()
            stack.append(title)
            cur_level = level
            cur_heading = title
            cur_path = " > ".join(stack)
        else:
            cur_lines.append(line)
    # last
    text = "\n".join(cur_lines).strip()
    if cur_heading or text:
        sections.append((cur_level, cur_heading, cur_path, text))
    # fallback: whole doc if no headings
    if not sections:
        return [(0, "", heading_path_prefix, body.strip())]
    return sections


def _section_parts(section: Tuple[Any, ...]) -> Tuple[Optional[int], str, str, str]:
    """Normalize a section tuple: (heading, path, text) or (level, heading, path, text)."""
    if len(section) >= 4:
        level, heading, path, text = section[0], section[1], section[2], section[3]
    else:
        level, heading, path, text = None, section[0], section[1], section[2]
    return level, str(heading or ""), str(path or ""), str(text or "")


def _is_question_section(level: Optional[int], heading: str) -> bool:
    """Atomic Q&A sections: question headings at section depth (### or deeper).

    Legacy 3-tuple callers pass no level; those are treated as section depth.
    """
    if not heading or not heading.rstrip().endswith("?"):
        return False
    return level is None or level >= 3


def _pack_sections_to_chunks(
    sections: List[Tuple],
    chunk_budget: int = CHUNK_TOKENS,
) -> List[Dict[str, Any]]:
    """Pack sections into tiktoken-budget chunks; question sections stay atomic.

    Accepted section shapes: (heading, heading_path, text) or
    (level, heading, heading_path, text). A question heading (``?``, level >= 3)
    is emitted with its answer as its own chunk: it is never merged with other
    sections and never carries a trailing buffer into the next section.
    Non-question sections still pack together.
    """
    chunks: List[Dict[str, Any]] = []
    cur_heading = ""
    cur_text = ""
    cur_heading_path_for_chunk = ""
    cur_headings: List[str] = []

    def emit(heading: str, path: str, text: str, headings: List[str]) -> None:
        if text.strip():
            chunks.append(
                {
                    "heading": heading,
                    "heading_path": path,
                    "headings": headings,
                    "text": text.strip(),
                }
            )

    def flush() -> None:
        nonlocal cur_text, cur_heading, cur_heading_path_for_chunk, cur_headings
        if cur_text.strip():
            emit(cur_heading, cur_heading_path_for_chunk, cur_text, cur_headings)
        cur_text = ""
        cur_heading = ""
        cur_heading_path_for_chunk = ""
        cur_headings = []

    for section in sections:
        level, heading, path, sec_text = _section_parts(section)
        # Body-less structural headings (e.g. "General Questions") carry no
        # retrievable content; heading_path is still tracked by the splitter.
        if not sec_text.strip():
            continue
        sec_full = sec_text
        # If section text doesn't contain heading, prepend for self-contained
        if heading and heading not in sec_full[:300]:
            sec_full = f"{heading}\n\n{sec_full}" if sec_full else heading
        sec_tokens = count_tokens(sec_full)
        # Question sections are atomic: one question + its answer per chunk.
        if _is_question_section(level, heading):
            flush()
            if sec_tokens <= chunk_budget:
                emit(heading, path, sec_full, [heading])
                continue
            # Oversize question: paragraph-pack, still without merging neighbors.
            buf = ""
            for p in [p for p in sec_full.split("\n\n") if p.strip()]:
                p_with_heading = p if p.startswith(heading) else f"{heading}\n{p}"
                p_tokens = count_tokens(
                    buf + "\n\n" + p_with_heading if buf else p_with_heading
                )
                if buf and p_tokens > chunk_budget:
                    emit(heading, path, buf, [heading])
                    buf = p_with_heading
                else:
                    buf = buf + "\n\n" + p_with_heading if buf else p_with_heading
            emit(heading, path, buf, [heading])
            continue
        cur_tokens = count_tokens(cur_text)
        # Section alone too big → paragraph-pack with heading carry, even
        # when it opens a chunk (cur_text empty).
        if sec_tokens > chunk_budget:
            flush()
            paras = [p for p in sec_full.split("\n\n") if p.strip()]
            buf = ""
            buf_heading = heading
            buf_path = path
            for p in paras:
                p_with_heading = (
                    p if p.startswith(heading) else f"{heading}\n{p}" if heading else p
                )
                p_tokens = count_tokens(
                    p_with_heading if not buf else buf + "\n\n" + p_with_heading
                )
                if buf and p_tokens > chunk_budget:
                    # flush buf
                    emit(
                        buf_heading, buf_path, buf, [buf_heading] if buf_heading else []
                    )
                    buf = p_with_heading
                else:
                    buf = buf + "\n\n" + p_with_heading if buf else p_with_heading
            if buf.strip():
                cur_text = buf.strip()
                cur_heading = buf_heading
                cur_heading_path_for_chunk = buf_path
                cur_headings = [buf_heading] if buf_heading else []
                # will be flushed on next iteration or end
            continue
        # Does it fit?
        if cur_text and cur_tokens + sec_tokens + 5 > chunk_budget:
            flush()
        # pack
        if not cur_text:
            cur_heading = heading
            cur_heading_path_for_chunk = path
            cur_headings = [heading] if heading else []
            cur_text = sec_full
        else:
            # appending; keep first heading as chunk heading
            cur_text = cur_text + "\n\n" + sec_full
            if heading and heading not in cur_headings:
                cur_headings.append(heading)
            # heading_path stays first
    flush()
    return chunks


def _doc_to_nodes(
    doc_path: Path,
    kb_root: Path,
    node_index_start: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Per-doc: frontmatter → sections → tiktoken chunks → node dicts with metadata."""
    # Prefer relative to repo root for stable id (chat/knowledge-base/...)
    try:
        rel = doc_path.relative_to(CHAT_DIR)
        doc_id = str(rel)
    except Exception:
        try:
            rel = doc_path.relative_to(REPO_ROOT)
            doc_id = str(rel)
        except Exception:
            doc_id = doc_path.name
    # ensure POSIX
    doc_id = doc_id.replace("\\", "/")

    meta_raw, body = _parse_frontmatter(doc_path)

    # Section-aware chunking: structural split, then budget pack.
    title = meta_raw.get("title") or doc_path.stem
    sections = _split_sections(body, heading_path_prefix=title)
    packed = _pack_sections_to_chunks(sections, CHUNK_TOKENS)

    nodes: List[Dict[str, Any]] = []
    # README §8.1: doc_hash is SHA-256 of the body (frontmatter excluded).
    doc_hash = f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
    frozen_commit = _frozen_commit(doc_path)
    frozen_at = datetime.now(timezone.utc).isoformat()
    source_entries = normalize_sources(
        meta_raw.get("source_refs") or meta_raw.get("sources") or []
    )
    for idx, ch in enumerate(packed):
        heading = ch["heading"]
        heading_path = ch["heading_path"]
        headings = ch.get("headings") or ([heading] if heading else [])
        text = ch["text"]
        # heading injection already done; ensure stable per-chunk id
        anchor = (
            _heading_anchor(heading)
            if heading
            else slugify(doc_id.replace("/", "-"))[:24]
        )
        nid = f"{doc_id}#h={anchor}#{idx}"
        # provenance: role/capability facts stay in text, not in ranking metadata
        metadata: Dict[str, Any] = {
            "doc_id": doc_id,
            "title": meta_raw.get("title") or title,
            "status": meta_raw.get("status", "published"),
            "collection": doc_id.split("/")[1] if "/" in doc_id else "general",
            "source_refs": source_entries,
            "sources": source_entries,
            "provenance": {
                "commit": frozen_commit,
                "frozen_at": frozen_at,
                "doc_hash": doc_hash,
            },
            "frozen_commit": frozen_commit,
            "frozen_at": frozen_at,
            "doc_hash": doc_hash,
            "chunk_index": idx,
            "node_index": node_index_start + idx,
            "chunk_token_count": count_tokens(text),
            "heading_anchor": anchor,
            "node_heading": heading,
            "node_heading_path": heading_path,
            "node_headings": headings,
            "parent_id": None,  # flat 53
            "is_table_chunk": False,
            "is_troubleshooting_chunk": False,
            # Flagged only when the banner text lies in this chunk (README §8.1).
            **needs_verification_node_meta(text),
        }
        # Carry extra frontmatter keys verbatim, except audience keys (personas/roles).
        for k, v in meta_raw.items():
            if k not in metadata and k not in {"personas", "roles"}:
                metadata[k] = v
        nodes.append(
            {
                "id": nid,
                "text": text,
                "metadata": metadata,
                "chunk_index": idx,
                "node_index": node_index_start + idx,
                "heading": heading,
                "heading_path": heading_path,
                "headings": headings,
            }
        )
    return nodes, node_index_start + len(nodes)


def build_chunks(kb_root: Path) -> List[Dict[str, Any]]:
    docs = _discover_kb(kb_root)
    if len(docs) != 32:
        # warn but continue — KB is FROZEN 32 substantive
        print(
            f"[warn] discover_kb_paths count={len(docs)} expected 32 (governance excluded)",
            file=sys.stderr,
        )
    all_nodes: List[Dict[str, Any]] = []
    node_index = 0
    # dedup by text
    seen_texts: set[str] = set()
    for p in docs:
        nodes, node_index = _doc_to_nodes(p, kb_root, node_index)
        for n in nodes:
            t = n["text"].strip()
            if t in seen_texts:
                continue
            seen_texts.add(t)
            # add embedding_hash for provenance drift check
            n["embedding_hash"] = hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]
            all_nodes.append(n)
    return all_nodes


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Section-aware chunker flat 53 (600-token tiktoken)"
    )
    ap.add_argument(
        "--kb",
        type=Path,
        default=CHAT_DIR / "knowledge-base",
        help="KB root (chat/knowledge-base)",
    )
    ap.add_argument(
        "--write",
        type=Path,
        default=None,
        help="Write chunks.json to path (e.g. chat/retrieval/data/chunks.json)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Don't write, just print summary"
    )
    ap.add_argument(
        "--sample", type=int, default=0, help="Print N sample chunks with heading_path"
    )
    ap.add_argument("--pretty", action="store_true", help="Pretty JSON")
    args = ap.parse_args(argv)

    kb_root: Path = args.kb if args.kb.is_absolute() else Path.cwd() / args.kb
    if not kb_root.exists():
        print(f"[chunk] KB root not found: {kb_root}", file=sys.stderr)
        print(
            "[chunk] pass --kb chat/knowledge-base (tasking-manager repo root)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(f"[chunk] KB={kb_root} PARENT_CHILD=0 flat CHUNK_TOKENS={CHUNK_TOKENS}")
    nodes = build_chunks(kb_root)
    total_tok = sum(count_tokens(n["text"]) for n in nodes)
    print(
        f"[chunk] docs={len(_discover_kb(kb_root))} chunks={len(nodes)} total_tokens~{total_tok} avg_tok={total_tok//max(1,len(nodes))}"
    )
    # distribution
    sizes = [count_tokens(n["text"]) for n in nodes]
    if sizes:
        print(
            f"       min={min(sizes)} median={sorted(sizes)[len(sizes)//2]} max={max(sizes)}"
        )
    if args.sample > 0:
        import textwrap

        for n in nodes[: args.sample]:
            print("\n---", n["id"], f"tok={count_tokens(n['text'])}")
            print(f"heading_path={n['heading_path']}")
            print(
                textwrap.shorten(
                    n["text"].replace("\n", " "), width=300, placeholder=" …"
                )
            )
    if args.write and not args.dry_run:
        out_path: Path = (
            args.write.resolve() if not args.write.is_absolute() else args.write
        )
        # ensure parent
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": "chat/retrieval/chunk.py flat 53 600-token tiktoken section-aware",
            "parent_child": False,
            "chunk_tokens": CHUNK_TOKENS,
            "count": len(nodes),
            "chunks": [
                {
                    "id": n["id"],
                    "doc_id": n["metadata"]["doc_id"],
                    "chunk_index": n["chunk_index"],
                    "node_index": n["node_index"],
                    "title": n["metadata"]["title"],
                    "status": n["metadata"]["status"],
                    "embedding_hash": n["embedding_hash"],
                    "text": n["text"],
                    "metadata": n["metadata"],
                }
                for n in nodes
            ],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2 if args.pretty else None)
        print(f"[chunk] wrote {len(nodes)} chunks -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
