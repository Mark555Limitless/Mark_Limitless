#!/usr/bin/env python3
"""Jev（TypeSafe AI）を Verifier のゲートとして呼ぶ薄いアダプタ。

Jev は文章を生成せず、型付きの判定だけを返す（公開情報: Noul=はい/いいえの確率、Choice=選択肢と確率・信頼度、
Score=2〜10 段階の採点と確率・信頼度）。本スクリプトは「state（判定対象）＋質問」を送り、判定と閾値の結論を
state/jev/ に記録する。

API の形（コミュニティの実例と公式 SDK の README から。公式ドキュメント本文はクラウド環境から未読）:
  直接:        POST https://api.typesafe.ai/v1/systemone   model=jev-latest   Authorization: Bearer $TYPESAFE_API_KEY
  OpenRouter:  POST https://openrouter.ai/api/alpha/decisions  model=typesafe/jev-1.13  Authorization: Bearer $OPENROUTER_API_KEY
  リクエスト:  {"model": ..., "state": {...}, "questions": {name: {"type": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}}}
  レスポンス:  {"model": ..., "answers": {name: {"type": "noul", "noul": 0.99}, ...}, "usage": {...}}
公式 SDK（pip install typesafe-sdk / npm install @typesafe-ai/sdk）が入っていればそちらを優先してよい。
環境変数:
  TYPESAFE_API_KEY     直接呼ぶときに必須。値は表示しない
  JEV_PROVIDER         typesafe（既定）| openrouter
  OPENROUTER_API_KEY   JEV_PROVIDER=openrouter のとき必須
  JEV_MODEL            既定: typesafe→jev-latest / openrouter→typesafe/jev-1.13
  TYPESAFE_API_BASE / TYPESAFE_EVAL_PATH  直接呼ぶときのホスト・パス（既定 https://api.typesafe.ai, /v1/systemone）

使い方:
  python3 scripts/jev_gate.py --state-file draft.md --questions questions.json [--threshold 0.6]
questions.json の例（ルミナス標準の 4 問）:
  {
    "source_tier":   {"type": "choice", "question": "この記事の主たる出典の信頼度は？", "options": ["1 一次情報", "2 査読・第三者評価", "3 技術メディア・通信社", "4 個人SNS・GitHub Issue", "5 動画・個人ブログ"]},
    "self_reported": {"type": "noul",   "question": "性能の主張は発表元の自己申告のみで、独立した第三者の裏付けが無いか？"},
    "go_nogo":       {"type": "score",  "question": "このまま公開してよい度合い", "levels": ["公開不可: 出典不明か矛盾あり", "保留: 裏取りが必要", "条件付き: 自己申告と明記すれば可", "公開可: 一次情報で確認済み"]},
    "escalate":      {"type": "noul",   "question": "判断に重大な矛盾・極端な主張が含まれ、上位モデルの裁定が必要か？"}
  }
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-file", required=True, help="判定対象のテキストファイル")
    ap.add_argument("--questions", required=True, help="質問定義 JSON")
    ap.add_argument("--threshold", type=float, default=0.6, help="noul の『はい』とみなす確率の閾値")
    ap.add_argument("--dry-run", action="store_true", help="送信せずリクエストを表示（鍵は不要）")
    a = ap.parse_args()

    state = Path(a.state_file).read_text(encoding="utf-8")
    questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    provider = os.getenv("JEV_PROVIDER", "typesafe")
    if provider == "openrouter":
        url = "https://openrouter.ai/api/alpha/decisions"
        model = os.getenv("JEV_MODEL", "typesafe/jev-1.13")
        key_name = "OPENROUTER_API_KEY"
    else:
        url = os.getenv("TYPESAFE_API_BASE", "https://api.typesafe.ai").rstrip("/") + os.getenv("TYPESAFE_EVAL_PATH", "/v1/systemone")
        model = os.getenv("JEV_MODEL", "jev-latest")
        key_name = "TYPESAFE_API_KEY"
    body = {"model": model, "state": {"document": state}, "questions": questions}

    if a.dry_run:
        print(json.dumps({"provider": provider, "endpoint": url, "model": model,
                          "body_preview": {"state_chars": len(state), "questions": list(questions)}}, ensure_ascii=False, indent=2))
        return 0

    key = os.getenv(key_name)
    if not key:
        print(f"{key_name} が未設定です。鍵は環境変数で渡してください（チャットやファイルに貼らない）。", file=sys.stderr)
        return 4
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Jev API エラー: HTTP {e.code}（ホスト・パス・ヘッダ名を公式ドキュメントで確認してください）", file=sys.stderr)
        return 5
    except Exception as e:  # ネットワーク遮断など
        print(f"Jev API に到達できません: {type(e).__name__}", file=sys.stderr)
        return 6

    # 結論（閾値ルール）。answers[name] の形: noul→{"type":"noul","noul":p}。choice/score は raw を保持しつつ要約を試みる
    answers = result.get("answers", {}) if isinstance(result, dict) else {}
    verdict = {}
    for name, q in questions.items():
        ans = answers.get(name)
        if not isinstance(ans, dict):
            verdict[name] = ans
        elif q.get("type") == "noul" and isinstance(ans.get("noul"), (int, float)):
            verdict[name] = {"yes": ans["noul"] >= a.threshold, "p": ans["noul"]}
        else:
            summary = {k: v for k, v in ans.items() if k in ("type", "choice", "score", "confidence", "selected", "probabilities")}
            verdict[name] = summary or ans
    usage = result.get("usage") if isinstance(result, dict) else None
    log_dir = ROOT / "state" / "jev"; log_dir.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "provider": provider, "model": model,
           "state_file": a.state_file, "threshold": a.threshold, "usage": usage, "raw": result, "verdict": verdict}
    (log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
