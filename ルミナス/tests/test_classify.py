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
