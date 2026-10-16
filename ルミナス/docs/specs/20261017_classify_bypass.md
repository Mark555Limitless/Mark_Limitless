# 20261017_classify_bypass

## 目的（1〜3行）
区分判定 `orch/classify.py` の、自動のセキュリティ審査が見つけた**迂回の穴 2 つ**を塞ぐ。(1) 40 桁の 16 進を一律に「コミットハッシュ」として鍵の形から除外しているため、16 進形式の鍵・トークン（40 桁）が A で外へ出る。(2) URL を乱雑さの判定から外しているため、URL のパスやクエリに埋めた鍵が A で外へ出る。方針は安全側（fail-closed）。

## 触ってよいファイル
<!-- ALLOWED -->
orch/classify.py
tests/test_classify.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出しやネットワーク通信・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- 分類に外部 AI を使わない（規則だけ。判定できなければ C）

## 変更
1. **40 桁の 16 進**: 除外するのは、直前（空白を挟んでよい）に `commit`・`sha`・`sha1`・`rev`・`hash`・`ref` の語（大文字小文字を区別しない）があるとき、または git の URL のパス（`/commit/`・`/commits/`・`/tree/`・`/blob/`・`/compare/` の直後）にあるときだけ。それ以外の 40 桁の 16 進（裸・`token=` の後ろ・文の途中）は `key_shape` で C。`redact_for_log` も同じ規則で伏せる（除外の文脈にあるものは残してよい）。
2. **URL**: 乱雑さと鍵の形の検査から URL 全体を外さない。外すのは**スキームとホスト**（`https://example.test`）だけにし、**パスの各要素**（`/` 区切り）と**クエリの各値**（`&` と `=` 区切り、`%` の復号はしない）に、乱雑さの判定（`[A-Za-z0-9+/=_.\-]{24,}`・4.5 ビット超）と鍵の形の検査を掛ける。普通の URL（`https://www.example.com/news/2026/10/16/internationalization-and-localization-guidelines`・`https://example.test/?page=2&sort=asc`）は A のまま。
3. 既存の規則（メール・電話・パスワードの形・カード番号・個人番号・クエリの鍵の名前）は変えない。

## テスト（追加）
- C: 裸の 40 桁 16 進／`token=` + 40 桁 16 進／`https://x.test/a/` + 乱雑な 32 字／`https://x.test/dl?f=` + 乱雑な 32 字／`https://x.test/` + 40 桁 16 進（git の文脈でない）
- A: `commit ` + 40 桁 16 進／`sha: ` + 40 桁 16 進／`https://github.com/o/r/commit/` + 40 桁 16 進／`https://github.com/o/r/blob/` + 40 桁 16 進 + `/README.md`／普通の URL 2 つ（上）／30 字以上の普通の日本語の依頼
- `redact_for_log`: 裸の 40 桁 16 進は `[C]` に、`commit ` の後ろは残る
- 既存の試験がすべて通ること。Python 3.9 互換

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
