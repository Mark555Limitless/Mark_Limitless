# digest — セッション要約の置き場

1 日 1 ファイル（`YYYY-MM-DD.md`）。同じ日に複数セッションがあれば追記する。
Stop hook（`.claude/hooks/stop-gate.sh`）は、セッション開始後に今日の digest が更新されていないと停止をブロックする。

## 1 件の形式

```
## HH:MM 〜（司令塔モデル）
- やったこと: 3 行以内
- 判断: ADR へのリンク or 1 行
- 数値: コスト・エスカレーション・レビュー指摘数など実測のみ
- 未解決:
- 次の一手:
```

Obsidian へは `scripts/sync-obsidian.sh` がそのまま複製する（ファイル名は同じ）。
