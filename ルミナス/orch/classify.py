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
                  r"|AKIA[0-9A-Z]{16}|(?i:key=)[A-Za-z0-9_+/=-]{20,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)+")
# Consume dates and numeric identifiers whole, without hiding TEL-prefixed numbers.
_PHONE = re.compile(r"(?P<non_phone>(?<!\d)\d{4}/\d{1,2}/\d{1,2}"
                    r"|(?<![A-Za-z0-9_-])[0-9a-fA-F]{40}(?![A-Za-z0-9_-])"
                    r"|[A-Za-z][A-Za-z_]*-\d{4}-\d{4}(?![\d-]))"
                    r"|(?P<phone>(?<!\d)(?:"
                    r"\+\d{1,3}[-\s.]?\d{1,4}[-\s.]?\d{1,4}[-\s.]?\d{3,4}"
                    r"|0\d{1,4}[-\s.]?\d{1,4}[-\s.]?\d{3,4})(?!\d))")
_PRIVATE = re.compile(r"(?<![\w.])\.env(?:\.[\w.-]+)?(?![\w])|settings\.local\.json|_\u975e\u516c\u958b|/\u0055sers/|/home/|C:\\Users\\", re.I)
_SECRET_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, config.SECRET_ENV_NAMES)) + r")\s*[=:]", re.I)
_URL = re.compile(r"https?://[^\s<>\u3000-\uffff]+", re.I)


def _normalize(text):
    return unicodedata.normalize("NFKC", text).replace("\u2212", "-")


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
    if any(match.group("phone") for match in _PHONE.finditer(normalized)):
        reasons.append("phone")
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
    return _PHONE.sub(lambda match: "[C]" if match.group("phone") else match.group(), out)
