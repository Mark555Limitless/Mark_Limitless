#!/usr/bin/env python3
"""指示書の ALLOWED 外の変更と、非公開の印（ローカルの絶対パス・非公開フォルダ名）の混入を検出する。

使い方: python3 tools/scope_check.py <指示書.md> [--baseline <実行前の未追跡ファイル一覧>]
終了コード: 0=問題なし / 2=前提の誤り（ALLOWED が無い等）/ 3=ALLOWED 外の変更か、非公開の印の混入
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Set

# 非公開の印（変えない）。追加行にこれが入ったら止める
PRIVATE_MARKERS = ("/Users/", "_非公開")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def allowed_paths(spec: Path) -> List[str]:
    text = spec.read_text(encoding="utf-8")
    m = re.search(r"<!--\s*ALLOWED\s*-->(.*?)<!--\s*/ALLOWED\s*-->", text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip().strip("`").lstrip("-* ").strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def is_allowed(path: str, allowed: List[str]) -> bool:
    for pat in allowed:
        if path == pat or fnmatch.fnmatch(path, pat) or (pat.endswith("/") and path.startswith(pat)):
            return True
    return False


def changed_files(baseline_untracked: Set[str]) -> List[str]:
    tracked = [p for p in git("diff", "--name-only", "HEAD", "--relative").splitlines() if p]
    untracked = [p for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p]
    return sorted(set(tracked) | (set(untracked) - baseline_untracked))


def added_lines(path: str, untracked: bool) -> List[str]:
    if untracked:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
    diff = git("diff", "-U0", "HEAD", "--relative", "--", path)
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--baseline", default=None)
    a = ap.parse_args()
    spec = Path(a.spec)
    if not spec.is_file():
        print(f"scope_check: 指示書がありません: {spec}", file=sys.stderr)
        return 2
    allowed = allowed_paths(spec)
    if not allowed:
        print("scope_check: 指示書に <!-- ALLOWED --> 〜 <!-- /ALLOWED --> がありません", file=sys.stderr)
        return 2
    baseline: Set[str] = set()
    if a.baseline and Path(a.baseline).is_file():
        baseline = {l for l in Path(a.baseline).read_text(encoding="utf-8").splitlines() if l}
    untracked_now = set(git("ls-files", "--others", "--exclude-standard").splitlines())
    changed = changed_files(baseline)
    problems = []
    for p in changed:
        if not is_allowed(p, allowed):
            problems.append(f"ALLOWED 外の変更: {p}")
            continue
        for i, line in enumerate(added_lines(p, p in untracked_now), 1):
            for mark in PRIVATE_MARKERS:
                if mark in line:
                    problems.append(f"非公開の印の混入: {p}（追加行 {i}）")
                    break
    if problems:
        print("scope_check: NG", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 3
    print(f"scope_check: OK（変更 {len(changed)} 件、すべて ALLOWED 内）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
