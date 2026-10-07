#!/usr/bin/env python3
"""Codex の実行前後でフォルダ全体を比べ、ALLOWED 外の変更と非公開の印の混入を検出する（標準ライブラリだけ）。

codex_impl.sh はこのファイルを Codex が書けない場所へ写してから、`python3 -I -S` で実行する。
git の見え方（未追跡・ignore・commit・rename・引用符つきのパス）に頼らず、内容のハッシュで比べる。

使い方:
  scope_check.py allowed  <指示書.md>                       ALLOWED を1行1件で出す（無ければ終了 2）
  scope_check.py snapshot <root> <出力.json>                 ファイルの一覧・ハッシュ・（小さい文章は）内容を記録
  scope_check.py count    <root> <before.json>               変更の件数を出す
  scope_check.py compare  <root> <before.json> <allowed.txt> ALLOWED 外の変更と非公開の印を検査（0=OK / 3=NG）
  scope_check.py ledger   --data-dir D --vendor codex ...    費用台帳に1行足す（orch.usage と同じ形式・同じロック）
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# 非公開の印（変えない）。追加行にこれが入ったら止める
PRIVATE_MARKERS = ("/Users/", "_非公開")
SKIP_DIRS = {".git"}
ARTIFACT_DIRS = {"__pycache__", ".pytest_cache"}  # 比べずに、実行後に削除する
HEAVY_TOP = {".venv", "node_modules", "data", "logs"}  # ハッシュだけ記録する
CONTENT_MAX = 2_000_000
JST = timezone(timedelta(hours=9))


def _no_content(rel: str) -> bool:
    name = os.path.basename(rel)
    if name.startswith(".env") and name != ".env.example":
        return True  # 鍵のファイルは内容を写さない（ハッシュだけ）
    return rel.split("/", 1)[0] in HEAVY_TOP


def snapshot(root: str) -> Dict[str, dict]:
    files: Dict[str, dict] = {}
    contents: Dict[str, str] = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            rel = os.path.normpath(os.path.join(rel_dir, d)).replace(os.sep, "/")
            if d in SKIP_DIRS or d in ARTIFACT_DIRS:
                continue
            if os.path.islink(full):
                files[rel] = {"t": "link", "v": os.readlink(full)}
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            full = os.path.join(dirpath, f)
            rel = os.path.normpath(os.path.join(rel_dir, f)).replace(os.sep, "/")
            if os.path.islink(full):
                files[rel] = {"t": "link", "v": os.readlink(full)}
                continue
            h = hashlib.sha256()
            size = 0
            buf = b""
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
                    size += len(chunk)
                    if size <= CONTENT_MAX:
                        buf += chunk
            files[rel] = {"t": "file", "h": h.hexdigest(), "n": size}
            if size <= CONTENT_MAX and b"\0" not in buf and not _no_content(rel):
                contents[rel] = buf.decode("utf-8", "replace")
    return {"files": files, "contents": contents}


def changes(before: dict, after: dict) -> List[str]:
    b, a = before["files"], after["files"]
    return sorted(p for p in set(b) | set(a) if b.get(p) != a.get(p))


def parse_allowed(spec_text: str) -> List[str]:
    m = re.search(r"<!--\s*ALLOWED\s*-->(.*?)<!--\s*/ALLOWED\s*-->", spec_text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", line).strip().strip("`").strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def is_allowed(path: str, allowed: List[str]) -> bool:
    for pat in allowed:
        if path == pat or (pat.endswith("/") and path.startswith(pat)) or fnmatch.fnmatchcase(path, pat):
            return True
    return False


def added_lines(old: str, new: str) -> List[str]:
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0))
    out = []
    for line in diff[2:]:  # 先頭2行は見出し（--- / +++）。本文が "++" で始まっても取りこぼさない
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            out.append(line[1:])
    return out


def compare(root: str, before: dict, allowed: List[str]) -> List[str]:
    after = snapshot(root)
    problems = []
    for p in changes(before, after):
        if not is_allowed(p, allowed):
            problems.append(f"ALLOWED 外の変更: {p}")
            continue
        ent = after["files"].get(p)
        if ent is None:
            continue  # ALLOWED 内の削除
        if ent["t"] == "link":
            if any(m in ent["v"] for m in PRIVATE_MARKERS):
                problems.append(f"非公開の印の混入（リンク先）: {p}")
            continue
        new = after["contents"].get(p)
        if new is None:
            full = os.path.join(root, p)
            with open(full, "rb") as fh:
                new = fh.read(CONTENT_MAX).decode("utf-8", "replace")
        old = before["contents"].get(p, "")
        for i, line in enumerate(added_lines(old, new), 1):
            if any(m in line for m in PRIVATE_MARKERS):
                problems.append(f"非公開の印の混入: {p}（追加行 {i}）")
                break
    return problems


def ledger(a: argparse.Namespace) -> int:
    os.makedirs(a.data_dir, exist_ok=True)
    row = {
        "ts": datetime.now(JST).isoformat(timespec="seconds"), "vendor": a.vendor, "model": a.model[:80],
        "purpose": a.purpose[:120], "calls": 1, "in_tokens": 0, "out_tokens": 0, "usd": 0.0,
        "status": a.status, "ms": int(a.ms),
    }
    path = os.path.join(a.data_dir, "usage.jsonl")
    with open(os.path.join(a.data_dir, "usage.lock"), "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="scope_check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("allowed"); s.add_argument("spec")
    s = sub.add_parser("snapshot"); s.add_argument("root"); s.add_argument("out")
    s = sub.add_parser("count"); s.add_argument("root"); s.add_argument("before")
    s = sub.add_parser("compare"); s.add_argument("root"); s.add_argument("before"); s.add_argument("allowed")
    s = sub.add_parser("ledger")
    s.add_argument("--data-dir", required=True); s.add_argument("--vendor", default="codex")
    s.add_argument("--model", default=""); s.add_argument("--purpose", default="")
    s.add_argument("--status", default="ok", choices=("ok", "warn", "skip", "error")); s.add_argument("--ms", default="0")
    a = ap.parse_args(argv)
    if a.cmd == "allowed":
        try:
            text = open(a.spec, encoding="utf-8").read()
        except OSError:
            print("scope_check: 指示書を読めません", file=sys.stderr)
            return 2
        items = parse_allowed(text)
        if not items:
            print("scope_check: 指示書に中身のある <!-- ALLOWED --> 〜 <!-- /ALLOWED --> がありません", file=sys.stderr)
            return 2
        print("\n".join(items))
        return 0
    if a.cmd == "snapshot":
        snap = snapshot(a.root)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False)
        return 0
    if a.cmd == "count":
        before = json.load(open(a.before, encoding="utf-8"))
        print(len(changes(before, snapshot(a.root))))
        return 0
    if a.cmd == "compare":
        before = json.load(open(a.before, encoding="utf-8"))
        allowed = [l for l in open(a.allowed, encoding="utf-8").read().splitlines() if l]
        problems = compare(a.root, before, allowed)
        if problems:
            print("scope_check: NG", file=sys.stderr)
            for pr in problems[:50]:
                print(f"  - {pr}", file=sys.stderr)
            return 3
        n = len(changes(before, snapshot(a.root)))
        print(f"scope_check: OK（変更 {n} 件、すべて ALLOWED 内）")
        return 0
    if a.cmd == "ledger":
        return ledger(a)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
