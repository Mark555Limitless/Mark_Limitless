# ADR 2026-10-10: クラウドの司令塔と ChatGPT（Codex）のつなぎ方

- 背景: Mark の依頼で Codex とブレーンストーミングしたいが、クラウドの司令塔は Codex に直接つながらない（Codex が未導入、ChatGPT のサイトとログインはプロキシで 403）。OpenAI の API（api.openai.com）にはつながる（鍵なしで 401）。AI NEWS Select が Codex と常時連携できるのは、Mark の Mac に Codex が入り ChatGPT でログイン済みだから
- 選択肢: ① OpenAI の API（従量課金・ChatGPT の月額とは別）／② Mac 経由（Mac のルミナスのフォルダで Claude Code をリモート操作ありで起動し、`tools/codex_opinion.sh` で Codex に聞く。追加費用なし）／③ クラウドに Codex を入れて ChatGPT でログイン（ログインの情報がクラウドに残る・ログインの画面が遮断）
- 決定（Mark、2026-10-10）: 「両方」。ただし **② を優先し、問題があるときは ① を併用**
- 理由: ② は今のログインを使い追加費用が無い。① はクラウドから常時使えるが費用がかかる
- 影響: ② のパケット `docs/astra-packets/20261010-brainstorm-r1.md` を用意し、公開可の一覧に資料を足した。① は予備の指示書 `docs/specs/20261010_openai_api.md`（未実装。上限の金額は Mark が決める）。① を使い始めるときは、新しい有料サービスの開始として改めて Mark の確認を受ける
