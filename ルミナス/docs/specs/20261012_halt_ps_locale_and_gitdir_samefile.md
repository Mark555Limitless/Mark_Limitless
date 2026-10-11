# 20261012_halt_ps_locale_and_gitdir_samefile

> **状態: 実施済み（2026-10-12、Codex 661 秒・終了 0 → pytest 357 passed・5 skipped・test-hooks 247 passed → Opus 審査 APPROVE）。** 審査の軽い指摘 6 件（試験の強化だけ）は未対応（HANDOVER）。背景の「アプリの Bash からは届かない」は、ラッパーを日本語を含む絶対パスで起動したときだけだった（相対パスの起動なら直す前でも届く。HANDOVER で訂正）。

## 目的（1〜3行）
Mac の実地確認（2026-10-11・10-12）で見つかった 2 つのずれを直す。
1. 〔中〕全体停止 `tools/luminous_halt.sh on` をロケール C のシェル（Claude Code アプリの Bash）から打つと、`ps` が日本語のパスをエスケープして出すため、実行中の Codex のラッパーに TERM が届かない。
2. 〔軽〕`tools/scope_check.py` の `_is_real_git` が、大文字小文字を区別しないボリュームで、同じ `.git` を綴りの違いで「別物」と判定する。

## 触ってよいファイル
<!-- ALLOWED -->
tools/luminous_halt.sh
tools/scope_check.py
tests/test_tools.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き・実際の外部 API 呼び出し・上記以外のファイル・リポジトリ内のファイルへの実行権限の付与・リポジトリ内でのリンクや FIFO の作成（試験が `tmp_path` の中に実行できる偽の `ps` やリンクを作るのはよい。既存の試験も偽の codex を作っている）
- `tools/_codex_common.sh`・`tools/codex_impl.sh`・`tools/codex_opinion.sh` の変更（`_codex_common.sh` の `ps` は `-o etime=` だけで、パスを照合していない。ロケールの影響を受けないので直さない）
- 既存の試験の期待値の変更・既存の試験の削除。`_halt_cmd` などの補助関数に引数を足すのはよい（既定値で今と同じ動きにする）
- TERM を送る条件を緩めること（照合の対象・時刻の突き合わせ・bash であること・PID の検査は今のまま。変えるのは `ps` を呼ぶときのロケールだけ）
- `luminous_halt.sh` 全体のロケールを変えること（`export LC_ALL=…` や先頭での代入をしない。理由の表示・ほかのコマンドの動きを変えないため。変えるのは照合に使う `ps` の呼び出しだけ）

## 背景（現象・再現手順・関連する決定）
### 1. ps のロケール（tools/luminous_halt.sh の term_codex）
- `term_codex` は、ロックの持ち主の PID の引数を `ps -o command= -p <PID>`（空なら `-o args=`）で取り、2 語目（ラッパーの脚本のパス）を `cd … && pwd -P` で実パスにして `"$PROJ_REAL/tools/codex_impl.sh"`・`"$PROJ_REAL/tools/codex_opinion.sh"` と比べている（一致したときだけ TERM）
- Mac の `ps` は、ロケールが C だと非 ASCII のバイトを `M-fM^O…` の形にエスケープして出す（Linux の procps は `?` に置き換える）。ルミナスの根のパスには「Claude提供用」「ルミナス」が入るので、ロケール C では 2 語目が実在しないパスになり、一致しない → **TERM を送らない**（安全側。印はでき、ラッパーは Codex が終わった後に印を見て止まる。最長で Codex の 1 回分＝5〜15 分遅れる）
- Claude Code アプリの Bash は `LANG`・`LC_ALL`・`LC_CTYPE` が空（ロケール C）。Mark の端末は UTF-8 のロケールなので届く。2026-10-12 に使い捨ての写しで実測: 端末（UTF-8）から on → 届いた／アプリの Bash（C）→ 届かない／アプリの Bash で `ps` だけを `LC_ALL=en_US.UTF-8` にする → 届いた
- Mac には `en_US.UTF-8` と `C.UTF-8` が両方ある（`locale -a`）。Linux（クラウドの試験環境）には `en_US.UTF-8` が無いことが多く、`C.UTF-8`（`C.utf8`）はたいていある。存在しないロケールを `LC_ALL` に入れると `ps` は C で動く（エスケープされる → 一致しない → 送らない）
- 試験の `proj`（`tmp_path / "ルミナス"`）は既に日本語のパスだが、pytest の Python は起動時にロケール C を UTF-8 へ強制し、子へ `LC_CTYPE` を渡すので、今の試験ではこの不具合が出ない。試験では `LC_ALL=C` を明示する

### 2. _is_real_git（tools/scope_check.py）
- `_is_real_git(full, real_git)` は `os.path.realpath(full) == real_git` の文字列比較。`real_git` は `codex_impl.sh` が `git rev-parse --absolute-git-dir` で求めた GITDIR を `os.path.realpath` したもの
- 大文字小文字を区別しないボリューム（Mac の既定の APFS）で、作業フォルダを実際と違う綴り（例: 実際は `Lum`、打ったのは `lum`）で開くと、git は実際の綴り（`…/Lum/.git`）、Python の `realpath` は打った綴り（`…/lum/.git`）を返す。同じフォルダなのに一致せず、本物の `.git` が「入れ子の .git」として扱われる（`snapshot` の比較・`quarantine_git` の移動の対象になる＝誤って違反・移動の側に倒れる）。Unicode の正規化（NFC/NFD）の違いでも同じことが起きうる
- 2026-10-11 の Mac の確認（HANDOVER §8.6）で、綴りのずれを実測。今の Mac の作業フォルダでは論理パスと実パスが同じなので、実害はまだ出ていない

## 変更（番号付きで具体的に）
1. `tools/luminous_halt.sh` の `term_codex` で、ラッパーかどうかの照合を、`ps` のロケールを変えて最大 3 回試す。順番は「(a) 引き継いだロケールのまま（今と同じ呼び方。`LC_ALL` を空文字で渡すことも含め、環境を変えない）→ (b) `LC_ALL=en_US.UTF-8` → (c) `LC_ALL=C.UTF-8`」。**どれか 1 回でも照合（bash であること・2 語目の実パスがルミナスのラッパーであること）に通れば**、その後は今と同じ（時刻の突き合わせ → TERM）。ロケールは `LC_ALL=… ps …` のように `ps` の呼び出しにだけ付ける
   - (a) で引数が取れない（空）ときは、今と同じく「動いていないため TERM は送りません」で戻る（(b)(c) は試さない）
   - (b)(c) で引数が取れない（空）ときは、その回を飛ばす
   - 3 回とも照合に通らなければ、**(a) のときの理由**（今と同じ文言: 「ラッパー（bash）ではない」「ラッパーの形でない」「tools/codex_impl.sh・codex_opinion.sh ではない」）を表示して送らない（戻り値 0。今と同じ）
   - 照合の中身（`set -f; set -- $args; set +f` で分ける・先頭の語の名前が `bash`・2 語目が絶対パスでなければ `PROJ` を基に解く・`-` で始まるか空なら形でない・`cd … && pwd -P` で実パスにして比べる）は変えない。照合の部分を関数に切り出してよい（例: 引数の文字列を受け取り、通れば 0、通らなければ理由を標準出力に出して 1）。関数の中で `set --` を使うときは、関数の外の位置引数を壊さないこと
   - `ps -o command=` が空のときに `-o args=` を試す今の振る舞いは、各ロケールの回でも同じにする
   - 先頭のコメント（ファイルの冒頭か `term_codex` の上）に、なぜロケールを変えて試すのか（ロケール C の `ps` は非 ASCII をエスケープする・アプリの Bash はロケール C・Linux には `en_US.UTF-8` が無いことがある・どのロケールでも照合の条件は同じで、緩めていない）を日本語で 2〜4 行書く
   - Mac の `/bin/bash` 3.2 で動くこと: 変数名の直後に非 ASCII の文字を続けるときは `${VAR}` と書く（`$pid）` は不可。bash 3.2 は UTF-8 のロケールで高位バイトを変数名に含め、`set -u` で落ちる）。連想配列・`${var,,}`・`mapfile` は使わない
2. `tools/scope_check.py` の `_is_real_git` を、文字列比較から「同じファイルか」（`os.path.samefile(full, real_git)`）の比較に変える
   - 今の条件（`real_git` が空でない・`full` がリンクでない）は残す
   - `os.path.samefile` が `OSError`（無い・権限が無いなど）を出したら `False`（本物ではない側＝検査する側に倒れる）
   - `snapshot`・`quarantine_git` の `real_git = os.path.realpath(real_gitdir) if real_gitdir else ""` はそのままでよい
   - 関数の上に、なぜ samefile か（大文字小文字・NFC/NFD を区別しないボリュームで、git の綴りと Python の realpath の綴りがずれる）を 1〜2 行のコメントで書く
   - Python 3.9 で動く書き方

## テスト（陽性・陰性・境界値。外部 API はモック）
`tests/test_tools.py` に足す（全体停止の試験の近く・`_is_real_git` は `test_scope_check_git_name_is_case_insensitive` の近く）。試験が作った `uchg` は既存の fixture（`_unlock_flags`）が外すので、`proj` を使う試験はそのままでよい。

### 1. ps のロケール
試験用の環境は `env_for(proj, "x")` を基に、`LANG`・`LC_ALL`・`LC_CTYPE`・`LC_MESSAGES` などの `LC_*` を取り除いてから `LC_ALL=C` と `LANG=C` を入れる（アプリの Bash と同じ。pytest が子へ渡す `LC_CTYPE` を打ち消すため）。`_halt_cmd` に `extra_env=None` のような引数を足して使ってよい（既定では今と同じ）。
1. **陽性（C のロケールから届く）**: `proj`（日本語のパス）で `codex_impl.sh` を `sleep` の偽の codex で起動（既存の `test_halt_terminated_impl_wrapper_exits_7` と同じ形）→ 起動を待って、**ロケール C の環境で** `luminous_halt.sh on` → 戻り値 0・「TERM を送りました」・ラッパーは 7 で終わる・偽の codex の sleep 30 を待たない（25 秒未満）・ロックが消える・違反の印が無い・印は残っていて「再作成」を含まない。`locale -a` に `en_US.UTF-8`・`en_US.utf8`・`C.UTF-8`・`C.utf8` のどれも無い環境では skip（理由を書く）
2. **陰性（UTF-8 のロケールが使えない環境では今と同じく送らない）**: `tmp_path` の中に偽の `ps` を作る（中身は、本物の `ps`＝試験の開始時に `shutil.which("ps")` で求めた絶対パスを、`LC_ALL=C` を付けて `exec` するだけの `#!/bin/sh` の脚本。実行権限を付ける）。そのフォルダを `PATH` の先頭に置き、ロケール C の環境で `on` → 戻り値 0・「送りません」を含み「送りました」を含まない・その時点でラッパーはまだ動いている。その後、試験がラッパーに SIGTERM を送って終わらせ、ラッパーは 7（印があるため）。`finally` でラッパーが残っていれば kill
3. **陰性（ロケールを変えても無関係のプロセスには送らない）**: `proj` の中に、日本語のパスの下の別の脚本（例: `tmp_path` 側の `proj[0] / "tools" / "other_sleep.sh"`。中身は `sleep 30`）を `bash` で起動し、その PID と今の時刻を `data/codex_runs/.lock/owner` に書く → ロケール C の環境で `on` → 戻り値 0・「送りません」・「送りました」を含まない・0.3 秒後もそのプロセスが生きている。`finally` で kill
4. **既存の試験**（`test_halt_terminated_impl_wrapper_exits_7`・`test_halt_wrapper_launched_from_parent_dir_detects_erased_marker_without_term`・`test_luminous_halt_does_not_term_bad_owner` など）は変えずに通ること

### 2. _is_real_git
`importlib` で `tools/scope_check.py` を読み込む（既存の `test_scope_check_git_name_is_case_insensitive` と同じ形）。
1. **陽性（大文字小文字違いのパスで真）**: `tmp_path / "Lum" / ".git"` を作る。`tmp_path / "lum"` が存在する（大文字小文字を区別しないボリューム）ときだけ実行し、区別するボリュームでは skip。`sc._is_real_git(str(tmp_path / "lum" / ".git"), os.path.realpath(str(tmp_path / "Lum" / ".git")))` が `True`。あわせて `sc.snapshot(str(tmp_path / "lum"), str(tmp_path / "Lum" / ".git"))["files"]` に `.git` が入らない（本物として比べない）
2. **陽性（境界・NFC/NFD）**: NFC の名前（例: `unicodedata.normalize("NFC", "ルミナス")`）のフォルダの下に `.git` を作り、NFD の綴りでも存在するとき（正規化を区別しないボリューム）だけ、NFD の綴りの `full` で `True`。存在しなければ skip
3. **陰性**: 別のリポジトリの `.git`（`tmp_path / "a" / ".git"` と `tmp_path / "b" / ".git"`）→ `False`／本物の `.git` を指すリンク（`tmp_path / "c" / ".git" -> 本物`）→ `False`／存在しない `full` → 例外を出さず `False`／`real_git` が空 → `False`
4. **陰性（区別するボリューム）**: `tmp_path / "Lum2" / ".git"` と `tmp_path / "lum2" / ".git"` を両方作れたとき（区別するボリューム）だけ、互いに `False`。作れなければ skip
5. `quarantine_git` が、大文字小文字違いの綴りで渡された本物の `.git` を移さないこと（1 と同じ skip 条件。`before` は `{"files": {}}` でよい。戻り値の「移した」が空で、`tmp_path / "Lum" / ".git"` が残る）

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告。skip の数と理由も）
- `bash scripts/test-hooks.sh` が全件通る（司令塔が確かめる）
- `git diff --stat` が ALLOWED のファイルだけ
- 新しい試験 1-1（C のロケールから届く）が、**直す前の `tools/luminous_halt.sh` では落ちる**こと（司令塔が使い捨ての写しで確かめる）
- 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）では、特に「TERM を送る条件が緩んでいないこと（ロケールを変えた回でも照合の条件は同じ・(a) の理由の表示・(a) で空なら戻る）」「ロケールの変更が `ps` の呼び出しだけにとどまること」「bash 3.2 で動くこと（`${VAR}`・位置引数）」「samefile の例外が本物でない側に倒れること」「リンクを本物とみなさないこと」を名指しで確かめる
- 最後に変更ファイル・要点3行・未解決の点
