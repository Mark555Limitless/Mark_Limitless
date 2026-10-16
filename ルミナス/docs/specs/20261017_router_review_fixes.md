# 20261017_router_review_fixes

## 目的（1〜3行）
振り分け役 v0 の 1 週目（指示書 `docs/specs/20261016_router_v0_week1.md`）の Opus 審査 REJECT の指摘を直す。とくに、**普通の日本語の依頼がほぼすべて区分 C になる**（乱雑さの判定が日本語の文を拾う）点と、名簿に `role_key` を足した途端に Gemini・Jev の直接呼び出しが止まる点。

## 触ってよいファイル
<!-- ALLOWED -->
orch/classify.py
orch/router.py
orch/roster.py
tests/test_classify.py
tests/test_router.py
tests/test_roster.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない。分類に外部 AI を使わない（規則だけ。判定できなければ C）
- 安全側の方針は変えない: 鍵・電話・メール・非公開のパスは C に**強制引き上げ**。直すのは「普通の文を C にしすぎる」偽陽性と「個人情報を逃す」偽陰性

## 変更
1. **（重 1）乱雑さの判定を ASCII の連なりに限る**（`orch/classify.py`）: 対象を `[A-Za-z0-9+/=_.\-]{24,}` の連なりだけにし、日本語（空白の無い文）を対象にしない。`https?://` で始まる部分は乱雑さの判定から除く（URL は A のまま。ただし URL の中に鍵の形〔`AIza…`・`sk-…`・`key=` に続く 20 字以上〕があれば `key_shape` で C）。エントロピーのしきい値（4.5 ビット・24 字）は据え置き。
2. **（中 2）日本語の役割名でも照合する**（`orch/roster.py` `_matches_role`）: `role_key` があれば `role_key == role` **または** `entry["role"] == role`。`gemini.ROLE`・`jev.ROLE`（日本語）での `active()` が、名簿に `role_key` を足した後も動くこと（試験: role_key のある行を日本語の役割名で選べる・role_key でも選べる・別の役割名では選べない）。
3. **（中 3）電話番号の判定**（`orch/classify.py`）: 前後に数字が続かない条件（`(?<!\d)` … `(?!\d)`）を付け、区切りに `-`・空白・`.` を許す。国内＝`0\d{1,4}[-\s.]?\d{1,4}[-\s.]?\d{3,4}`、国際＝`\+\d{1,3}[-\s.]?\d{1,4}[-\s.]?\d{1,4}[-\s.]?\d{3,4}`（`+81 90 1234 5678` を C に）。`20261016`・`12345678901円`・`ISBN 9784123456789`・`INV-0012-3456`・`2026/10/01-2026/10/31` は **C にしない**（日付・金額・識別子）。数字 10〜11 桁の連なりは、`0` で始まるときだけ電話番号とみなす。
4. **（中 4）`stopped` の値**（`orch/roster.py`）: 真偽値でなければ止める側（`"true"`・`1`・`"yes"` などは停止扱い。`False`・`None`・無しだけが停止でない）。`candidates_with_skips` の理由は `stopped` のまま。
5. **（軽 5）`.env` とメール**（`orch/classify.py`）: `.env` は語の境界で（`(?<![\w.])\.env(?:\.[\w.-]+)?(?![\w])`。`.envrc`・`.environment`・`process.env` は C にしない。`.env.local`・`.env.bak.20261011` は C）。メールは `react@18.3.1` のようなパッケージの版指定を除く（`@` の後ろにドットつきのドメインが必要で、ドメインの最初の字は英字: `[A-Za-z0-9._%+-]+@[A-Za-z][A-Za-z0-9-]*(\.[A-Za-z0-9-]+)+`）。
6. **（軽 6）全体停止の記録**（`orch/router.py`）: アダプタの中で `GlobalHalt` が上がったら、`router_log.jsonl` に `final_rc=HALT_EXIT_CODE`・理由 `global_halt` の 1 行を書いてから再送出する（記録の失敗で止めない）。
7. **（軽 7）CLI の標準入力**（`orch/router.py`）: 文字コードが壊れていれば rc=2 `invalid_input`（標準エラーに 1 行）。`sys.stdin.buffer.read().decode("utf-8", errors="strict")` を try で囲む。
8. **（軽 8）秘匿する環境変数の名前**（`orch/classify.py`）: 大文字小文字を区別せずに照合（`gemini_api_key=` も `secret_name`）。

## テスト（追加・修正）
- classify: 30 字以上の普通の日本語の依頼 3 文（会議の紹介文・住所の案内・予定の相談）と `https://www.example.com/news/2026/10/16/...` を含む文が origin=public で **A**／40 桁のコミットハッシュと `internationalization-and-localization-guidelines` は **A**（鍵の形に当てない: 鍵の形は `AIza`・`sk-`・`AKIA`・`ghp_`・`xox[abp]-`・PEM・`[A-Za-z0-9_-]{32,}` のうち**英字と数字の両方を含み、ハイフンだけの英単語の連なりでない**もの）／`+81 90 1234 5678`・`090 1234 5678`・`090.1234.5678`・`０９０−１２３４−５６７８` は **C**／`20261016`・`12345678901円`・`ISBN 9784123456789`・`INV-0012-3456`・`2026/10/01-2026/10/31` は **A**／`react@18.3.1` は A・`a.b@example.co.jp` は C／`.envrc`・`process.env.X` は A・`.env`・`.env.local` は C／`gemini_api_key=` は C
- roster: role_key のある行を日本語名でも role_key でも選べる／`stopped: "true"` が停止扱い
- router: 全体停止の 1 行が記録に残る／壊れた標準入力で rc=2
- 既存の試験がすべて通ること。Python 3.9 互換

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
