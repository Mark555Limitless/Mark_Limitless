"""点検: Codex・Gemini・Jev の状態を1行ずつ出す。セッション開始時のフックで毎回表示する（無人実行では表示しない）。

固定コマンド: python3 -m orch.health [--quiet] [--no-net]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import List, Optional

from . import config, gemini, jev, usage

CODEX_APP_PATH = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"


def codex_bin() -> Optional[str]:
    """新しい場所 → 古い場所（CODEX_OLD_BIN）→ PATH の順に探す。CODEX_BIN があれば最優先。"""
    for cand in (config.env("CODEX_BIN"), CODEX_APP_PATH, config.env("CODEX_OLD_BIN")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("codex")


def codex_line() -> str:
    b = codex_bin()
    stop = "停止中" if config.disabled("codex") else "稼働"
    running = (config.data_dir() / "codex_runs" / ".lock").exists()
    return (f"codex: 本体={'あり' if b else 'なし'} {stop}{' 実行中' if running else ''} "
            f"本日 {usage.today_calls('codex')}回")


def lines(net: bool = True) -> List[str]:
    out: List[str] = []
    if config.global_halt():   # 例外は出さず、表示だけ（docs/specs/20261008_global_halt.md）
        out.append("!!! 全体停止中（data/.luminous_halt）。外部AI・Codex・判断層は動きません。解除は Mark が端末で: bash tools/luminous_halt.sh off")
    out.append(codex_line())
    out.append(gemini.check_status(net=net, net_timeout=5)[1])
    out.append(jev.status_line())
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="orch.health")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-net", action="store_true")
    a = ap.parse_args(argv)
    if not a.quiet:
        print("=== ルミナス 外部AIの点検 ===")
    for line in lines(net=not a.no_net):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
