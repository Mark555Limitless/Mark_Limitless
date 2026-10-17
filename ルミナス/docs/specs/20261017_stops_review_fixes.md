# 20261017_stops_review_fixes

## 目的（1〜3行）
`docs/specs/20261016_stops_in_gate.md` の Opus 審査 REJECT の指摘 2 件を直す。(1) `active()` が停止中の行を除くようになったため、停止中の採用行から別の行へ切り替える `plan_switch` と前の行へ戻す `plan_rollback` が失敗する（停止スイッチを使った後の運用に差し支える）。(2) 名簿の行の `jurisdiction`・`provider` が文字列でないと一括停止をすり抜ける。

## 触ってよいファイル
<!-- ALLOWED -->
orch/roster.py
orch/gate.py
tests/test_roster.py
tests/test_gate.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出しやネットワーク通信・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない。ゲートの既定を変えない

## 変更
1. **（中）切替と巻き戻し**（`orch/roster.py`）: 停止を見ずに「今の行」を選ぶ内部関数 `_current(roster, role)`（変更前の `active` と同じ中身＝adopted → trial、あいまいなら ValueError）を作り、`plan_switch` の `old` と `plan_rollback` の `current` はそれを使う。切替先 `new` が停止中なら `invalid_switch`（今のまま）。巻き戻し先 `previous` が停止中なら `rollback_unavailable`。`active()`（実際の呼び出しに使う）は停止中を除いたまま。
2. **（低）型の検査**（`orch/roster.py` `stop_reason`・`orch/gate.py`）: 行の `jurisdiction`・`provider`・`stopped` が「無い・None・文字列（`stopped` は真偽値）」以外なら `ValueError("invalid_roster")`（ゲートでは `GateDenied("invalid_stops")`）。fail-closed。
3. 試験: 採用中の A が停止中・試用の B のとき B へ切り替えられる／停止中の採用行から停止していない前の行へ巻き戻せる／巻き戻し先が停止中なら rollback_unavailable／`"jurisdiction": ["US"]` の行は invalid_roster（ゲートでは invalid_stops）。既存の試験がすべて通ること。Python 3.9 互換

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
