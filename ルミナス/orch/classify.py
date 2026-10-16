"""Conservative, local-only data classification before routing."""
import math
import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

from . import config

# A bare SHA-1 is a commit ID; explicit secret prefixes/assignments still win.
_GENERIC_KEY = (r"(?<![A-Za-z0-9_-])(?![0-9a-fA-F]{40}(?![A-Za-z0-9_-]))"
                r"(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*[0-9])"
                r"[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")
_KEY = re.compile(config._GENERIC_SECRET.pattern + r"|" + _GENERIC_KEY
                  + r"|-----BEGIN[^\r\n]*|xox[abp]-[A-Za-z0-9-]*|ghp_[A-Za-z0-9_]*"
                  r"|AKIA[0-9A-Z]{16}|(?i:key|token|sig|signature|secret|password|pass|pwd|auth|access_token|api_key)="
                  r"[A-Za-z0-9+/=_.\-%]{16,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                    r"\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
_MIXED_ASCII = re.compile(r"[!-~]{16,}")  # 名前に password を含めない（秘密の検査器が代入文と誤認するため）
# Consume dates and identifiers whole; TEL is an explicit phone prefix.
_PHONE = re.compile(r"(?P<non_phone>(?<!\d)\d{4}/\d{1,2}/\d{1,2}"
                    r"|(?<![A-Za-z0-9_-])[0-9a-fA-F]{40}(?![A-Za-z0-9_-])"
                    r"|[A-Za-z][A-Za-z_]*-\d{4}-\d{4}(?![\d-]))"
                    r"|(?P<phone>(?:(?<![A-Za-z0-9])|(?<=TEL))"
                    r"(?:\+[0-9]|\(0|0)[0-9 ()\t.\-]*[0-9](?![A-Za-z0-9]))")
_NUMBERS = re.compile(r"(?<![A-Za-z0-9])[0-9]+(?:[ \t-]+[0-9]+)*(?![A-Za-z0-9])")


def _is_phone(match):
    value = match.group("phone")
    if not value:
        return False
    count = sum(c.isdigit() for c in value)
    return 10 <= count <= (15 if value.startswith("+") else 11)


def _is_password(value):
    return all(re.search(pattern, value) for pattern in
               (r"[A-Z]", r"[a-z]", r"[0-9]", r"[!-/:-@\[-`{-~]"))


def _number_reason(value):
    digits = re.sub(r"[ \t-]", "", value)
    if 13 <= len(digits) <= 19:
        total = 0
        for index, digit in enumerate(reversed(digits)):
            n = int(digit) * (2 if index % 2 else 1)
            total += n - 9 if n > 9 else n
        if total % 10 == 0:
            return "card_number"
    if re.fullmatch(r"[0-9]{12}|[0-9]{4}[ \t-][0-9]{4}[ \t-][0-9]{4}", value):
        total = sum(int(digit) * (n + 1 if n <= 6 else n - 5)
                    for n, digit in enumerate(reversed(digits[:-1]), 1))
        q = 11 - total % 11
        if int(digits[-1]) == (0 if q >= 10 else q):
            return "personal_number"
    return None


_PRIVATE = re.compile(r"(?<![\w.])\.env(?:\.[\w.-]+)?(?![\w])|settings\.local\.json|_\u975e\u516c\u958b|/\u0055sers/|/home/|C:\\Users\\", re.I)
_SECRET_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, config.SECRET_ENV_NAMES)) + r")\s*[=:]", re.I)
_URL = re.compile(r"https?://[^\s<>\u3000-\uffff]+", re.I)


def _normalize(text):
    return re.sub(r"[‐-―−ーｰ]", "-", unicodedata.normalize("NFKC", text)).replace("（", "(").replace("）", ")")


def classify(text: str, origin: Optional[str] = None) -> Tuple[str, List[str]]:
    label = {"public": "A", "private": "B"}.get(origin, "C")
    reasons = [] if label != "C" else ["unknown_origin"]
    if not isinstance(text, str):
        return "C", reasons + ["invalid_text"]
    normalized = _normalize(text)
    for pattern, reason in ((_KEY, "key_shape"), (_EMAIL, "email"),
                            (_PRIVATE, "private_path"),
                            (_SECRET_NAME, "secret_name")):
        if pattern.search(normalized):
            reasons.append(reason)
            label = "C"
    if any(_is_phone(match) for match in _PHONE.finditer(normalized)):
        reasons.append("phone")
        label = "C"
    if any(_is_password(match.group()) for match in _MIXED_ASCII.finditer(normalized)):
        reasons.append("password_shape")
        label = "C"
    for match in _NUMBERS.finditer(normalized):
        reason = _number_reason(match.group())
        if reason and reason not in reasons:
            reasons.append(reason)
            label = "C"
    for token in re.findall(r"[A-Za-z0-9+/=_.\-]{24,}", _URL.sub(" ", normalized)):
        counts = Counter(token)
        entropy = -sum((n / len(token)) * math.log2(n / len(token)) for n in counts.values())
        if entropy > 4.5:
            reasons.append("entropy")
            label = "C"
            break
    return label, reasons


def redact_for_log(text: str) -> str:
    out = config.redact(_normalize(text))
    for pattern in (_EMAIL, _KEY):
        out = pattern.sub("[C]", out)
    out = _MIXED_ASCII.sub(lambda m: "[C]" if _is_password(m.group()) else m.group(), out)
    out = _NUMBERS.sub(lambda m: "[C]" if _number_reason(m.group()) else m.group(), out)
    return _PHONE.sub(lambda match: "[C]" if _is_phone(match) else match.group(), out)
