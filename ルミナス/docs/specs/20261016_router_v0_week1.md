# 20261016_router_v0_week1

## 目的（1〜3行）
振り分け役 v0 の 1 週目（提案 `docs/proposals/20261015-router-v0.md`「最初の 1 週間」）: **利用者に AI も区分も指定させない**ための配管と安全装置だけを作る。(1) 送信直前の区分の自動判定と、区分 C への強制引き上げ・即停止（外部へ何も送らない）。(2) 名簿の「法域」「機械用の役割キー」「停止」を読んで候補を並べ、停止中の国・ベンダーを飛ばして最大 2 回まで試す振り分け。(3) 1 行の実績記録。賢い振り分け（種類の分類・並び替えの計算）は作らない。

## 触ってよいファイル
<!-- ALLOWED -->
orch/classify.py
orch/router.py
orch/roster.py
orch/gemini.py
orch/fugu.py
tests/test_classify.py
tests/test_router.py
tests/test_roster.py
tests/conftest.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで。`ORCH_DATA_DIR`・`ORCH_LOG_DIR` を一時ディレクトリに）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない（名簿の新しい項目は人が足す。テストは一時ディレクトリの名簿。**名簿に新しい項目が無くても動く**＝後方互換）
- 分類に外部 AI を使わない（区分の判定は規則だけ。判定できなければ C）

## 背景
- 区分: A＝公開可／B＝非公開／C＝鍵・個人情報・利用者データ（どこにも送らない）。合成は最も重いもの。区分の無い部分は C（`docs/baseline/00-sotai-map.md` §3）。
- ゲート `orch/gate.py` は `(本文, 区分)` の組を受け取り、区分が None・C・名簿の `max_data_class` 超なら拒否する。振り分け役はゲートの**前**に置き、ゲートの既定（拒否）は変えない。
- 名簿の行に足す予定の項目（人が足す。無ければ既定値）: `role_key`（英小文字とハイフン。例 `drafter`・`measure`）、`jurisdiction`（ISO 3166-1 alpha-2。例 `US`・`JP`）、`stopped`（真偽。既定 false）。名簿の先頭に任意の `stops`: `{"jurisdictions": ["CN"], "providers": ["xxx"]}`（一括停止。無ければ空）。
- 学習型のルーターは分類に引きずられ、脱獄の試みを弱いモデルへ送る（EACL 2026、査読）。区分 C の判定は学習させず決まった規則で行う。
- Python 3.9 で動くこと。失敗しても本流を止めない（不変条件 4）。ただし**区分 C は止める側**（fail-closed）。

## 変更
1. **`orch/classify.py`（区分の自動判定・規則だけ）**
   - `classify(text: str, origin: Optional[str] = None) -> Tuple[str, List[str]]`: 区分（"A"/"B"/"C"）と理由の短い語の一覧を返す。
   - 初期値は `origin` で決める: `"public"`→A、`"private"`→B、None・その他→C（出どころが分からなければ C）。
   - 強制引き上げ（どの初期値でも C にする。理由の語は固定の短い英語）: 鍵の形（`config._GENERIC_SECRET` と同じパターンに加え、`[A-Za-z0-9_-]{32,}` の英数字の連なり・`-----BEGIN`・`xox[abp]-`・`ghp_`・`AKIA[0-9A-Z]{16}`）→`key_shape`／メールアドレス→`email`／電話番号（国内の `0\d{1,4}-?\d{1,4}-?\d{3,4}`、国際の `\+\d{6,15}`。数字 10〜11 桁の連なりも）→`phone`／`.env`・`settings.local.json`・`_非公開`・ホームディレクトリの絶対パス（`/Users/`・`/home/`・`C:\\Users\\`）→`private_path`／`config.SECRET_ENV_NAMES` の名前が `=` や `:` を伴って出る→`secret_name`／1 行の中の文字の乱雑さ（シャノンエントロピーが 4.5 ビット超かつ長さ 24 以上の空白を含まない連なり）→`entropy`。
   - `redact_for_log(text) -> str`: 記録用。`config.redact` を通したうえで、メール・電話・鍵の形を `[C]` に置き換える（本文は記録しないので、理由と長さだけ記録するのが基本）。
   - 日本語の全角数字・全角ハイフンは半角に正規化してから判定する（`unicodedata.normalize("NFKC")`）。
2. **`orch/roster.py`**: `active()` を `role_key` 優先にする（`role_key` があればそれで、無ければ従来の `role` で照合。gate_followups の 1 と同じ）。新関数 `candidates(roster, role_key_or_role) -> List[entry]`: 役割に合う行を「state が adopted → trial の順、同じなら名簿の順」で返し、`stopped: true`・`stops.jurisdictions` に `jurisdiction` が入る・`stops.providers` に `provider` が入る行を**除く**。除いた行とその理由（`stopped`・`jurisdiction_stopped`・`provider_stopped`）も返せるよう、`(candidates, skipped)` の組を返す関数 `candidates_with_skips` も用意（`candidates` はその先頭だけ）。
3. **`orch/router.py`（規則だけの振り分け）**
   - `route(prompt: str, *, role: str, origin: Optional[str] = None, purpose: str = "", max_tries: int = 2, timeout: float = 120) -> RouteResult`。`RouteResult` は rc・reason・text・data_class・reasons・entry_id・tries（各試行の entry_id・rc・reason・sec・usd）・sec。
   - 順番: ① 全体停止なら `GlobalHalt`。② `classify(prompt, origin)` → **C なら外部へ何も送らず** rc=4 `data_class_c`（理由の語つき）で返す（長さの測定も候補の列挙もしない）。③ `roster.candidates_with_skips` で候補。候補が無ければ rc=2 `no_candidates`。④ 先頭から順に、その行の `channel` に応じたアダプタを呼ぶ: provider `google`→`gemini.generate(prompt, data_class=区分, entry_id=行の id, purpose=..., timeout=...)`、provider `sakana`→`fugu.generate(...)`。それ以外の provider は飛ばす（`unsupported_provider`）。**最大 `max_tries` 行まで**。rc=0 なら終了。rc=3 で理由が「安全フィルタ」なら**次へ回さず**止める（rc=3 のまま返す）。rc=2・その他の rc=3 は次の候補へ。⑤ 全部失敗なら最後の rc と理由。
   - 1 行の記録 `data/router_log.jsonl`（追記・排他ロック・失敗で本流を止めない）: ts・purpose・role・data_class・reasons・prompt_chars・tries（entry_id・rc・reason・sec・usd）・final_rc・final_entry・total_sec・skipped（除いた行と理由）。**本文・鍵は書かない**。
   - CLI: `python3 -m orch.router run --role drafter [--origin public|private] [--purpose 用途] [--max-tries 2] < prompt.txt`。rc=0 なら本文を標準出力へ、標準エラーに 1 行（`router: entry=… class=… tries=… sec=…`）。終了コード = rc（全体停止は `config.HALT_EXIT_CODE`、C は 4）。`python3 -m orch.router check`: 名簿の役割ごとの候補の並びと、除外された行を表示（通信しない）。
   - **`gemini.generate`・`fugu.generate` は変更しない**のが望ましいが、`entry_id` で選ぶ経路が無ければ足す（gemini は既にある。fugu は `entry_id` 引数がある）。アダプタの中のゲートはそのまま通る（二重の安全装置）。
4. **`tests/conftest.py`**: 新しい環境変数があれば FLAG_VARS に足す（無ければ変更なし）。

## テスト
- classify: 模擬の鍵（Gemini の `AIza…` 形・`sk-…`・`AKIA…`・PEM の見出し）・電話番号（`090-1234-5678`・`０９０１２３４５６７８`・`+81901234567`）・メール・`.env`・ホームの絶対パス・`GEMINI_API_KEY=`・乱雑な 32 文字 → それぞれ **10 件が 10 件とも C** になり理由が付く／`origin="public"` の普通の日本語の依頼は A／`origin` 無しは C／`origin="private"` は B／全角のみの電話番号も C
- roster: `role_key` で選べる・無ければ `role`／`stopped`・`stops.jurisdictions`・`stops.providers` で除外され理由が返る／並びが adopted→trial→名簿順
- router（requests はモック、名簿は一時ディレクトリに google と sakana の 2 行以上）: C は通信ゼロで rc=4／1 番目が 500 なら 2 番目で成功し tries が 2 件／`max_tries=2` で 3 番目は呼ばれない／安全フィルタは次へ回さず rc=3／法域を停止すると残りの候補で成功し skipped に理由／候補ゼロは rc=2／全体停止は GlobalHalt／記録の 1 行に本文が無く、必要な項目がある／CLI の終了コード（0・2・3・4・HALT）と `check` の表示
- 既存の試験がすべて通ること

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点（名簿に足すべき `role_key`・`jurisdiction` の値を行ごとに書く）
