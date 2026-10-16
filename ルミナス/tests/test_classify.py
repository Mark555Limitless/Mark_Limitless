from time import perf_counter

import pytest
from orch.classify import classify, redact_for_log


@pytest.mark.parametrize('text,reason', [
    ('AIza' + 'x' * 32, 'key_shape'), ('sk-' + 'x' * 32, 'key_shape'),
    # 鍵の形は実行時に組み立てる（秘密の検査器がこのファイル自体を鍵と誤認しないように）
    ('AK' + 'IA' + 'X' * 16, 'key_shape'), ('-----' + 'BEGIN PRIVATE' + ' KEY-----', 'key_shape'),
    ('090-1234-5678', 'phone'), ('０９０１２３４５６７８', 'phone'),
    ('+81901234567', 'phone'), ('test@example.test', 'email'),
    ('.env', 'private_path'), ('/' + 'Users/person/file', 'private_path'),
    ('/home/person/file', 'private_path'), ('C:\\Users\\person', 'private_path'),
    ('GEMINI_API_KEY=', 'secret_name'), ('settings.local.json', 'private_path'),
    ('_\u975e\u516c\u958b', 'private_path'),
    ('0123456789abcdefghijklmnopqrstuv', 'entropy'),
])
def test_sensitive(text, reason):
    label, reasons = classify(text, 'public')
    assert label == 'C' and reason in reasons


@pytest.mark.parametrize('origin,label', [('public', 'A'), ('private', 'B'), (None, 'C'), ('other', 'C')])
def test_origin(origin, label):
    assert classify('今日の天気について短い文章を書いてください。', origin)[0] == label


def test_redaction():
    for value in ['test@example.test', '０９０１２３４５６７８', 'ghp_' + 'x' * 35]:
        assert redact_for_log(value) == '[C]'


def test_config_redaction(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic value')
    assert 'synthetic value' not in redact_for_log('synthetic value')


@pytest.mark.parametrize('text', [
    '来週の会議で新しい企画を紹介するための文章を参加者全員に伝わるように書いてください。',
    '初めて訪れる方にも会場の住所と駅からの道順が分かるように案内文を作成してください。',
    '来月の予定について参加者全員が無理なく集まれる日程を相談する文章を考えてください。',
    '記事 https://www.example.com/news/2026/10/16/internationalization-and-localization-guidelines を紹介',
    'commit ' + 'abcdef0123456789' * 2 + 'abcdef01',
    'internationalization-and-localization-guidelines',
    '20261016', '12345678901円', 'ISBN 9784123456789', 'INV-0012-3456',
    '2026/10/01-2026/10/31', '期間2026/10/01-2026/10/31', 'react@18.3.1', '.envrc', '.environment',
    'process.env', 'process.env.X',
])
def test_public_regressions(text):
    assert classify(text, 'public') == ('A', [])


@pytest.mark.parametrize('text,reason', [
    ('TEL-090-1234-5678', 'phone'), ('TEL090-1234-5678', 'phone'), ('電話/090-1234-5678', 'phone'),
    ('+81 90 1234 5678', 'phone'), ('090 1234 5678', 'phone'),
    ('090.1234.5678', 'phone'), ('０９０−１２３４−５６７８', 'phone'),
    ('a.b@example.co.jp', 'email'), ('.env.local', 'private_path'),
    ('.env.bak.20261011', 'private_path'), ('gemini_api_key=', 'secret_name'),
    ('https://example.test/?key=' + 'x' * 20, 'key_shape'),
    ('https://example.test/?token=' + 'AIza' + 'x' * 32, 'key_shape'),
    ('https://example.test/?token=' + 'sk-' + 'x' * 32, 'key_shape'),
    ('Z9_' * 12, 'key_shape'),
])
def test_sensitive_regressions(text, reason):
    for origin in ('public', 'private', None):
        label, reasons = classify(text, origin)
        assert label == 'C' and reason in reasons


def test_url_exclusion_preserves_following_entropy():
    text = 'https://example.test/ 記事を紹介。' + '0123456789abcdefghijklmnopqrstuv'
    assert 'entropy' in classify(text, 'public')[1]


@pytest.mark.parametrize('text,reason', [
    ('x@163.com', 'email'), ('foo@1und1.de', 'email'),
    ('p@ssW0rd!' + 'Xy7#Lm2$' + 'Qr9&Tz4*Kw8', 'password_shape'),
    ('4111111111111111', 'card_number'),
    ('4111 1111 1111 1111', 'card_number'),
    ('5500-0000-0000-0004', 'card_number'),
    ('https://example.test/?sig=' + 'aB3dE5fG7hJ9kL1mN3pQ5rSx', 'key_shape'),
    ('https://example.test/?token=' + 'a' * 16, 'key_shape'),
    ('090‐1234‐5678', 'phone'), ('090ー1234ー5678', 'phone'),
    ('(03)1234-5678', 'phone'), ('03(1234)5678', 'phone'),
    ('+81 (0)90 1234 5678', 'phone'), ('+1 (555) 123-4567', 'phone'),
])
def test_restored_sensitive_cases(text, reason):
    for origin in ('public', 'private', None):
        label, reasons = classify(text, origin)
        assert label == 'C' and reason in reasons
    assert text not in redact_for_log(text)


@pytest.mark.parametrize('text', [
    'react@18.3.1', 'pkg@1.2.3-beta',
    'print(f"{user.name}:{user.id}")', 'os.path.join(a,b)', 'x=1;y=2',
    # 4111111111111112 は Luhn に通る部分番号を含むので、窓の判定では C（安全側。2026-10-17 に A から変更）
    '期限 08 2026', '05 10 2026', '〒060-0001',
    'INV 0012-3456', '注文番号 000123', 'commit 3f0912345a',
    'Please write a clear introduction for everyone attending the meeting.',
    'The value is 0.5 and version 1.2.3', 'prod.env', '.env_backup',
])
def test_restored_public_cases(text):
    assert classify(text, 'public') == ('A', [])
    assert redact_for_log(text) == text


def personal_check_digit(body):
    weights = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    remainder = sum(int(d) * w for d, w in zip(body, weights)) % 11
    return str(0 if remainder <= 1 else 11 - remainder)


@pytest.mark.parametrize('body', ['12345678901', '11111111111', '10000000008'])
@pytest.mark.parametrize('separator', ['', ' ', '-'])
def test_personal_number_checksum(body, separator):
    number = body + personal_check_digit(body)
    text = separator.join(number[i:i + 4] for i in range(0, 12, 4))
    assert 'personal_number' in classify(text, 'public')[1]
    assert redact_for_log(text) == '[C]'


def test_invalid_personal_number():
    number = '123456789013'
    assert number[-1] != personal_check_digit(number[:-1])
    assert classify(number, 'public') == ('A', [])


@pytest.mark.parametrize('name', [
    'key', 'token', 'sig', 'signature', 'secret', 'password', 'pass', 'pwd',
    'auth', 'access_token', 'api_key',
])
@pytest.mark.parametrize('prefix', ['', 'https://example.test/?'])
def test_token_assignment_boundaries(name, prefix):
    text = prefix + name.upper() + '='
    assert 'key_shape' in classify(text + 'x' * 16, 'public')[1]
    assert 'key_shape' not in classify(text + 'x' * 15, 'public')[1]


@pytest.mark.parametrize('text,expected', [
    ('aA1!' + 'a' * 12, True), ('aA1!' + 'a' * 11, False),
    ('aa1!' + 'a' * 12, False), ('AA1!' + 'A' * 12, False),
    ('aAa!' + 'a' * 12, False), ('aA1a' + 'a' * 12, False),
])
def test_password_shape_boundary(text, expected):
    assert ('password_shape' in classify(text, 'public')[1]) is expected


# Synthetic values are assembled here, never real credentials.
_HEX_VALUE = 'abcdef0123456789' * 2 + 'abcdef01'
_RANDOM_VALUE = '0123456789abcdefghijklmnopqrstuvwx'


@pytest.mark.parametrize('prefix,suffix,reason', [
    ('', '', 'key_shape'), ('token=', '', 'key_shape'),
    ('文の途中', 'です', 'key_shape'),
    ('https://x.test/', '', 'key_shape'),
    ('https://x.test/a/', '', 'entropy'),
    ('https://x.test/dl?f=', '', 'entropy'),
    ('https://x.test/?f=/commit/', '', 'key_shape'),
    ('https://x.test/#/commit/', '', 'key_shape'),
    ('/commit/', '', 'key_shape'), ('notcommit ', '', 'key_shape'),
])
def test_bypass_rejected(prefix, suffix, reason):
    value = _RANDOM_VALUE if reason == 'entropy' else _HEX_VALUE
    text = prefix + value + suffix
    for origin in ('public', 'private', None):
        label, reasons = classify(text, origin)
        assert label == 'C' and reason in reasons
    assert value not in redact_for_log(text)


@pytest.mark.parametrize('prefix,suffix', [
    ('commit ', ''), ('sha: ', ''), ('SHA1:  ', ''),
    ('REV ', ''), ('hash ', ''), ('ref ', ''),
    ('https://github.com/o/r/commit/', ''),
    ('https://github.com/o/r/commits/', ''),
    ('https://github.com/o/r/tree/', ''),
    ('https://github.com/o/r/blob/', '/README.md'),
    ('https://github.com/o/r/compare/', ''),
])
def test_explicit_commit_context(prefix, suffix):
    text = prefix + _HEX_VALUE + suffix
    assert classify(text, 'public') == ('A', [])
    assert redact_for_log(text) == text


@pytest.mark.parametrize('text', [
    'https://www.example.com/news/2026/10/16/internationalization-and-localization-guidelines',
    'https://example.test/?page=2&sort=asc',
    'https://' + _RANDOM_VALUE + '.test/',
    'https://x.test/abcdefghijklmnop/qrstuvwxyz012345',
    'https://x.test/?f=abcdefghijklmnop&g=qrstuvwxyz012345',
])
def test_url_components_public(text):
    assert classify(text, 'public') == ('A', [])


def test_bare_hex_redaction():
    assert redact_for_log(_HEX_VALUE) == '[C]'
    assert redact_for_log('commit ' + _HEX_VALUE) == 'commit ' + _HEX_VALUE


@pytest.mark.parametrize('value', ['a' * 40, '1' * 40, _HEX_VALUE.upper()])
def test_hex_key_without_mixed_characters(value):
    assert 'key_shape' in classify(value, 'public')[1]
    assert redact_for_log(value) == '[C]'


@pytest.mark.parametrize('text,reason', [
    ('090-1234-5678 9', 'phone'), ('9 090-1234-5678', 'phone'),
    ('tel 09012345678', 'phone'), ('Tel: 090 1234 5678', 'phone'),
    ('tel09012345678', 'phone'), ('電話09012345678', 'phone'),
    ('03-1234-5678/03-1234-5679', 'phone'),
    ('9 (03)1234-5678 9', 'phone'), ('9 +81 90 1234 5678 9', 'phone'),
    ('4111111111111111 123', 'card_number'),
    ('123 4111-1111-1111-1111', 'card_number'),
    ('41111111111111110', 'card_number'),
    ('9 4111-1111-1111-1111 9', 'card_number'),
    ('a@example.com-1', 'email'), ('a@example.com2', 'email'),
])
def test_sensitive_windows(text, reason):
    assert classify(text, 'public')[0] == 'C'
    assert reason in classify(text, 'public')[1]
    redacted = redact_for_log(text)
    expected = {
        'tel 09012345678': 'tel [C]',
        'Tel: 090 1234 5678': 'Tel: [C]',
        'tel09012345678': 'tel[C]',
        '電話09012345678': '電話[C]',
        '03-1234-5678/03-1234-5679': '[C]/[C]',
        '9 +81 90 1234 5678 9': '9 [C]',
        'a@example.com-1': '[C]-1',
        'a@example.com2': '[C]2',
    }
    assert redacted == expected.get(text, '[C]')


@pytest.mark.parametrize('separator', ['', ' ', '-'])
@pytest.mark.parametrize('prefix,suffix', [('', ' 1'), ('1 ', ''), ('1 ', ' 1')])
def test_personal_number_windows(separator, prefix, suffix):
    body = '12345678901'
    number = body + personal_check_digit(body)
    text = prefix + separator.join(number[i:i + 4] for i in range(0, 12, 4)) + suffix
    assert classify(text, 'public')[0] == 'C'
    assert 'personal_number' in classify(text, 'public')[1]
    assert redact_for_log(text) == '[C]'


@pytest.mark.parametrize('text', [
    '期限 08 2026', '05 10 2026', '〒060-0001', '2026/10/01-2026/10/31',
    '注文番号 000123', '2222222222222222 123', '123456789013',
    'react@18.3.1', 'pkg@1.2.3-beta',
    '来週の会議で新しい企画を紹介するための文章を参加者全員に伝わるように書いてください。',
    'Please write a clear introduction for everyone attending the meeting.',
])
def test_windows_public(text):
    assert classify(text, 'public') == ('A', [])
    assert redact_for_log(text) == text


def test_checksum_work_is_limited_to_sixty_digits(monkeypatch):
    import importlib
    module = importlib.import_module('orch.classify')
    checked = []
    monkeypatch.setattr(module, '_checksum_reason', lambda digits: checked.append(digits))
    assert module._number_reason('2' * 60 + '4111111111111111') is None
    assert checked and all(set(digits) <= {'2'} for digits in checked)
    checked.clear()
    assert module._number_reason('2 ' * 60 + '4111111111111111') is None
    assert checked and all(set(digits) <= {'2'} for digits in checked)


@pytest.mark.parametrize('unit', [
    '2', '2 ', '2222222222222222 123/',
    'Please write a clear introduction. ',
    '会議の参加者に分かりやすい案内文を作成してください。',
])
def test_classify_ten_kilobytes_under_half_second(unit):
    text = (unit * 10240).encode('utf-8')[:10240].decode('utf-8', errors='ignore')
    start = perf_counter()
    classify(text, 'public')
    elapsed = perf_counter() - start
    assert elapsed < 0.5, elapsed


@pytest.mark.parametrize('text', [
    'https://user:' + 'AIza' + 'x' * 32 + '@example.test/path',   # ユーザー情報の中の鍵の形
    'https://' + 'AK' + 'IA' + 'X' * 16 + '@example.test/',
    'https://u:' + '0123456789abcdefghijklmnopqrstuv' + '@example.test/',  # ユーザー情報の中の乱雑な文字列
])
def test_url_userinfo_is_inspected(text):
    # URL を分割しても検出は減らない（自動のセキュリティ審査の指摘 2026-10-17）
    label, reasons = classify(text, 'public')
    assert label == 'C' and ('key_shape' in reasons or 'entropy' in reasons)
    secret = text[len('https://'):text.index('@')]
    assert secret not in redact_for_log(text)
