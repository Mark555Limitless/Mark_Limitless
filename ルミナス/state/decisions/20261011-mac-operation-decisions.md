# ADR 2026-10-11: Mac 運用の決定 4 点（監査の残りの反証から）

元: Mac 切替の監査の残り 39 件の反証（`docs/mac-switch-audit.md`）で出た、Mark の判断が要る点。Mark がチャットで決めた（原文「1はい 2はい 3はい 4見送り」）。

## 1. 正本の場所 → GitHub の写し（Mac の clone）の `ルミナス/` を正本にする
- 背景: Mac の「正本フォルダ」は空で git 管理外だった。Mac の司令塔は clone の `ルミナス/` で動いており、hooks・git フック・pull/push はそこでしか効かない
- 影響: Claude Code は clone の `ルミナス/` で起動する（デスクトップアプリは Project folder にそれを指定。worktree は使わない）。空の正本フォルダは不要。CLAUDE.md:4 と ROUTINE §6 の記述を直す（保護ファイル。差分を Mark に見せてから適用）
- 注意: ルミナス単独のリポジトリにはしない（祖先に .git があると hooks の入れ子 .git の検知が誤作動する）。親リポジトリ Mark_Limitless の一部のまま使う

## 2. `package-lock.json` → コミットする
- 背景: Mac の `scripts/setup.sh`（npm install）が作り、保護ファイルなのに未追跡のため、起動のたびに警告が出続ける
- 実施: Mac の司令塔が中身（docx が 9.x、resolved がすべて https://registry.npmjs.org/、integrity がそろう）を確かめてコミット・push する。クラウドでは作らない（作って push すると、Mac の未追跡のファイルとぶつかり pull が止まる）

## 3. 記録ファイルの衝突 → 両方を残す自動マージ（merge=union）にする
- 対象: `HANDOVER.md`・`digest/*.md`・`state/escalations.log`（`.gitattributes` を新設。組み込みの union ドライバなので外部コマンドは動かない）
- 副作用: 同じ行を両方が書き換えたときは、新旧の両方が残る（受け入れる）
- あわせて: `.gitattributes` を保護の対象に足す（-diff や binary を書かれると鍵の検査が中身を見なくなるため）。ROUTINE §3 に「記録を書く前に pull、書いたらすぐ push」を足す（保護ファイル。差分を見せてから）

## 4. pull で入った記録で Stop ゲートが通る穴 → 見送り
- 理由: Stop ゲートは記録の催促で、安全の境界ではない。塞ぐには git フック（post-merge・post-checkout）を足し、pull のたびにスクリプトが走る運用の変更になる
- 残る点: Mac で pull した直後は、そのセッションで記録を書かなくても終了できることがある。司令塔は自分で書く（ROUTINE §3）
