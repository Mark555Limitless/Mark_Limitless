#!/usr/bin/env python3
"""Codex の実行前後でフォルダ全体を比べ、ALLOWED 外の変更と非公開の印の混入を検出する（標準ライブラリだけ）。

codex_impl.sh はこのファイルを Codex が書けない場所へ写してから、`python3 -I -S` で実行する。
git の見え方（未追跡・ignore・commit・rename・引用符つきのパス）に頼らず、内容のハッシュで比べる。
git を1回も実行しないうちに入れ子の .git を探して隔離する（.git の設定に仕込まれたコマンドを走らせないため）。

使い方:
  scope_check.py allowed  <指示書.md>                        ALLOWED を1行1件で出す（無ければ終了 2）
  scope_check.py nested-git <root>                           作業フォルダ内の .git を探す（あれば終了 3。root/.git は上位に .git が無いときだけ除く）
  scope_check.py snapshot <root> <出力.json>                  ファイルの一覧・種類・権限・ハッシュ・（小さい文章は）内容を記録
  scope_check.py count    <root> <before.json>                変更の件数を出す
  scope_check.py quarantine-git <root> <before.json> <隔離先>  実行後に現れた .git を作業フォルダの外へ移す（見つかれば終了 3）
  scope_check.py compare  <root> <before.json> <allowed.txt> [--save-after A]  ALLOWED 外の変更と非公開の印を検査（0=OK / 3=NG）
  scope_check.py recheck  <root> <after.json>                 検査の後にも書き込みが続いていないか（0=無し / 3=あり）
  scope_check.py gitfp    <gitdir>                            本物の GITDIR の config・hooks・info/attributes のハッシュ
  scope_check.py fsum     <path>                              1ファイルの種類・権限・ハッシュ（FIFO 等は開かない）
  scope_check.py ledger   --data-dir D --vendor codex ...     費用台帳に1行足す（orch.usage と同じ形式・同じロック）
snapshot・count・quarantine-git・compare・recheck は --real-gitdir <GITDIR> を受け取り、本物の .git は比べない。
.git の判定は大文字小文字を区別しない（Mac の既定のファイルシステムでは .GIT も git が .git として読むため）。
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# 非公開の印（変えない）。追加行にこれが入ったら止める
PRIVATE_MARKERS = ("/Users/", "_非公開")
ARTIFACT_DIRS = {"__pycache__", ".pytest_cache"}  # 本物のディレクトリなら比べずに実行後に削除。リンクやファイルなら違反
HEAVY_TOP = {".venv", "node_modules", "data", "logs"}  # ハッシュだけ記録する
CONTENT_MAX = 2_000_000
JST = timezone(timedelta(hours=9))
# Codex の実行中に司令塔・orch・hooks が書く記録（追記だけなら許す。実行可能・リンク・追記以外の変更は違反）
# git で追跡される（公開される）ファイルは入れない。追記部分は ALLOWED の判定も非公開の印の検査も通らないため（tests が .gitignore を確かめる）
APPEND_ONLY = {"data/usage.jsonl", "data/decisions_shadow.jsonl", "state/.session-end.log"}
APPEND_GLOBS = ("logs/*.log",)
# 印のファイル（ロック・セッションの開始印と編集印・停止スイッチ）。新規作成は「空」（開始印は数字、停止スイッチは中身を問わない）だけ許す。
# 既存の印の中身の変更は違反（開始印だけは、より新しい時刻への更新を許す。再開・圧縮で書き直されるため）。削除・実行権限も違反
MARKER_GLOBS = ("data/*.lock", "logs/*.lock", "state/.sessions/*", "data/.*_disabled")
# 費用台帳の数値の欄（追記された行で、数値でない・負・無限大・NaN なら違反。上限の計算を壊させない）
LEDGER_NUMS = ("usd", "calls", "in_tokens", "out_tokens", "ms")


# HFS+ が名前の比較で無視する文字（git の is_hfs_dotgit と同じ。ゼロ幅文字・方向制御文字・BOM）
HFS_IGNORABLE = dict.fromkeys([0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                               0x206A, 0x206B, 0x206C, 0x206D, 0x206E, 0x206F, 0xFEFF])


def is_git_name(name: str) -> bool:
    """git が .git として読みうる名前か（大文字小文字・HFS+ で無視される文字を問わない）。"""
    return name.translate(HFS_IGNORABLE).casefold() == ".git"


def _open_regular(path: str):
    """リンクをたどらず、FIFO 等で止まらないように開く。通常のファイルでなければ None。"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        return None
    return os.fdopen(fd, "rb")


def _no_content(rel: str) -> bool:
    name = os.path.basename(rel)
    if name.startswith(".env") and name != ".env.example":
        return True  # 鍵のファイルは内容を写さない（ハッシュだけ）
    return rel.split("/", 1)[0] in HEAVY_TOP


def _rel(root: str, full: str) -> str:
    return os.path.normpath(os.path.relpath(full, root)).replace(os.sep, "/")


def _git_entry(full: str) -> dict:
    """.git（ディレクトリ・ファイル・リンク）を、中身の要所（HEAD・config・commondir）のハッシュで表す。"""
    try:
        st = os.lstat(full)
    except FileNotFoundError:
        return {"t": "git", "v": "none"}
    if stat.S_ISLNK(st.st_mode):
        return {"t": "git", "v": "link:" + os.readlink(full)}
    h = hashlib.sha256()
    if stat.S_ISDIR(st.st_mode):
        for name in ("HEAD", "config", "commondir", "gitdir"):
            fh = _open_regular(os.path.join(full, name))
            if fh is not None:
                with fh:
                    h.update(name.encode() + b"\0" + fh.read(1 << 20))
        return {"t": "git", "v": "dir:" + h.hexdigest()}
    fh = _open_regular(full)
    if fh is not None:
        with fh:
            h.update(fh.read(1 << 20))
        return {"t": "git", "v": "file:" + h.hexdigest()}
    return {"t": "git", "v": "special:%o" % st.st_mode}


def _is_real_git(full: str, real_git: str) -> bool:
    return bool(real_git) and not os.path.islink(full) and os.path.realpath(full) == real_git


def snapshot(root: str, real_gitdir: str = "") -> Dict[str, dict]:
    """ファイルの一覧（種類・権限・ハッシュ）と、小さい文章の内容。FIFO などは開かない。"""
    files: Dict[str, dict] = {}
    contents: Dict[str, str] = {}
    root = os.path.abspath(root)
    real_git = os.path.realpath(real_gitdir) if real_gitdir else ""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            rel = _rel(root, full)
            if is_git_name(d):
                if not _is_real_git(full, real_git):
                    files[rel] = _git_entry(full)  # 本物の GITDIR は比べない（config・hooks は gitfp、HEAD は codex_impl.sh が確かめる）
                continue
            if os.path.islink(full):  # リンクの判定を先に行う（__pycache__ のリンクを見逃さない）
                files[rel] = {"t": "badartifact" if d in ARTIFACT_DIRS else "link", "v": os.readlink(full)}
                continue
            if d in ARTIFACT_DIRS:
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            full = os.path.join(dirpath, f)
            rel = _rel(root, full)
            try:
                st = os.lstat(full)
            except FileNotFoundError:
                continue
            if is_git_name(f):
                files[rel] = _git_entry(full)
                continue
            if stat.S_ISLNK(st.st_mode):
                files[rel] = {"t": "badartifact" if f in ARTIFACT_DIRS else "link", "v": os.readlink(full)}
                continue
            if f in ARTIFACT_DIRS:
                files[rel] = {"t": "badartifact", "v": "file"}
                continue
            fh = _open_regular(full) if stat.S_ISREG(st.st_mode) else None
            if fh is None:
                files[rel] = {"t": "special", "v": "%o" % st.st_mode}  # FIFO・ソケット・デバイスは読まない
                continue
            h = hashlib.sha256()
            size = 0
            buf = b""
            with fh:
                mode = stat.S_IMODE(os.fstat(fh.fileno()).st_mode)
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
                    size += len(chunk)
                    if size <= CONTENT_MAX:
                        buf += chunk
            files[rel] = {"t": "file", "h": h.hexdigest(), "n": size, "m": mode}
            if size <= CONTENT_MAX and b"\0" not in buf and not _no_content(rel):
                contents[rel] = buf.decode("utf-8", "replace")
    return {"files": files, "contents": contents}


def _has_git_above(root: str) -> bool:
    d = os.path.dirname(os.path.abspath(root))
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return True
        nd = os.path.dirname(d)
        if nd == d:
            return False
        d = nd


def find_git(root: str) -> List[str]:
    """作業フォルダ内の .git をすべて探す（__pycache__・.venv・node_modules の中も）。git は実行しない。"""
    root = os.path.abspath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            if is_git_name(name):
                found.append(_rel(root, os.path.join(dirpath, name)))
        dirnames[:] = [d for d in dirnames if not is_git_name(d)]
    return sorted(found)


def nested_git_now(root: str) -> List[str]:
    """実行前の点検: root/.git は、上位に .git が無い（root がリポジトリの根）ときだけ正当とみなす。"""
    top_ok = not _has_git_above(root)
    return [p for p in find_git(root) if not (p == ".git" and top_ok)]


def nested_git(before: dict, after: dict) -> List[str]:
    """実行前と違う .git（新規・変更・削除）。"""
    b, a = before["files"], after["files"]
    return sorted(p for p in set(b) | set(a)
                  if (a.get(p, {}).get("t") == "git" or b.get(p, {}).get("t") == "git") and a.get(p) != b.get(p))


def quarantine_git(root: str, before: dict, dest: str, real_gitdir: str = "") -> Tuple[List[str], List[str]]:
    """実行前に無かった（か変わった）.git を作業フォルダの外へ移す（名前から .git を外す）。(移した, 移せなかった) を返す。"""
    root = os.path.abspath(root)
    real_git = os.path.realpath(real_gitdir) if real_gitdir else ""
    moved, failed = [], []
    targets = []
    for rel in find_git(root):
        full = os.path.join(root, rel)
        if _is_real_git(full, real_git):
            continue
        if before["files"].get(rel) == _git_entry(full):
            continue  # 実行前からあって変わっていない（ワークツリーの .git ファイル等。実行前の点検で入れ子は弾いてある）
        targets.append(rel)
    if targets:
        os.makedirs(dest, mode=0o700, exist_ok=True)
    for i, rel in enumerate(targets, 1):
        target = os.path.join(dest, "%02d-%s" % (i, re.sub(r"(?i)\.git", "dotgit", rel.replace("/", "_"))))
        try:
            shutil.move(os.path.join(root, rel), target)
            moved.append(rel)
        except OSError:
            failed.append(rel)
    return moved, failed


def _fp_entry(path: str) -> bytes:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return path.encode() + b"\0none\n"
    if stat.S_ISLNK(st.st_mode):
        return path.encode() + b"\0link:" + os.readlink(path).encode() + b"\n"
    fh = _open_regular(path) if stat.S_ISREG(st.st_mode) else None
    if fh is None:
        return path.encode() + b"\0special:%o\n" % st.st_mode
    with fh:
        return path.encode() + b"\0%o:" % stat.S_IMODE(st.st_mode) + hashlib.sha256(fh.read()).hexdigest().encode() + b"\n"


def git_fingerprint(gitdir: str) -> str:
    """本物の GITDIR のうち、コマンドを仕込める場所（config・config.worktree・info/attributes・hooks/）のハッシュ。"""
    h = hashlib.sha256()
    dirs = [os.path.abspath(gitdir)]
    fh = _open_regular(os.path.join(gitdir, "commondir"))
    if fh is not None:
        with fh:
            common = fh.read(4096).decode("utf-8", "replace").strip()
        dirs.append(os.path.normpath(os.path.join(gitdir, common)))
    for d in dirs:
        for name in ("config", "config.worktree", "commondir", "info/attributes"):
            h.update(_fp_entry(os.path.join(d, name)))
        hooks = os.path.join(d, "hooks")
        h.update(_fp_entry(hooks) if os.path.islink(hooks) or not os.path.isdir(hooks) else b"hooks-dir\n")
        if os.path.isdir(hooks) and not os.path.islink(hooks):
            for n in sorted(os.listdir(hooks)):
                h.update(_fp_entry(os.path.join(hooks, n)))
    return h.hexdigest()


def file_sum(path: str) -> str:
    """ファイルの種類・権限・ハッシュ（FIFO などは開かない）。無ければ none。"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "none"
    if stat.S_ISLNK(st.st_mode):
        return "link:" + os.readlink(path)
    fh = _open_regular(path) if stat.S_ISREG(st.st_mode) else None
    if fh is None:
        return "special:%o" % st.st_mode
    h = hashlib.sha256()
    with fh:
        mode = stat.S_IMODE(os.fstat(fh.fileno()).st_mode)
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "file:%o:%s" % (mode, h.hexdigest())


def _match(path: str, globs) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def is_system(path: str) -> bool:
    return path in APPEND_ONLY or _match(path, APPEND_GLOBS) or _match(path, MARKER_GLOBS)


def _marker_problem(root: str, p: str, b: Optional[dict], a: dict, old_text: Optional[str]) -> str:
    fh = _open_regular(os.path.join(root, p))
    if fh is None:
        return f"印のファイルを読めない: {p}"
    with fh:
        new = fh.read(4097)
    is_new = b is None or b.get("t") != "file"
    if p.endswith(".start"):
        if not re.fullmatch(rb"\s*[0-9]{1,12}\s*", new):
            return f"開始時刻の印が数字でない: {p}"
        if not is_new and old_text is not None and re.fullmatch(r"\s*[0-9]{1,12}\s*", old_text) and int(new) < int(old_text):
            return f"開始時刻の印が過去に戻された: {p}"
        return ""
    if is_new:
        if os.path.basename(p).endswith("_disabled"):
            return ""  # 停止スイッチ（止める方向にしか働かない）。中身は理由のメモでよい
        if new.strip():
            return f"新しい印のファイルに中身がある: {p}"
        return ""
    if a.get("h") != b.get("h"):
        return f"既存の印のファイルの中身が変わった: {p}"
    return ""


def system_change_problem(root: str, p: str, b: Optional[dict], a: Optional[dict], old_text: Optional[str] = None) -> str:
    """司令塔・orch・hooks の記録ファイルの変更が許せる形かを調べる。問題があれば理由、無ければ空文字。"""
    if a is None:
        return f"記録ファイルの削除: {p}"
    if a.get("t") != "file":
        return f"記録ファイルが通常のファイルでない: {p}"
    if a.get("m", 0) & 0o111:
        return f"記録ファイルに実行権限: {p}"
    if _match(p, MARKER_GLOBS) and not (p in APPEND_ONLY or _match(p, APPEND_GLOBS)):
        return _marker_problem(root, p, b, a, old_text)
    if (p in APPEND_ONLY or _match(p, APPEND_GLOBS)) and b and b.get("t") == "file":
        n = int(b.get("n", 0))
        if a.get("n", 0) < n:
            return f"記録ファイルが短くなった（追記以外の変更）: {p}"
        fh = _open_regular(os.path.join(root, p))
        if fh is None:
            return f"記録ファイルを読めない: {p}"
        with fh:
            head = fh.read(n)
            tail = fh.read(CONTENT_MAX)
        if hashlib.sha256(head).hexdigest() != b.get("h"):
            return f"記録ファイルの既存部分が変わった（追記以外の変更）: {p}"
        if p.endswith(".jsonl"):
            return _jsonl_problem(p, tail)
    elif p.endswith(".jsonl") and (b is None or b.get("t") != "file"):
        fh = _open_regular(os.path.join(root, p))
        if fh is None:
            return f"記録ファイルを読めない: {p}"
        with fh:
            return _jsonl_problem(p, fh.read(CONTENT_MAX))
    return ""


def _jsonl_problem(p: str, data: bytes) -> str:
    """追記された JSON 行が、オブジェクトで、台帳なら数値の欄が 0 以上の有限の数かを確かめる。"""
    for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return f"記録ファイルに JSON でない行が追記された: {p}（追記 {i} 行目）"
        if not isinstance(row, dict):
            return f"記録ファイルに JSON オブジェクトでない行が追記された: {p}（追記 {i} 行目）"
        if p == "data/usage.jsonl":
            for k in LEDGER_NUMS:
                v = row.get(k, 0)
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                    return f"費用台帳に不正な数値が追記された（{k}）: {p}（追記 {i} 行目）"
    return ""


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


def compare(root: str, before: dict, allowed: List[str], real_gitdir: str = "") -> Tuple[List[str], List[str]]:
    """(問題の一覧, 記録ファイル以外の変更の一覧) を返す。"""
    after = snapshot(root, real_gitdir)
    problems = []
    for p in nested_git(before, after):
        problems.append(f"入れ子の .git（git の設定でコマンドを仕込める）: {p}")
    changed = changes(before, after)
    for p in changed:
        b_ent, ent = before["files"].get(p), after["files"].get(p)
        kind = (ent or b_ent or {}).get("t")
        if kind == "git":
            continue  # 上で報告済み
        if (ent or {}).get("t") == "badartifact":
            problems.append(f"__pycache__/.pytest_cache が本物のディレクトリでない（リンク等）: {p}")
            continue
        if (ent or {}).get("t") == "special":
            problems.append(f"通常のファイルでないもの（FIFO 等）: {p}")
            continue
        if is_system(p):
            why = system_change_problem(root, p, b_ent, ent, before["contents"].get(p))
            if why:
                problems.append(why)
            continue
        if not is_allowed(p, allowed):
            problems.append(f"ALLOWED 外の変更: {p}")
            continue
        if ent is None:
            continue  # ALLOWED 内の削除
        if ent["t"] == "link":
            if any(m in ent["v"] for m in PRIVATE_MARKERS):
                problems.append(f"非公開の印の混入（リンク先）: {p}")
            continue
        if b_ent and b_ent.get("t") == "file" and ent.get("m", 0) & 0o111 and not b_ent.get("m", 0) & 0o111:
            problems.append(f"実行権限が付いた: {p}")
            continue
        new = after["contents"].get(p)
        if new is None:
            fh = _open_regular(os.path.join(root, p))
            if fh is None:
                problems.append(f"読めない変更: {p}")
                continue
            with fh:
                new = fh.read(CONTENT_MAX).decode("utf-8", "replace")
        old = before["contents"].get(p, "")
        for i, line in enumerate(added_lines(old, new), 1):
            if any(m in line for m in PRIVATE_MARKERS):
                problems.append(f"非公開の印の混入: {p}（追加行 {i}）")
                break
    return problems, changed, after


def recheck(root: str, after: dict, real_gitdir: str = "") -> List[str]:
    """検査の後（片付けと待ち時間の後）にもう一度記録し、書き込みが続いていないかを確かめる。
    許すのは、片付けで消えたリンク等の __pycache__ と、記録ファイルの追記・印のファイルだけ。"""
    now = snapshot(root, real_gitdir)
    problems = []
    for p in changes(after, now):
        b_ent, ent = after["files"].get(p), now["files"].get(p)
        if ent is None and (b_ent or {}).get("t") == "badartifact":
            continue
        if is_system(p) and (ent or {}).get("t") != "git":
            why = system_change_problem(root, p, b_ent, ent, after["contents"].get(p))
            if why:
                problems.append(why)
            continue
        problems.append(f"検査の後にも変更が続いた（Codex が残したプロセスの可能性）: {p}")
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


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="scope_check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("allowed"); s.add_argument("spec")
    s = sub.add_parser("nested-git"); s.add_argument("root")
    s = sub.add_parser("snapshot"); s.add_argument("root"); s.add_argument("out"); s.add_argument("--real-gitdir", default="")
    s = sub.add_parser("count"); s.add_argument("root"); s.add_argument("before"); s.add_argument("--real-gitdir", default="")
    s = sub.add_parser("compare"); s.add_argument("root"); s.add_argument("before"); s.add_argument("allowed"); s.add_argument("--real-gitdir", default="")
    s.add_argument("--save-after", default="")
    s = sub.add_parser("recheck"); s.add_argument("root"); s.add_argument("after"); s.add_argument("--real-gitdir", default="")
    s = sub.add_parser("quarantine-git"); s.add_argument("root"); s.add_argument("before"); s.add_argument("dest"); s.add_argument("--real-gitdir", default="")
    s = sub.add_parser("gitfp"); s.add_argument("gitdir")
    s = sub.add_parser("fsum"); s.add_argument("path")
    s = sub.add_parser("ledger")
    s.add_argument("--data-dir", required=True); s.add_argument("--vendor", default="codex")
    s.add_argument("--model", default=""); s.add_argument("--purpose", default="")
    s.add_argument("--status", default="ok", choices=("ok", "warn", "skip", "error")); s.add_argument("--ms", default="0")
    a = ap.parse_args(argv)
    if a.cmd == "allowed":
        try:
            with open(a.spec, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            print("scope_check: 指示書を読めません", file=sys.stderr)
            return 2
        items = parse_allowed(text)
        if not items:
            print("scope_check: 指示書に中身のある <!-- ALLOWED --> 〜 <!-- /ALLOWED --> がありません", file=sys.stderr)
            return 2
        print("\n".join(items))
        return 0
    if a.cmd == "nested-git":
        found = nested_git_now(a.root)
        for p in found[:20]:
            print(f"scope_check: 作業フォルダ内に .git があります: {p}", file=sys.stderr)
        return 3 if found else 0
    if a.cmd == "snapshot":
        snap = snapshot(a.root, a.real_gitdir)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False)
        return 0
    if a.cmd == "count":
        print(len(changes(_load(a.before), snapshot(a.root, a.real_gitdir))))
        return 0
    if a.cmd == "quarantine-git":
        moved, failed = quarantine_git(a.root, _load(a.before), a.dest, a.real_gitdir)
        for p in moved:
            print(f"scope_check: 入れ子の .git を作業フォルダの外へ隔離しました: {p}", file=sys.stderr)
        for p in failed:
            print(f"scope_check: 入れ子の .git を隔離できませんでした（git を使わないこと）: {p}", file=sys.stderr)
        if failed:
            return 4
        return 3 if moved else 0
    if a.cmd == "compare":
        with open(a.allowed, encoding="utf-8") as fh:
            allowed = [l for l in fh.read().splitlines() if l]
        problems, changed, after = compare(a.root, _load(a.before), allowed, a.real_gitdir)
        if a.save_after:
            fd = os.open(a.save_after, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(after, fh, ensure_ascii=False)
        if problems:
            print("scope_check: NG", file=sys.stderr)
            for pr in problems[:50]:
                print(f"  - {pr}", file=sys.stderr)
            return 3
        user = [p for p in changed if not is_system(p)]
        system = [p for p in changed if is_system(p)]
        print(f"scope_check: OK（変更 {len(user)} 件、すべて ALLOWED 内）")
        for p in user[:50]:
            print(f"  - {p}")
        if system:
            print(f"scope_check: 記録ファイルの追記・印のファイル {len(system)} 件（検査済み）")
            for p in system[:20]:
                print(f"  - {p}")
        return 0
    if a.cmd == "recheck":
        problems = recheck(a.root, _load(a.after), a.real_gitdir)
        for pr in problems[:50]:
            print(f"scope_check: {pr}", file=sys.stderr)
        return 3 if problems else 0
    if a.cmd == "gitfp":
        print(git_fingerprint(a.gitdir))
        return 0
    if a.cmd == "fsum":
        print(file_sum(a.path))
        return 0
    if a.cmd == "ledger":
        return ledger(a)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
