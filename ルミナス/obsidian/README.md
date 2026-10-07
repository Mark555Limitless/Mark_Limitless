# obsidian — Obsidian vault へ同期するノート

- `ルミナス.md`: ハブノート。目的・現在地・リンク集。セッション終了時に「最新」節を更新する
- 同期: `scripts/sync-obsidian.sh` が、`obsidian/*.md`・`digest/*.md`・`CHARTER.md`・`ROUTINE.md` を
  `$LUMINOUS_OBSIDIAN_DIR/ルミナス/` に複製する（SessionEnd hook から呼ばれる。変数が無ければ何もしない）
- vault の場所は `.claude/settings.local.json`（git 管理外）の `env.LUMINOUS_OBSIDIAN_DIR` に書く
