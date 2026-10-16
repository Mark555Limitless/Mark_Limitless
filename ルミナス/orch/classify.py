"""Conservative, local-only data classification before routing."""
import math
import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

from . import config

_KEY = re.compile(config._GENERIC_SECRET.pattern + r"|[A-Za-z0-9_-]{32,}|-----BEGIN[^\r\n]*|xox[abp]-[A-Za-z0-9-]*|ghp_[A-Za-z0-9_]*|AKIA[0-9A-Z]{16}")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"\+\d{6,15}|0\d{1,4}-?\d{1,4}-?\d{3,4}|\d{10,11}")
_PRIVATE = re.compile(r"\.env|settings\.local\.json|_\u975e\u516c\u958b|/\u0055sers/|/home/|C:\\Users\\", re.I)
_SECRET_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, config.SECRET_ENV_NAMES)) + r")\s*[=:]")


def classify(text: str, origin: Optional[str] = None) -> Tuple[str, List[str]]:
    label = {"public": "A", "private": "B"}.get(origin, "C")
    reasons = [] if label != "C" else ["unknown_origin"]
    if not isinstance(text, str):
        return "C", reasons + ["invalid_text"]
    normalized = unicodedata.normalize("NFKC", text)
    for pattern, reason in ((_KEY, "key_shape"), (_EMAIL, "email"),
                            (_PHONE, "phone"), (_PRIVATE, "private_path"),
                            (_SECRET_NAME, "secret_name")):
        if pattern.search(normalized):
            reasons.append(reason)
            label = "C"
    for token in re.findall(r"\S{24,}", normalized):
        counts = Counter(token)
        entropy = -sum((n / len(token)) * math.log2(n / len(token)) for n in counts.values())
        if entropy > 4.5:
            reasons.append("entropy")
            label = "C"
            break
    return label, reasons


def redact_for_log(text: str) -> str:
    out = config.redact(unicodedata.normalize("NFKC", text))
    for pattern in (_EMAIL, _KEY, _PHONE):
        out = pattern.sub("[C]", out)
    return out
