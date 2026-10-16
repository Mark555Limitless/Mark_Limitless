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
    'abcdef0123456789' * 2 + 'abcdef01',
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
