"""Conservative, local-only data classification before routing."""
import math
import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

from . import config

_HEX40 = r"(?<![A-Za-z0-9_-])[0-9a-fA-F]{40}(?![A-Za-z0-9_-])"
_GENERIC_KEY = (r"(?<![A-Za-z0-9_-])"
                r"(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*[0-9])"
                r"[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")
_KEY = re.compile(config._GENERIC_SECRET.pattern + r"|" + _GENERIC_KEY + r"|" + _HEX40
                  + r"|-----BEGIN[^\r\n]*|xox[abp]-[A-Za-z0-9-]*|ghp_[A-Za-z0-9_]*"
                  r"|AKIA[0-9A-Z]{16}|(?i:key|token|sig|signature|secret|password|pass|pwd|auth|access_token|api_key)="
                  r"[A-Za-z0-9+/=_.\-%]{16,}")
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                    r"\.[A-Za-z]{2,}")
_MIXED_ASCII = re.compile(r"[!-~]{16,}")  # 名前に password を含めない（秘密の検査器が代入文と誤認するため）
# Consume recognized identifiers whole; dates are masked by _number_text.
_PHONE = re.compile(r"(?P<non_phone>(?<![A-Za-z0-9_-])[0-9a-fA-F]{40}(?![A-Za-z0-9_-])"
                    r"|(?<![A-Za-z_])[A-Za-z][A-Za-z_]*-\d{4}-\d{4}(?![\d-]))"
                    r"|(?P<phone>(?<!\d)"
                    r"(?:\+[0-9]|\(0|[0-9])[0-9 ()\t\r\n./_,\-]*[0-9](?!\d))")
_NUMBERS = re.compile(r"(?<!\d)[0-9]+(?:[ \t\r\n./_,-]+[0-9]+)*(?!\d)")
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DAY = r"(?:0?[1-9]|[12][0-9]|3[01])"
_DATE_PART = r"(?:19|20)[0-9]{2}(?:/" + _MONTH + "/" + _DAY + "|-" + _MONTH + "-" + _DAY + ")"
_DATE = re.compile(r"(?<![0-9./_,+\-])" + _DATE_PART + "(?:-" + _DATE_PART
                   + r")?(?![0-9./_,+\-])")
_VERSIONS = re.compile(r"\bversion[ \t]+(?:(?:0|[1-9][0-9]{0,2})\.[0-9]{1,3}\.[0-9]{1,3}"
                       r"(?![\w.])(?:[ \t]+|$))+", re.I)


def _is_phone(match):
    value = match.group("phone")
    if not value:
        return False
    # Whole digit groups only: never take a phone-sized prefix of a longer number.
    groups = list(re.finditer(r"[0-9]+", value))
    for start, group in enumerate(groups):
        international = start == 0 and value.startswith('+')
        if not international and not group.group().startswith('0'):
            continue
        limit = 15 if international else 11
        count = 0
        for index in range(start, min(start + limit, len(groups))):
            count += len(groups[index].group())
            if count > limit:
                break
            if count >= 10:
                return True
    return False


def _is_password(value):
    if not re.search(r"[^A-Za-z0-9._()/:,\-]", value):
        return False
    return all(re.search(pattern, value) for pattern in
               (r"[A-Z]", r"[a-z]", r"[0-9]", r"[!-/:-@\[-`{-~]"))


def _number_reason(value):
    # Limit individual runs, not the entire input. Visit every separated group.
    groups = re.findall(r"[0-9]+", value)
    if any(len(group) > 60 for group in groups):
        return "long_number"
    personal = None
    for start in range(len(groups)):
        digits = ""
        for index in range(start, min(start + 19, len(groups))):
            digits += groups[index]
            if len(digits) > 19:
                break
            reason = _checksum_reason(digits)
            if reason == "card_number":
                return reason
            if reason:
                personal = reason
    for group in groups:
        for start in range(max(0, len(group) - 11)):
            for size in range(12, min(19, len(group) - start) + 1):
                reason = _checksum_reason(group[start:start + size])
                if reason == "card_number":
                    return reason
                if reason:
                    personal = reason
    return personal


def _checksum_reason(digits):
    if 13 <= len(digits) <= 19:
        total = 0
        for index, digit in enumerate(reversed(digits)):
            n = int(digit) * (2 if index % 2 else 1)
            total += n - 9 if n > 9 else n
        if total % 10 == 0:
            return "card_number"
    if len(digits) == 12:
        total = sum(int(digit) * (n + 1 if n <= 6 else n - 5)
                    for n, digit in enumerate(reversed(digits[:-1]), 1))
        q = 11 - total % 11
        if int(digits[-1]) == (0 if q >= 10 else q):
            return "personal_number"
    return None


_PRIVATE = re.compile(r"(?<![\w.])\.env(?:\.[\w.-]+)?(?![\w])|settings\.local\.json|_\u975e\u516c\u958b|/\u0055sers/|/home/|C:\\Users\\", re.I)
_SECRET_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, config.SECRET_ENV_NAMES)) + r")\s*[=:]", re.I)
_URL_CHARS = r"[^\s\"',;|<>()\[\]{}\u3000-\uffff]"
_URL = re.compile(r"https?://(?:\[[0-9A-Fa-f:.]+\]" + _URL_CHARS + r"*|"
                  + _URL_CHARS + r"+)", re.I)
_SCHEME = re.compile(r"https?://", re.I)
# Only entropy inspection removes a valid host; userinfo remains inspectable.
_URL_HEAD = re.compile(r"https?://(?=[^/?#]*@)|https?://"
                       r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]+)?(?=[/?#]|$)", re.I)
_UUID = re.compile(r"(?<![A-Za-z0-9_-])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                   r"[0-9a-f]{4}-[0-9a-f]{12}(?![A-Za-z0-9_-])", re.I)
_POST_ID = re.compile(r"/status(?:es)?/([0-9]{15,20})(?=/|$)")
_POST_HOSTS = frozenset(("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"))
_COMMIT_WORD = re.compile(r"\b(?:commit|sha1?|rev|hash|ref)\s*:?\s*$", re.I)
_GIT_PATH = re.compile(r"/(?:commit|commits|tree|blob|compare)/$")


def _inspection_text(text, entropy=False, split_equals=False):
    """Keep offsets while separating URL components; never decode percent escapes."""
    def replace(match):
        value = match.group()
        head = (_URL_HEAD.match(value) if entropy else None) or _SCHEME.match(value)
        size = head.end() if head else 0
        separators = r"[/?&#=]" if entropy or split_equals else r"[/?&#]"
        return ' ' * size + re.sub(separators, " ", value[size:])
    return _URL.sub(replace, _UUID.sub(lambda m: ' ' * len(m.group()), text))


def _number_text(text):
    """Mask dates and public post IDs, preserving all offsets and query values."""
    def replace(match):
        value = match.group()
        head = _URL_HEAD.match(value)
        if not head or '@' in value[:head.end()]:
            return value
        # 投稿 ID を除外するのは決めたホスト（X／Twitter）だけ。任意のホストの /status/ で数字を逃がさない（再審査の指摘 2026-10-17）
        host = re.sub(r"^https?://", "", head.group(), flags=re.I).split(":")[0].lower()
        if host not in _POST_HOSTS:
            return value
        path_end = min([value.find(c) for c in '?#' if c in value] or [len(value)])
        path = value[head.end():path_end]
        path = _POST_ID.sub(lambda m: m.group()[:m.start(1) - m.start()]
                            + ' ' * len(m.group(1)), path)
        return value[:head.end()] + path + value[path_end:]
    text = _URL.sub(replace, text)
    for pattern in (_DATE, _VERSIONS):
        text = pattern.sub(lambda m: ' ' * len(m.group()), text)
    return text


def _is_commit(text, match):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", match.group()):
        return False
    for url in _URL.finditer(text):
        if url.start() <= match.start() < url.end():
            head = _URL_HEAD.match(url.group())
            if not head:
                return False
            prefix = text[url.start() + head.end():match.start()]
            return '?' not in prefix and '#' not in prefix and bool(_GIT_PATH.search(prefix))
    return bool(_COMMIT_WORD.search(text[:match.start()]))


def _key_matches(text):
    """Inspect keys in hosts, userinfo, paths and queries, keeping original offsets."""
    return [match for match in _KEY.finditer(_inspection_text(text))
            if not _is_commit(text, match)]


def _password_text(text):
    masked = re.sub(_HEX40, lambda m: ' ' * len(m.group()) if _is_commit(text, m)
                    else m.group(), text)
    return _inspection_text(masked, split_equals=True)


def _normalize(text):
    text = ''.join(char for char in text if unicodedata.category(char) != 'Cf')
    return re.sub(r"[‐-―−ーｰ]", "-", unicodedata.normalize("NFKC", text)).replace("（", "(").replace("）", ")")


def classify(text: str, origin: Optional[str] = None) -> Tuple[str, List[str]]:
    label = {"public": "A", "private": "B"}.get(origin, "C")
    reasons = [] if label != "C" else ["unknown_origin"]
    if not isinstance(text, str):
        return "C", reasons + ["invalid_text"]
    normalized = _normalize(text)
    if any(_key_matches(normalized)):
        reasons.append("key_shape")
        label = "C"
    for pattern, reason in ((_EMAIL, "email"),
                            (_PRIVATE, "private_path"),
                            (_SECRET_NAME, "secret_name")):
        if pattern.search(normalized):
            reasons.append(reason)
            label = "C"
    number_text = _number_text(normalized)
    if any(_is_phone(match) for match in _PHONE.finditer(number_text)):
        reasons.append("phone")
        label = "C"
    if any(_is_password(match.group()) for match in
           _MIXED_ASCII.finditer(_password_text(normalized))):
        reasons.append("password_shape")
        label = "C"
    for match in _NUMBERS.finditer(number_text):
        reason = _number_reason(match.group())
        if reason and reason not in reasons:
            reasons.append(reason)
            label = "C"
    for token in re.findall(r"[A-Za-z0-9+/=_.\-]{24,}",
                            _inspection_text(normalized, entropy=True)):
        counts = Counter(token)
        entropy = -sum((n / len(token)) * math.log2(n / len(token)) for n in counts.values())
        if entropy > 4.5:
            reasons.append("entropy")
            label = "C"
            break
    return label, reasons


def redact_for_log(text: str) -> str:
    out = config.redact(_normalize(text))
    for match in reversed(list(_key_matches(out))):
        out = out[:match.start()] + "[C]" + out[match.end():]
    out = _EMAIL.sub("[C]", out)
    for match in reversed(list(_MIXED_ASCII.finditer(_password_text(out)))):
        if _is_password(match.group()):
            out = out[:match.start()] + "[C]" + out[match.end():]
    for match in reversed(list(_NUMBERS.finditer(_number_text(out)))):
        if _number_reason(match.group()):
            out = out[:match.start()] + "[C]" + out[match.end():]
    for match in reversed(list(_PHONE.finditer(_number_text(out)))):
        if _is_phone(match):
            out = out[:match.start()] + "[C]" + out[match.end():]
    # Remove the path suffix as well, so filenames cannot leak via metadata.
    return re.sub(r"(?:" + _PRIVATE.pattern + r""")[^\s"'<>|,;)\]}]*""",
                  "[C]", out, flags=re.I)
