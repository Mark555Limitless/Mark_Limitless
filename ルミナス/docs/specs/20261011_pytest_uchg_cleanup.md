# 20261011_pytest_uchg_cleanup

> **状態: 実施済み（2026-10-11、Codex 341 秒・終了 0 → pytest 341 passed・4 skipped・警告 0 → Opus 審査 APPROVE）。** 審査の軽い指摘のうち、根がリンクのときの試験の強化と `__wrapped__` が無いときの skip は未対応（HANDOVER）。

## 目的
Mac で pytest を流すたびに出る警告 61 件（`(rm_rf) error removing …`）を無くす。原因は、全体停止の印の写し（`data/.luminous_halt`）に付いた `uchg`（変更禁止の属性）が外れないまま一時フォルダに残り、pytest が毎回消そうとして失敗していること。残った分を次の実行で自動で外し、今後も試験の後に残らないようにする。

## 触ってよいファイル
<!-- ALLOWED -->
tests/conftest.py
tests/test_mac_compat.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出し・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `tools/`・`orch/`・`.claude/` の変更（印に `uchg` を付ける側は正しい。直すのは試験の後片付けだけ）
- 既存の試験の期待値・既存の fixture（`tests/test_tools.py` の `_unlock_flags`・`proj`、`tests/test_mac_compat.py` の `proj`）の変更。重なっても害が無いので残す
- 一時フォルダの中身を pytest 以外の手段で消すこと（`shutil.rmtree` などで `garbage-*` や `pytest-<番号>` を消さない。属性を外すだけにし、消すのは pytest 自身の片付けに任せる）
- 一時フォルダの外のファイル、リンクの先のファイルの属性を変えること

## 背景（現象・再現手順・実測 2026-10-11 Mac）
- `.venv/bin/python -m pytest tests -q` → 323 passed・4 skipped・**61 warnings**。61 件はすべて `PytestWarning: (rm_rf) error removing <一時フォルダの根>/garbage-<uuid>/…`
- 残っているのは 15 個の `garbage-<uuid>/<試験名>/ルミナス/data/.luminous_halt`（`ls -lO` で `uchg`）。試験名は `test_luminous_halt_*`・`test_halt_terminated_impl_wrap*`・`test_halt_eraser_env_mismatch_0`・`test_halt_wrapper_launched_fro0`。15 個 × 4 階層（印・`data`・`ルミナス`・試験のフォルダ）＋ `garbage-*` 自身 = 61
- 中のフォルダの日時は 10-11 08:18。各 fixture に `_unlock_flags`（`chflags -R nouchg`）が入る前の実行の残り。**今のコードで全件流した直後の新しい `pytest-<番号>` には `uchg` は 1 つも残っていない**（実測）。つまり今の不具合は「過去の残りが自動で片付かない」ことと「試験が途中で止められた（Ctrl+C・時間切れ・強制終了）ときに teardown が走らず同じことが起きうる」こと
- pytest は実行のたびに、一時フォルダの根（`<システムの一時フォルダ>/pytest-of-<ユーザー名>`）の古い `pytest-<番号>` を `garbage-<uuid>` に改名してから消し、消せなかった `garbage-*` も次の実行で消し直す。`uchg` のファイルは消せず、その親も消せないので、同じ警告が毎回出る
- 一時フォルダの根は同じユーザーのすべての pytest（Fable5 AI NEWS Select の試験を含む）で共有されている。この警告は向こうの試験の出力にも出る。向こうのファイルは変えない（不変条件 6）ので、こちらの印だけを狙って片付ける
- Mac の `chflags` で付く `uchg` は、Python では `os.lstat(p).st_flags & stat.UF_IMMUTABLE` で見られ、`os.chflags(p, flags & ~stat.UF_IMMUTABLE, follow_symlinks=False)` で外せる（Linux には `os.chflags` が無い）

## 変更
1. `tests/conftest.py` に、属性を外す補助関数を 2 つ足す。どちらも `os.chflags` が無い環境（Linux）では何もせずに戻る。例外は外へ出さない（後片付けの失敗で試験を落とさない。ただし黙って握りつぶさず、外せなかった数を返す）
   - `_clear_immutable(root) -> int`: `root` の下を、**リンクをたどらずに**（`os.walk(..., followlinks=False)` と `os.lstat`）歩き、`UF_IMMUTABLE` が付いた項目（ファイル・フォルダ・リンク自身）からその 1 ビットだけを外す（ほかの属性は残す）。`root` 自身がリンクなら何もしない。戻り値は外せなかった数
   - `_sweep_stale_halt_markers(root) -> int`: pytest の一時フォルダの根 `root` の**直下の `garbage-*` で、リンクでない本物のフォルダ**だけを歩き（リンクはたどらない）、**名前が `.luminous_halt` で親のフォルダの名前が `data` の項目**からだけ `UF_IMMUTABLE` を外す。`pytest-<番号>` には触らない（同時に走っている別の pytest の試験が `uchg` を確かめている最中かもしれないため）。`root` がリンク・フォルダでない・自分の所有でない（`st_uid != os.getuid()`）なら何もしない。戻り値は外せなかった数
2. `tests/conftest.py` の autouse の `isolated_env` の `yield` の後で `_clear_immutable(tmp_path)` を呼ぶ（どの fixture を使う試験でも、teardown で必ず外れる）
3. `tests/conftest.py` に `pytest_sessionstart(session)` を足し、pytest が一時フォルダを作って古いものを片付ける**前に** `_sweep_stale_halt_markers` を呼ぶ。根の求め方は pytest と同じにする: `--basetemp` が指定されていれば何もしない（その場合 pytest は番号付きの片付けをしない）。それ以外は `Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve() / f"pytest-of-{ユーザー名}"`（ユーザー名は `getpass.getuser()`、失敗したら `"unknown"`）。根を求める部分は `_pytest_temproot(config) -> Optional[Path]` として切り出す（試験から呼ぶため）。これで、今残っている 15 個は実装後の最初の実行で外れ、同じ実行の pytest 自身の片付けで消える
4. Python 3.9 で動く書き方にする（`Optional` は `typing` から。`X | None` は使わない）

## テスト（`tests/test_mac_compat.py` の末尾。陽性・陰性・境界値）
Mac でだけ意味があるものは `@pytest.mark.skipif(not hasattr(os, "chflags"), reason=…)`。各試験は `try/finally` で、自分が付けた `uchg` を最後に必ず外す（試験自身が残りを作らない）。
1. `_clear_immutable`: `tmp_path/root/t/ルミナス/data/.luminous_halt` と、`root` の下のフォルダ 1 つに `uchg` を付ける → 呼ぶと両方外れ、戻り値は 0。ほかの属性（`UF_NODUMP` など、付けられるもの 1 つ）は残る
2. `_clear_immutable` はリンクをたどらない: `tmp_path/outside/victim` に `uchg`、`root/link -> outside/victim` → 呼んだ後も `victim` の `uchg` は残る。`root` 自身がリンクのときも、リンク先の `uchg` は残る
3. `_sweep_stale_halt_markers`: 偽の根 `tmp_path/fake_root` に次を作り、それぞれ `uchg` を付ける → 呼んだ後
   - `garbage-a/t0/ルミナス/data/.luminous_halt` → 外れる
   - `garbage-a/t0/ルミナス/data/other.txt`・`garbage-a/t0/.luminous_halt`（親が `data` でない）→ 残る
   - `pytest-7/t1/ルミナス/data/.luminous_halt` → 残る
   - `garbage-lnk -> tmp_path/elsewhere`（`elsewhere/data/.luminous_halt` に `uchg`）→ 残る
4. `_sweep_stale_halt_markers` は、根がリンク・無い・ファイルのとき何もせず 0 を返す
5. `os.chflags` が無いとき（`monkeypatch.delattr(os, "chflags", raising=False)`）、2 つの補助関数は例外を出さず 0 を返す（どの OS でも走る）
6. `_pytest_temproot`: `--basetemp` があれば `None`。`PYTEST_DEBUG_TEMPROOT` を一時フォルダに向ければ、その下の `pytest-of-<ユーザー名>` を返す（`config` は `option.basetemp` だけを持つ簡単な偽物でよい）

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）。**Mac では、実装後の 1 回目で警告の `(rm_rf) error removing` が 0 件になり、終わった後に `find "${TMPDIR%/}/pytest-of-$(id -un)" -flags +uchg` が空**（司令塔が確かめる）
- `git diff --stat` が ALLOWED のファイルだけ
- 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）では、特に「リンクをたどらないこと」「`pytest-<番号>` と他のプロジェクトのファイルに触らないこと」「`UF_IMMUTABLE` 以外の属性を変えないこと」「消すのは pytest に任せていること」を名指しで確かめる
- 最後に変更ファイル・要点3行・未解決の点
