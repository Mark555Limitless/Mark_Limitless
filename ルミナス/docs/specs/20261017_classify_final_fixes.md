# 20261017_classify_final_fixes

## 目的（1〜3行）
振り分け役 v0 の最終審査（REJECT）の指摘 7 件を直す。重大: URL の「ホスト」の範囲が広すぎて、URL の後ろに JSON・CSV・`;` で続く鍵が検査から外れる。中: 60 桁の上限で前に数字を足すと逃げる／英字の長い連なりで 2 乗の時間／一括停止の設定の型の誤りが fail-open／URL とコードの偽陽性・電話番号の上限なし。軽: ゼロ幅空白・記録の非公開パス。方針は安全側（fail-closed）だが、普通の URL・コード・日付は A にする。

## 触ってよいファイル
<!-- ALLOWED -->
orch/classify.py
orch/roster.py
orch/router.py
tests/test_classify.py
tests/test_roster.py
tests/test_router.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出しやネットワーク通信・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- 分類に外部 AI を使わない（規則だけ。判定できなければ C）。`config/roster.json` を変更しない

## 変更
1. **（重 1）URL の分割**（`orch/classify.py` `_URL`・`_URL_HEAD`・`_inspection_text`）: `_URL` の区切りに `" ' , ; | < > ( ) [ ] { }` と空白・全角文字を含める（URL は次の区切りで終わる）。ホストは `[A-Za-z0-9.-]+(?::[0-9]+)?`（IPv6 は `\[[0-9A-Fa-f:.]+\]`）に限る。**鍵の形の検査ではスキームだけを外し、ホスト名も検査に残す**（ホスト名に埋めた鍵も C）。乱雑さの判定でだけホストを外す。ユーザー情報（`user:token@`）は両方の検査に残す。試験: `{"url":"https://a.test","key":"sk-" + 32 字}`／`url,api_key\nhttps://a.test,sk-…`／`{"endpoint":"https://a.test","token":"<40 桁 16 進>"}`／`https://a.test;token=ZZZZ…`／`https://AIza…xxx.h.test/` → すべて C。普通の URL（arXiv・Python ドキュメント・`https://www.example.com/news/2026/10/16/internationalization-and-localization-guidelines`）は A。
2. **（中 2）数字の上限**: 60 桁の上限は「区切りの無い 1 つの連なり」にだけ掛け、60 桁を超える連なりは安全側で C（`long_number`）。区切りつきのグループの連なりは全部を窓で見る（グループ数に比例）。試験: `'\t'.join(['2222222']*9) + ' 4111111111111111'` → C（card_number）。
3. **（中 3）2 乗の時間**: `[A-Za-z][A-Za-z_]*-\d{4}`（`:24`）とメールのローカル部に、先頭だけから試す否定の後読み（`(?<![A-Za-z_])`・`(?<![A-Za-z0-9._%+-])`）を付ける。試験: 英字 2 万字・`'a'*20000+'@'`・`'a.'*4000+'@'+'a.'*1000` が各 0.5 秒以内。
4. **（中 4）一括停止の設定の型**（`orch/roster.py` `_stops`）: `stops` が dict でない、`jurisdictions`・`providers` が list でない、要素が文字列でない → `ValueError("invalid_roster")`（`candidates_with_skips`・`active` から上がる。router は `roster_unavailable` で止まる＝fail-closed）。提供元と法域は `strip().casefold()` でそろえて比べる（`"Google"` で `google` の行が止まる）。試験: 文字列の `jurisdictions`・dict でない `stops`・大文字の提供元名。
5. **（中 5）偽陽性**: (a) パスワードの形は `_inspection_text` で URL を分けてから当て、記号が `._()/:,-` だけの語は除く（`https://www.youtube.com/watch?v=dQw4w9WgXcQ`・Google Docs の URL・`amazon.co.jp/dp/B0C1234567`・`self.assertEqual(x,1)`・`MyClass.method(arg1)` は A）。(b) 電話番号は、区切りを除いた数字が 10〜11 桁（`+` 始まりは 10〜15 桁）**ちょうど**の部分範囲だけを電話とみなし、範囲の終わりが区切りか末尾であること（`2026-10-01 2026-10-31`・`version 1.0.0 2.0.0 3.0.0 4.0.0`・`10 20 30 40 50 60`・`売上は 10000000000 円`・13 桁の時刻は A。`090-1234-5678 9` は C のまま）。(c) **X（Twitter）などの投稿 URL の ID**（`/status/\d{15,20}`・`/statuses/`）は公開の識別子なので、その数字は電話・カード番号の判定から除く（司令塔の判断。URL 以外に裸で出る 19 桁は従来どおり）。`uuid 550e8400-e29b-41d4-a716-446655440000` は A（UUID の形 `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` は乱雑さと鍵の形から除く）。
6. **（軽 6）ゼロ幅文字**: `_normalize` で Unicode の区分 Cf（U+200B・U+200C・U+200D・U+FEFF など）を取り除いてから判定する。試験: `AIza` + U+200B + 32 字 → C。
7. **（軽 7）記録の非公開パス**: `redact_for_log` が `_PRIVATE`（`.env`・`/Users/`・`/home/`・`C:\Users\`・`_非公開` など）も `[C]` に伏せる。試験: purpose に `/Users/x/secret` を入れても記録に出ない（router の試験）。
8. 迂回の追加（審査で A だったもの）: `090/1234/5678`・`090_1234_5678`・`090,1234,5678` は区切りに `/ _ ,` も許して C。`a09012345678`（英字の直後）は C（境界は数字でないこと。英字は境界にしない）。`card4111111111111111`・`4111.1111.1111.1111`・`4111/…`・`4111_…`・改行区切りのカード番号も C（カード番号の区切りに `. / _ 改行` を許す）。

## テスト
- 上の各項の試験。既存の試験がすべて通ること（期待値を変える場合は理由をコメントに）。Python 3.9 互換。分類 1 回が 10 KB で 0.5 秒以内（既存の試験）・英字 2 万字で 0.5 秒以内（追加）

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
