# 20261008_trial1_version_info

## 目的
段階1の試験1。Codex の流れ（指示書 → 実装 → ALLOWED 検査）が動くことを確かめる。

## 触ってよいファイル
<!-- ALLOWED -->
orch/__init__.py
<!-- /ALLOWED -->

## 禁止
- git commit・.env／data／logs の読み書き・実際の外部 API 呼び出し・上記以外のファイル

## 背景
`orch/__init__.py` には `__version__ = "0.1.0"` がある。比較しやすい版数のタプルが欲しい。

## 変更
1. `orch/__init__.py` に `VERSION_INFO = (0, 1, 0)` を足す。`__version__` と同じ値にする

## テスト
- 追加なし（既存の `.venv/bin/python -m pytest tests -q` が全件通ること）

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
