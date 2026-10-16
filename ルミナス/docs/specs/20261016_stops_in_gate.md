# 20261016_stops_in_gate

## 目的（1〜3行）
名簿の停止条件（行の `stopped: true`、名簿の先頭の `stops.jurisdictions`・`stops.providers`）を、振り分け役だけでなく**すべての送信経路**で効かせる。今は `orch/router.py` の候補の列挙でしか除外されず、Gemini・Jev・Fugu を直接呼ぶ経路（`roster.active()`・`entry_id` 指定）とゲート `orch/gate.py` は停止中の行をそのまま通す（自動のセキュリティ審査の指摘 2026-10-16: 停止スイッチの迂回）。

## 触ってよいファイル
<!-- ALLOWED -->
orch/gate.py
orch/roster.py
tests/test_gate.py
tests/test_roster.py
tests/test_gemini.py
tests/test_jev.py
tests/test_fugu.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない
- ゲートの既定（区分が無ければ拒否・名簿に無い宛先は拒否・上限の予約と精算）を変えない。`orch/router.py`・`orch/classify.py` は触らない

## 背景
- `orch/roster.py` に `_stops(roster)`（法域は大文字に正規化・提供元はそのまま）と `candidates_with_skips(roster, role)`（stopped → jurisdiction_stopped → provider_stopped の順で除外の理由を付ける）がある。`active(roster, role)` は `_matches_role` で絞って adopted → trial で 1 行を選ぶが、停止条件を見ない。
- `orch/gate.py` の `_entry(roster, entry_id)` は `state` が adopted/trial でなければ `entry_inactive`、無ければ `unknown_entry`。`check_destination`・`check_send`・`gate()` はこれを通る。`load_roster` は `_object`（重複キーの拒否）と `_json_float` で読む。
- `GateDenied.reason` は固定の短い英語（記録と試験で使う）。

## 変更
1. **`orch/roster.py`**: 停止判定を 1 か所にまとめる関数 `stop_reason(roster, entry) -> Optional[str]`（`"stopped"`／`"jurisdiction_stopped"`／`"provider_stopped"`／None。`candidates_with_skips` はこれを使う）。`active()` は、役割に合う adopted/trial の行のうち**停止中の行を除いて**選ぶ（除いた結果、候補が無ければ従来どおり `ValueError`。あいまい判定〔同じ state が 2 行〕は停止中を除いた後で行う）。`plan_switch` の切替先が停止中なら `ValueError("invalid_switch")`。
2. **`orch/gate.py`**: `_entry()` で、state の検査の後に `roster.stop_reason(roster, entry)`（循環 import を避けるため、判定の実装は `gate.py` 側に小さく持ち、`roster.py` がそれを呼ぶ形でもよい。どちらか 1 か所）を見て、停止中なら `GateDenied("entry_stopped")`。これで `check_destination`・`check_send`・`gate()`・`Budget._reserve` の前にすべて止まる（`entry_id` を直接指定する経路＝Gemini `--entry`・Fugu も止まる）。`stops` の形が不正（辞書でない・配列でない・文字列でない要素）なら、その部分を無視せず **`GateDenied("invalid_stops")`**（fail-closed。名簿の読み込み `load_roster` の検証に加える）。
3. 試験: 
   - gate: `stopped: true` の行／`stops.jurisdictions` に法域が入る行／`stops.providers` に提供元が入る行 → `gate()` が `entry_stopped`（予約は作られない・台帳に行が増えない）。法域の大文字小文字（`us` と `US`）が一致する。`stops` が壊れている（文字列・数値・要素が数値）→ `invalid_stops`。停止条件が無い名簿は従来どおり通る
   - roster: `active()` が停止中の adopted を飛ばして trial を選ぶ／全部停止なら ValueError／`plan_switch` の切替先が停止中なら invalid_switch
   - gemini・jev・fugu: 停止中の行では通信せず rc=2（理由 `entry_stopped`）。Gemini の `--entry` 指定でも同じ
   - 既存の試験がすべて通ること。Python 3.9 互換

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
