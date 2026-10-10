# 20261010_mac_bash32_tests

## 目的
Mac（/bin/bash 3.2.57・APFS・macOS の pty）で pytest 21 件が落ちる原因 4 種を直し、Phase 0 の門（Mac で全件通る）を通す。うち 1 種（bash 3.2 の変数展開）は試験だけでなく Mark の端末（UTF-8 ロケール）での実運用でも落ちる本物の不具合。

## 触ってよいファイル
<!-- ALLOWED -->
tools/_codex_common.sh
tools/codex_impl.sh
tools/codex_opinion.sh
tools/luminous_halt.sh
scripts/sync-obsidian.sh
.claude/hooks/log-model-switch.sh
.claude/hooks/restore-charter.sh
.claude/hooks/session-end.sh
tests/test_tools.py
tests/test_mac_compat.py
<!-- /ALLOWED -->

※ `.claude/hooks/` と `scripts/sync-obsidian.sh` は保護ファイル。適用（コミット）前に Mark の確認を取る。

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出し・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- 守りを弱める変更（判定の正規表現・終了コード・hooks の止める条件は変えない。変えるのは文字列の展開の書き方と試験の前提だけ）

## 背景（現象・再現手順）
2026-10-10 に Mac で `.venv/bin/python -m pytest tests -q` → 187 passed・21 failed（Linux では 208 passed）。test-hooks.sh は 112/112（試験側の 1 行を司令塔が修正済み）。

(a) 18 件 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xef`。実体は子プロセスの stderr `tools/codex_impl.sh: line 107: RC\xef: unbound variable`。
    bash 3.2 は UTF-8 ロケール（`LC_ALL=en_US.UTF-8`・`ja_JP.UTF-8`・Python が子へ渡す `LC_CTYPE=C.UTF-8`）で、`$RC）` のように変数名の直後に非 ASCII 文字が続くと高位バイトを変数名に含めてしまう。`set -u` の脚本は「unbound variable」で落ち、`set -u` が無い脚本は値と直後の 1 文字が黙って消える。`LC_ALL=C` では再現しない。`${RC}` と波括弧で囲めば直る（再現: `LC_ALL=ja_JP.UTF-8 /bin/bash -c 'set -u; RC=1; echo "rc=$RC）"'`）。
    該当 20 か所（2026-10-10 時点の行番号）:
    - tools/_codex_common.sh:73（`$pid）`）
    - tools/codex_impl.sh:107（`$RC）`）、161（`$QDIR（`）、173（`$RC）`）
    - tools/codex_opinion.sh:83（`$RC）`）
    - tools/luminous_halt.sh:58・59・61・80・82（`$pid）`）、91（`$TERM_PID）`）、98・115・148（`$HALT）`）
    - scripts/sync-obsidian.sh:26（`$DEST（`・`$n 件` は半角スペースがあるので対象外）
    - .claude/hooks/log-model-switch.sh:14・22（`$TO）`）
    - .claude/hooks/restore-charter.sh:18（`$SID）`）、66（`$CHG）`）
    - .claude/hooks/session-end.sh:10（`$SKIP・`）
    機械で探す: `perl -ne 'use bytes; print "$ARGV:$.: $_" if /\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]/; close ARGV if eof' tools/*.sh scripts/*.sh .claude/hooks/*.sh .githooks/*`
(b) 1 件 `test_halt_wrapper_launched_from_parent_dir_detects_erased_marker_without_term`: 7 == 3 で失敗。Mac では `luminous_halt.sh on` が印に `chflags uchg` を付けるため、偽 Codex（conftest/test_tools.py の `halt_eraser` モード）の `rm -f data/.luminous_halt` が印を消せず、ラッパーは「全体停止中のため止めました」で 7 を返す。守りが Linux より強く効いている。(a) を直すと `test_halt_eraser_codex_deleting_marker_is_violation_and_marker_recreated`・`test_halt_eraser_env_mismatch_falls_back_to_recreate_by_halt_script` も同じ理由で落ちる見込み。
(c) 1 件 `test_scope_check_git_name_is_case_insensitive`: APFS（大文字小文字を区別しない）では `GIT/`・`Git/`・`gIt/` が同じフォルダになり `.Git` の mkdir が FileExistsError。
(d) 1 件 `test_luminous_halt_off_refused_while_codex_running`: `run_tty` が 0.3 秒待ってから master へ書くが、`off` は Codex 実行中なら stdin を読まずに 2 で終わるので、macOS の pty では slave が閉じた後の write が `OSError: [Errno 5] Input/output error`（Linux は緩衝する）。

## 変更
1. (a) 上記 20 か所の変数参照を `${VAR}` に変える（出力の文言・終了コードは変えない）。
2. (a) 再発防止の試験 `tests/test_mac_compat.py` を新設: `tools/*.sh`・`scripts/*.sh`・`.claude/hooks/*.sh`・`.githooks/*` を bytes で読み、正規表現 `\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]` に当たる行が 0 件であることを確かめる（当たった行をメッセージに出す）。あわせて `/bin/bash` が存在する環境では `LC_ALL=ja_JP.UTF-8 /bin/bash -c 'set -u; X=1; echo "${X}）"'` が 0 で終わり出力が `1）` であることを確かめる（bash 3.2 でも波括弧なら通ることの実測）。
3. (b) `tests/test_tools.py` の偽 Codex `halt_eraser` モードで、印を消す前に `chflags nouchg data/.luminous_halt 2>/dev/null || true` を入れる（trap 側とループ側の両方。Linux では chflags が無く無視される）。「印を消す Codex は変更禁止属性も外す」という最悪の前提に試験を合わせる。Darwin で `rm` が失敗した場合の分岐は足さない。
4. (c) `test_scope_check_git_name_is_case_insensitive` の親フォルダを名前ごとに別にする（例: `tmp_path / f"case{i}"`）。`find_git` と `snapshot` の期待値は変えない。
5. (d) `run_tty` の `os.write(master, …)` を `try/except OSError` で囲み、`errno.EIO` のときだけ握りつぶして続ける（他の errno は再送出）。その後の `communicate` と戻り値の扱いは変えない。

## テスト
- 陽性: Mac（/bin/bash 3.2・APFS）で `.venv/bin/python -m pytest tests -q` が全件通る。`bash scripts/test-hooks.sh` が 112/112 のまま
- 陰性: `tests/test_mac_compat.py` は、わざと `$X）` を含む一時ファイルを対象にすれば落ちることを、試験内の小さな自己検査（対象リストを差し替えた関数呼び出し）で確かめる
- 境界: `${RUNDIR#"$PROJ"/}` のような既に波括弧の参照は触らない。半角スペースが間にある `$n 件` も対象外

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告。Linux と Mac の両方で通る書き方）
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
