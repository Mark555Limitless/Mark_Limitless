import io
import json
from unittest.mock import Mock

import pytest
from orch import config, router, gemini, fugu


@pytest.fixture
def routing(isolated_env, monkeypatch):
    entries = []
    for ident, provider, state in [('first', 'google', 'adopted'), ('second', 'sakana', 'trial'), ('third', 'google', 'trial')]:
        entries.append(dict(id=ident, role='draft', role_key='drafter', provider=provider,
                            state=state, model='test', hosts=['example.test'],
                            max_data_class='A', version_kind='alias', evidence=[],
                            rollback_to='stop', review_by='2026-11-01',
                            price={'input': 0.1, 'output': 0.1}, caps={'usd_per_day': 10},
                            jurisdiction='US' if provider == 'google' else 'JP'))
    path = isolated_env / 'roster.json'
    data = {'entries': entries}
    path.write_text(json.dumps(data))
    monkeypatch.setenv('ORCH_ROSTER', str(path))
    monkeypatch.setenv('GEMINI_API_KEY', 'fake')
    monkeypatch.setenv('SAKANA_API_KEY', 'fake')
    monkeypatch.setattr(gemini.requests, 'post', Mock(side_effect=AssertionError('unexpected network')))
    monkeypatch.setattr(fugu.requests, 'get', Mock(side_effect=AssertionError('unexpected network')))
    return path, data


def test_c_short_circuits(routing, monkeypatch):
    class Sensitive(str):
        def __len__(self):
            raise AssertionError('must not measure')
    loader = Mock(side_effect=AssertionError('must not load'))
    monkeypatch.setattr(router, '_load_roster', loader)
    result = router.route(Sensitive('hello'), role='drafter')
    assert result.rc == 4 and result.reasons == ['unknown_origin']
    loader.assert_not_called()


def test_http_fallback(routing, monkeypatch, fake_resp):
    post = Mock(side_effect=[fake_resp(500), fake_resp(200, {
        'choices': [{'message': {'content': 'done'}}],
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})])
    monkeypatch.setattr(gemini.requests, 'post', post)
    result = router.route('普通の依頼', role='drafter', origin='public')
    assert result.rc == 0 and result.text == 'done' and len(result.tries) == 2
    assert result.tries[0]['usd'] > 0
    assert result.entry_id == 'second' and post.call_count == 2


@pytest.mark.parametrize('rc,reason,count', [(2, 'API障害', 2), (3, '空応答', 2), (3, '安全フィルタ', 1)])
def test_attempt_limits(routing, monkeypatch, rc, reason, count):
    call = Mock(return_value=gemini.Result(rc, reason))
    monkeypatch.setattr(gemini, 'generate', call)
    monkeypatch.setattr(fugu, 'generate', call)
    result = router.route('普通の依頼', role='drafter', origin='public')
    assert result.rc == rc and len(result.tries) == count and call.call_count == count


def test_stop_and_log(routing, monkeypatch, isolated_env):
    path, data = routing
    data['stops'] = {'jurisdictions': ['US']}
    path.write_text(json.dumps(data))
    monkeypatch.setattr(fugu, 'generate', Mock(return_value=fugu.Result(0, 'ok', 'output')))
    result = router.route('本文は記録しない', role='drafter', origin='public', purpose='test@example.test')
    assert result.rc == 0 and result.entry_id == 'second'
    raw = (isolated_env / 'data/router_log.jsonl').read_text()
    assert '本文は記録しない' not in raw and 'output' not in raw and 'test@example.test' not in raw
    row = json.loads(raw)
    assert set(row) == {'ts', 'purpose', 'role', 'data_class', 'reasons', 'prompt_chars', 'tries', 'final_rc', 'final_entry', 'total_sec', 'skipped'}
    assert row['skipped'][0]['why'] == 'jurisdiction_stopped'


def test_purpose_is_redacted_before_adapters(routing, monkeypatch):
    # purpose は利用者の入力から来うる。アダプタ（台帳・ログに書く側）へ渡る前に伏せて 80 字に切る
    seen = Mock(return_value=gemini.Result(0, 'ok', 'output'))
    monkeypatch.setattr(gemini, 'generate', seen)
    long = 'x' * 200
    router.route('本文', role='drafter', origin='public', purpose='mail test@example.test key ' + 'ghp_' + 'x' * 35 + long)
    passed = seen.call_args.kwargs['purpose']
    assert 'test@example.test' not in passed and 'ghp_' not in passed and len(passed) <= 80


def test_no_candidates(routing):
    assert router.route('hello', role='missing', origin='public').rc == 2


def test_halt(routing):
    config.HALT_PATH.parent.mkdir(exist_ok=True)
    config.HALT_PATH.touch()
    with pytest.raises(config.GlobalHalt):
        router.route('hello', role='drafter')
    assert router.main(['check']) == config.HALT_EXIT_CODE


@pytest.mark.parametrize('rc', [0, 2, 3, 4, config.HALT_EXIT_CODE])
def test_cli(routing, monkeypatch, capsys, rc):
    call = Mock(return_value=router.RouteResult(rc, 'reason', text='answer'))
    if rc == config.HALT_EXIT_CODE:
        call.side_effect = config.GlobalHalt()
    monkeypatch.setattr(router, 'route', call)
    monkeypatch.setattr('sys.stdin', io.TextIOWrapper(io.BytesIO(b'hello'), encoding='utf-8'))
    assert router.main(['run', '--role', 'drafter', '--origin', 'public']) == rc
    out = capsys.readouterr()
    assert out.out == ('answer' if rc == 0 else '')
    assert 'router:' in out.err


def test_check(routing, capsys):
    assert router.main(['check']) == 0
    assert json.loads(capsys.readouterr().out)['candidates'] == ['first', 'second', 'third']


def test_logging_failure(routing, monkeypatch):
    monkeypatch.setattr(config, 'data_dir', Mock(side_effect=OSError()))
    assert router.route('hello', role='drafter').rc == 4


@pytest.mark.parametrize('limit,count', [(1, 1), (2, 2), (10, 2)])
def test_explicit_limit(routing, monkeypatch, limit, count):
    call = Mock(return_value=gemini.Result(2, 'API障害'))
    monkeypatch.setattr(gemini, 'generate', call)
    monkeypatch.setattr(fugu, 'generate', call)
    result = router.route('hello', role='drafter', origin='public', max_tries=limit)
    assert len(result.tries) == count


def test_unsupported_counts_toward_row_limit(routing, monkeypatch, isolated_env):
    path, data = routing
    data['entries'][0]['provider'] = 'unsupported'
    path.write_text(json.dumps(data))
    call = Mock(return_value=fugu.Result(2, 'API障害'))
    monkeypatch.setattr(fugu, 'generate', call)
    never = Mock(side_effect=AssertionError())
    monkeypatch.setattr(gemini, 'generate', never)
    result = router.route('hello', role='drafter', origin='public')
    assert len(result.tries) == 1
    never.assert_not_called()
    row = json.loads((isolated_env / 'data/router_log.jsonl').read_text())
    assert row['skipped'] == [{'id': 'first', 'why': 'unsupported_provider'}]


def test_private_still_passes_adapter_gate(routing):
    result = router.route('非公開の依頼', role='drafter', origin='private')
    assert result.rc == 2
    gemini.requests.post.assert_not_called()


def test_adapter_halt_logged_once(routing, monkeypatch, isolated_env):
    halted = Mock(side_effect=config.GlobalHalt())
    fallback = Mock(side_effect=AssertionError('must not fall back'))
    monkeypatch.setattr(gemini, 'generate', halted)
    monkeypatch.setattr(fugu, 'generate', fallback)
    with pytest.raises(config.GlobalHalt):
        router.route('本文を保存しない', role='drafter', origin='public')
    raw = (isolated_env / 'data/router_log.jsonl').read_text()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 1
    assert rows[0]['final_rc'] == config.HALT_EXIT_CODE
    assert rows[0]['reasons'] == ['global_halt']
    assert rows[0]['tries'][0]['reason'] == 'global_halt'
    assert '本文を保存しない' not in raw
    fallback.assert_not_called()


def test_adapter_halt_survives_logging_failure(routing, monkeypatch):
    monkeypatch.setattr(gemini, 'generate', Mock(side_effect=config.GlobalHalt()))
    monkeypatch.setattr(config, 'data_dir', Mock(side_effect=OSError()))
    with pytest.raises(config.GlobalHalt):
        router.route('hello', role='drafter', origin='public')


def test_cli_invalid_utf8(routing, monkeypatch, capsys):
    call = Mock(side_effect=AssertionError('must not route'))
    monkeypatch.setattr(router, 'route', call)
    monkeypatch.setattr('sys.stdin', io.TextIOWrapper(io.BytesIO(b'hello\xff'), encoding='utf-8'))
    assert router.main(['run', '--role', 'drafter', '--origin', 'public']) == 2
    out = capsys.readouterr()
    assert out.out == '' and out.err == 'router: invalid_input\n'
    call.assert_not_called()


@pytest.mark.parametrize('halt_checks,attempts', [([False, False, True], 1), ([False, True], 0)])
def test_loop_halt_records_completed_attempts(routing, monkeypatch, isolated_env, halt_checks, attempts):
    monkeypatch.setattr(config, 'global_halt', Mock(side_effect=halt_checks))
    first = Mock(return_value=gemini.Result(2, 'API障害'))
    second = Mock(side_effect=AssertionError('must not fall back'))
    monkeypatch.setattr(gemini, 'generate', first)
    monkeypatch.setattr(fugu, 'generate', second)
    with pytest.raises(config.GlobalHalt):
        router.route('本文を保存しない', role='drafter', origin='public')
    raw = (isolated_env / 'data/router_log.jsonl').read_text()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row['final_rc'] == config.HALT_EXIT_CODE
    assert row['reasons'] == ['global_halt']
    assert len(row['tries']) == attempts
    assert first.call_count == attempts
    if attempts:
        assert row['tries'][0]['entry_id'] == 'first'
        assert row['tries'][0]['rc'] == 2
        assert row['tries'][0]['reason'] == 'API障害'
    assert '本文を保存しない' not in raw
    second.assert_not_called()
