"""Rule-only routing. Adapters retain their independent outbound gates."""
import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import config, fugu, gate, gemini, roster
from .classify import classify, redact_for_log


@dataclass
class RouteResult:
    rc: int
    reason: str
    text: str = ""
    data_class: str = "C"
    reasons: List[str] = field(default_factory=list)
    entry_id: str = ""
    tries: list = field(default_factory=list)
    sec: float = 0.0


def _load_roster():
    return gate.load_roster(config.env("ORCH_ROSTER") or config.ROOT / "config" / "roster.json")


def _log(result, purpose, role, prompt_chars, skipped):
    # Sanitize metadata too: callers and roster editors can supply secret-shaped values.
    def clean(value):
        if isinstance(value, str):
            return redact_for_log(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value
    try:
        row = clean(dict(ts=config.ts(), purpose=purpose, role=role,
                         data_class=result.data_class, reasons=result.reasons,
                         prompt_chars=prompt_chars, tries=result.tries,
                         final_rc=result.rc, final_entry=result.entry_id,
                         total_sec=result.sec, skipped=skipped))
        path = config.data_dir() / "router_log.jsonl"
        with config.file_lock(path.with_suffix(".lock")):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def route(prompt: str, *, role: str, origin: Optional[str] = None,
          purpose: str = "", max_tries: int = 2, timeout: float = 120) -> RouteResult:
    start = time.monotonic()
    if config.global_halt():
        raise config.GlobalHalt()
    # purpose は利用者の入力から来うるので、アダプタの台帳・ログに渡す前に伏せて短く切る（自動のセキュリティ審査の指摘 2026-10-17）
    purpose = redact_for_log(str(purpose or ""))[:80]
    label, reasons = classify(prompt, origin)
    result = RouteResult(4 if label == "C" else 2,
                         "data_class_c" if label == "C" else "no_candidates",
                         data_class=label, reasons=reasons)
    skipped = []

    def finish(chars):
        result.sec = time.monotonic() - start
        _log(result, purpose, role, chars, skipped)
        return result

    if label == "C":
        return finish(None)  # Do not measure the rejected input or enumerate candidates.
    if type(max_tries) is not int or max_tries < 1:
        result.reason = "invalid_max_tries"
        return finish(len(prompt))
    try:
        entries, skipped = roster.candidates_with_skips(_load_roster(), role)
    except Exception:
        result.reason = "roster_unavailable"
        return finish(len(prompt))
    for entry in entries[:min(max_tries, 2)]:
        if config.global_halt():
            result.rc, result.reason = config.HALT_EXIT_CODE, "global_halt"
            result.reasons.append("global_halt")
            finish(len(prompt))
            raise config.GlobalHalt()
        adapter = {"google": gemini, "sakana": fugu}.get(entry.get("provider"))
        if adapter is None:
            skipped.append({"id": entry["id"], "why": "unsupported_provider"})
            continue
        attempt_start = time.monotonic()
        try:
            response = adapter.generate(prompt, data_class=label, entry_id=entry["id"],
                                        purpose=purpose, timeout=timeout)
        except config.GlobalHalt:
            result.rc, result.reason = config.HALT_EXIT_CODE, "global_halt"
            result.entry_id = entry["id"]
            result.reasons.append("global_halt")
            result.tries.append(dict(entry_id=entry["id"], rc=result.rc,
                                     reason=result.reason, sec=time.monotonic() - attempt_start,
                                     usd=None))
            finish(len(prompt))
            raise
        except Exception:
            response = RouteResult(2, "adapter_error")
        result.rc, result.reason = response.rc, response.reason
        result.text = response.text if response.rc == 0 else ""
        result.entry_id = entry["id"]
        result.tries.append(dict(entry_id=entry["id"], rc=response.rc,
                                 reason=response.reason, sec=time.monotonic() - attempt_start,
                                 usd=getattr(response, "usd", None)))
        if response.rc == 0 or (response.rc == 3 and response.reason == "安全フィルタ"):
            break
    return finish(len(prompt))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orch.router")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--role", required=True)
    run.add_argument("--origin", choices=("public", "private"))
    run.add_argument("--purpose", default="")
    run.add_argument("--max-tries", type=int, default=2)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if config.global_halt():
            raise config.GlobalHalt()
        if args.cmd == "check":
            try:
                data = _load_roster()
                roles = dict.fromkeys(e.get("role_key") or e["role"] for e in data["entries"])
                for role in roles:
                    candidates, skipped = roster.candidates_with_skips(data, role)
                    print(redact_for_log(json.dumps(dict(role=role, candidates=[e["id"] for e in candidates],
                                                        skipped=skipped), ensure_ascii=False)))
                return 0
            except Exception:
                print("router: roster_unavailable", file=sys.stderr)
                return 2
        try:
            prompt = sys.stdin.buffer.read().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            print("router: invalid_input", file=sys.stderr)
            return 2
        result = route(prompt, role=args.role, origin=args.origin,
                       purpose=args.purpose, max_tries=args.max_tries)
    except config.GlobalHalt:
        print("router: 全体停止中", file=sys.stderr)
        return config.HALT_EXIT_CODE
    if result.rc == 0:
        sys.stdout.write(result.text)
    print(redact_for_log(f"router: entry={result.entry_id} class={result.data_class} "
                         f"tries={len(result.tries)} sec={result.sec:.3f}"), file=sys.stderr)
    return result.rc


if __name__ == "__main__":
    sys.exit(main())
