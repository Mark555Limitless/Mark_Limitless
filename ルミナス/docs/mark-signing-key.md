# Mark の承認タグ用の鍵 — 手順書 v0.8（Opus の反証審査 APPROVE、2026-10-10）（鍵の作成・設定・署名は Mark だけ。検証は司令塔も行う）

> 背景: 許可台帳（`docs/proposals/20261008-autonomy-grants.md` §5-3）の Mark の決定（2026-10-10）「署名つきの承認タグ。鍵は Touch ID などで守られたもので、いったん様子を見る」。
> 目的: 台帳の行（保護ファイル）を「Mark 自身の操作」でだけ変えられるようにする。**使うたびに Mark の操作が要る鍵**で git のタグに署名し、同じ Mac で動く AI（Claude Code・Codex）も別の機械も、その署名を作れない・Mark の承認を別の中身に流用できないようにする。
> 事実確認: 2026-10-10 に一次情報（OpenSSH・git・Secretive v4.0.0 のソース・Apple・Yubico・GitHub の文書）で確認。v0.1〜v0.7 の反証審査（Opus）の指摘 21 件＋11 件＋7 件＋4 件＋6 件＋3 件＋2 件を反映した。確認できなかった点は §8。出典の信頼度: ①一次情報 ②査読・第三者 ③技術メディア ④個人 SNS・Issue ⑤動画・個人ブログ。
> **鍵・パスフレーズ・PIN・ログインのパスワードをチャット・ファイル・コミットに書かない。** この文書に載るのは公開鍵の指紋だけ。

## 0. やること（5 行）と、要るもの

1. **AI が動いていない別の管理者ユーザー**（例: `mark-admin`）を Mac に作る。root を使う手順と「本物か」の確認は、すべてそのユーザーにログインして行う（Mark のユーザーの端末は AI が `~/.zshrc` を書き換えられるので、`sudo`・`cat`・`ls` の表示も横取りされうる。§1）。**別ユーザーで初めて Terminal を開く前に、Finder で `/usr/local` と `/usr/local/bin` の所有者が system（root）で Mark に書き込みが無いことを確かめる**（Mark に書き込みがあれば Terminal を開かずに止まり、司令塔に知らせる。§3.1-0）
2. Secretive を**ブラウザで GitHub の Releases から**入れ、別ユーザーで開発元の署名（Team ID `Z72PRUAWF6`）を確かめてから、Mark のユーザーに戻ってすぐに Secure Enclave の鍵を「認証を要求する」で作る（§3.1）
3. 公開鍵の 1 行を、別ユーザーの sudo で root 所有の場所に置いて確かめ、同じ公開鍵を**ブラウザの GitHub の Settings** で Signing Key に登録し（gh は使わない）、指紋を紙に控える（§3.2）
4. 承認のたび: コミットの 40 桁のハッシュを控える → 変更をブラウザの GitHub で、**控えてある前のハッシュ**からの差分として読む → そのハッシュにタグを署名（Touch ID は `git tag -s` の直後の 1 回だけ）→ 検証して指紋を目で確かめる → push → GitHub でタグに **Verified** が付き、署名者が自分で、指紋と **40 桁全部**が控えと一致し、Signing Key が自分の 1 つだけであることを確かめる（§3.4）
5. Touch ID に応えた後に失敗したら打ち直さない。司令塔に知らせて鍵を作り直す（§3.4-6）
6. 本番の前に、試しの鍵（`luminous-trial-*`）で一通りやってみて、後片付けする（§3.5）

要るもの: Touch ID 付きか M1 以降の Mac、macOS 15 以降、AI が動いていない別の管理者ユーザー（システム設定 → ユーザとグループ で作る。パスワードは Mark のユーザーと別にする）、git 2.34 以降と OpenSSH 8.8 以降（`git --version`・`ssh -V` で確認）。所要は初回 30〜60 分、以後は承認 1 回 5 分程度（見込み）。

## 1. 守れること・守れないこと（先に）

**守れる**: 鍵の秘密は Secure Enclave の中にあり、署名のたびに Touch ID が要る。**AI は署名を作れず、鍵は複製できない**ので別の機械の AI も作れない（Secretive の README・Apple の文書: ①）。

**守れない（運用で補う）**:
- **鍵を作る時点の Secretive が本物でなければ、以後の確かめはすべて通ってしまう**（偽物は「認証なし」の鍵を作りながら画面には「認証を要求する」と出せる）。Homebrew の本体と入手先は Mark の所有する `/opt/homebrew` にあり AI が書き換えられるので、`brew install` では入れない。GitHub の Releases から入れ、`spctl` で開発元と公証を確かめ（§3.1）、間を空けずに鍵を作る。作った後にアプリを差し替えられても、作った鍵は Secure Enclave の制約（`userPresence`）とキーチェーンの開発元ごとの区切りで守られる
- **Mark のユーザーの端末は AI から独立していない。** 同じユーザーで動く AI は、端末のシェルが読むもの（`~/.zshrc` の関数・別名・PATH・ZLE ウィジェット、リポジトリの `.git/config`、`~/.gitconfig`、Mark の所有する `/opt/homebrew/bin`）を書き換えられる。だから端末の表示だけでは確かめにならない。**`sudo` も横取りされうる**: Mark が `sudo` を打ってパスワードを入れると、同じ端末に記憶された資格（既定 5 分）で AI の命令も root で走り、`/etc/luminous/allowed_signers` に AI の鍵を足す・sudoers を変えることができ、偽の `sudo` でログインのパスワードを盗むこともできる。直後の `cat`・`ls` の表示も偽れる。→ **root を使う手順と、本物かどうかの確認は、AI が動いていない別の管理者ユーザーにログインして行う**（AI は Mark のユーザーで動くので、別ユーザーの `~/.zshrc` には書けない。`/Applications` と `/etc` はユーザー間で共通）。ただし **`/usr/local/bin` が Mark の所有（Intel Mac の Homebrew）だと、別ユーザーの Terminal も開いた時点で乗っ取られうる**: macOS 標準の `/etc/zshrc` は、Mark が PATH を直すより前に `locale` を PATH（先頭が `/usr/local/bin`）から探して実行するので、AI が置いた偽の `locale` が別ユーザーの権限で走り、その `~/.zshrc` を書き換えられる。だから別ユーザーで Terminal を開く前に Finder（表示は AI が偽れない）で `/usr/local` と `/usr/local/bin` の所有者を確かめ、Mark に書き込みがあれば**進めない**（§3.1-0）。PATH の決まり（§3）は二重の守り。鍵の作成と署名は Mark のユーザーでよい（§3.4 の GitHub の確かめで守られる）。git について具体的には:
  - a. 署名のプログラムの差し替え（`.git/config` に `gpg.ssh.program`）: Mark の `git tag -s` の Touch ID を、AI が選んだ中身（別のコミットを指すタグ）の署名に使われる。Mark のタグは検証で失敗し、打ち直すと 2 回目は通る。AI の手元に Mark の鍵で署名されたタグが 1 つ残る
  - b. git そのものの差し替え（`~/.zshrc` の関数や PATH）: Mark が打った `git tag -s` を、差分を見たのとは別のコミットに付けられる。Touch ID は 1 回、`verify-tag` の出力も本物
  - c. 差分の表示の差し替え（`.gitattributes`・`.git/config` の textconv・外部 diff・pager）: 台帳の行の追加を隠せる
  - → 対策（§3.4）: **確かめは端末の外（ブラウザの GitHub）で行う**。タグは**完全なハッシュを指定して**付ける。署名と検証の設定は設定ファイルに頼らず `-c` でコマンドに直接書く。差分は `git --no-pager diff --no-ext-diff --no-textconv`。**1 回の `git tag -s` で Touch ID は 1 回だけ**。2 回目の求めや Secretive の「複数の求めが保留中（Multiple authenticated requests are pending）」が出たら全部拒否する。Touch ID に応えた後に失敗したら打ち直さず、鍵を作り直す（allowed signers を新しい鍵だけにすれば、古い鍵で作られたタグは全部無効になる。応える前の失敗は直して打ち直してよい。§3.4-6）
- 承認の画面は「署名してよいか」を聞くだけで、何に署名するかは見せない。**署名を求められてよいのは §3.4 の手順 3（`git tag -s`）の直後の 1 回だけ。** 手順 1・2・4・5 のコマンドの後や、手順の外で出た求めはすべて拒否する（包み替えられた git は `rev-parse` の直後にも求めを出せる）。誤って承認したら鍵を作り直す（§3.4-6）
- Secretive の画面に出る「求めたアプリ」の名前は、プロセスの親をたどった最初の GUI アプリで、AI は `open -a Terminal x.command` で Terminal.app から求めたように見せられる（`SigningRequestTracer.swift`: ①）。表示は目安にすぎない。AI の CLI（claude・codex）は Terminal.app 以外の端末アプリで動かすと見分けやすい
- **身に覚えのない「管理者のパスワード」の画面には入力しない**（AI は `osascript … with administrator privileges` で、本物の認証画面を好きな説明文つきで出せる）。より強くするなら、Mark の普段のユーザーを管理者でなく一般ユーザーにする
- 「認証を要求する」はログインのパスワードでも通る（Apple の `userPresence`: ①）。より強い「現在の生体認証」も選べる（§3.1）。AI にログインのパスワードや画面操作の権限（アクセシビリティ）を渡さない。システム設定 → プライバシーとセキュリティ → アクセシビリティに、ターミナルや Claude のアプリが入っていないことを確かめる
- 検証（`git verify-tag`）を AI（司令塔）が実行する場合、AI が `git` や PATH を差し替えれば結果は偽れる。許可台帳の提案は guard-protected で鍵と署名の操作（`git tag`・`git config gpg.*`・`user.signingkey`・`gpg.ssh.allowedSignersFile`・`ssh-keygen -Y sign`・`ssh-add`・`.git/config` の編集）を止めることにしているが、**この止め方はまだ入っていない**（台帳の適用の差分で入れる）。確かめの基準は、Mark が GitHub の画面で見たハッシュと、紙に控えた指紋
- より強い選択（任意）: 署名も別ユーザーで行う（そのユーザーに Secretive と GitHub から取り直したクローンを置く）。AI のユーザーと分かれるので、上の a〜c が成り立たない。月に 1 回程度、別ユーザーで `/etc/luminous/allowed_signers` の中身（1 行・自分の鍵）を見直す

## 2. 方式の比較（事実確認の結果）

| 方式 | 毎回の本人操作 | 同じ Mac の別プロセスが黙って署名できるか | 鍵の複製 | 必要なもの・費用 | 出典 |
|---|---|---|---|---|---|
| **(a) Secretive（Secure Enclave）** 推奨 | 「認証を要求する」: 求めごとに Touch ID／Apple Watch／パスワード。「現在の生体認証」: Touch ID のみ | 既定では不可（求めごとに認証、使い回さない）。ただし通知の「ロックを解除したままにする（Leave Unlocked。1 分・5 分・1 時間・24 時間）」を押すとその間はどのプロセスでも署名できる | **不可**（書き出せない。Mac を替えたら作り直し） | Secretive 4.0.0（2026-09-21 公開、最低 macOS 15.0）。Touch ID 付きか M1 以降の Mac。無料（MIT） | README・FAQ・ソース・Apple の文書: ① |
| (b) 1Password の SSH agent | Touch ID で解錠・承認 | **既定ではアプリ単位で承認が続く**。設定で厳しくできるが原文未確認 | **可**（vault に保存され同期） | 有料。最低 macOS 不明 | 公式文書の原文は未取得。本件には**使わない** |
| (c) FIDO2 のハードウェアキー（`ed25519-sk`／`ecdsa-sk`、`-O verify-required`） | 署名のたびに**物理タッチ**。`verify-required` なら PIN も | 不可（タッチは物理操作） | **不可**（秘密鍵はキーの中） | OpenSSH 8.4 以降・git 2.34 以降。**macOS 標準の ssh は FIDO 非対応で Homebrew の openssh が要る**（①④。macOS 26 で変わったかは不明）。約 $29〜58（③）。**弱点**: Homebrew の `ssh-keygen` は Mark の所有する `/opt/homebrew` にあり、検証も署名も AI が差し替えられる（SIP では守られない） | OpenSSH の man とソース、Yubico の手順: ① |
| (d) パスフレーズ付き ed25519 鍵（agent に載せない） | 署名のたびにパスフレーズ入力 | agent に載せなければ不可。**弱点**: 差し替えた `ssh-keygen` にパスフレーズを盗まれると、以後は黙って署名される。同じ Mac の AI に対しては目的を満たさない | **可**（ファイル） | 追加ソフトなし | OpenSSH の man: ① |

推奨: **(a) Secretive**。費用なし、鍵が複製できない、求めごとに本人認証、鍵の種類が ECDSA-256（既定）で macOS 標準の `/usr/bin/ssh-keygen`（SIP で守られる）で検証できる（ML-DSA を扱えるかは未確認）。(c) は Mac の買い替えに強いが、検証の道具を守れない。(d) は次善にもならない。

## 3. 手順（(a) Secretive。git のコマンドは Mark のユーザーの Terminal.app で、**ルミナスのフォルダ**（git の根はその一つ上）で打つ。**sudo と「本物か」の確認は別の管理者ユーザーで**。Mark のユーザーでは sudo を打たない。**別ユーザーの Terminal を開いたら、最初に `export PATH=/usr/bin:/bin:/usr/sbin:/sbin` を打ち、コマンドは絶対パスで書く**: PATH は全ユーザー共通の `/etc/paths` から来て先頭が `/usr/local/bin`（Intel Mac の Homebrew では Mark の所有）なので、別ユーザーでも偽の `sudo`・`cp`・`ls`・`cat` を置かれうる。sudo は打った人の PATH でコマンドを探す）

### 3.1 導入と鍵の作成（Mark）
0. **別ユーザーで Terminal を開く前に（Finder で）**: Mark のユーザーのまま Finder で「移動 → フォルダへ移動 → `/usr`」を開き、`local` を選んで「情報を見る」→「共有とアクセス権」で、所有者が **system** で、Mark（と staff・everyone）に**書き込みが無い**ことを見る。次に `/usr/local` を開き、`bin` があれば同じように見る（**`/usr/local` と `/usr/local/bin` の両方**。`/usr/local` 自体を Mark が書けると、確かめた後に AI が `bin` の名前を変えて Mark 所有の `bin` を作れる。今の macOS では `/usr/local` は既定で root の所有）。**Mark に書き込みがあれば、別ユーザーの Terminal を開かずにここで止まり、司令塔に知らせる**（fail-closed。対処の例: `/usr/local/bin` の持ち主を root に戻す（Intel の Homebrew の使い方が変わる）／起動の設定を読まない方法で root の手順を行う（スクリプトエディタの `do shell script … with administrator privileges` は固定の PATH の sh で動くはず。§8 で要確認））。理由は §1
1. **ブラウザで GitHub の Releases（v4.0.0）から入れる**（`brew install` は使わない: §1）。`/Applications` に置いたら、**別の管理者ユーザーにログインし、その Terminal で**本物であることを確かめる（Mark のユーザーの端末は AI が行を書き換えうるので使わない）:
   ```
   export PATH=/usr/bin:/bin:/usr/sbin:/sbin
   /usr/sbin/spctl -a -vv /Applications/Secretive.app
   ```
   3 つを全部満たすこと: 1 行目が `/Applications/Secretive.app: accepted`、`source=Notarized Developer ID`、`origin=…(Z72PRUAWF6)`（`spctl -a` は署名の有効性と公証、つまり中身が改ざんされていないことまで確かめる。`codesign -dv` は情報の表示だけなので確認には使わない。出力の書式は §8）。開発元のチーム ID `Z72PRUAWF6` はソースの `Config.xcconfig` と XPC の署名要件で確認（①）。合わなければ使わない。**確かめたら Mark のユーザーに戻り、間を空けずに手順 2 で鍵を作る**。鍵を作った後にもう一度、別ユーザーで同じ `spctl` を打ち、Secretive の画面に鍵が出ていることを見る（確かめてから作るまでの間の差し替えの確認）
2. Secretive を開き、鍵を作る。名前は例えば `luminous-approval`。**保護のレベル（Protection Level）は「認証を要求する（Require Authentication）」**。保護の強さは作成時に決まり、後から変えられない（`CreationOptions.swift`: ①）
   - より強い選択: 「詳細（Advanced）」→ 保護のレベル「現在の生体認証（Current Biometrics）」。パスワードでは通らない（`.biometryCurrentSet`。Apple: ①）。引き換えに、指紋を足す・消すと鍵が無効になり作り直し、Apple Watch は使えない、Touch ID の無い Mac では使えない。4.0.0 にはこの鍵の求めでパスワード入力の画面を出してしまう表示の不具合があり（修正の PR #845 が main に 2026-10-01 に入ったが、修正版は未公開）、鍵そのものは生体認証を求めるはずだが実機での動きは §8 で「不明」
   - 「詳細 → 鍵の種類」は**既定の ECDSA-256 のまま**（macOS 26 では ML-DSA も出るが、`/usr/bin/ssh-keygen` で扱えるか未確認なので選ばない）
3. **Secretive の設定画面にあるシェルと Git Signing の設定例は使わない**（`~/.zshrc` に `export SSH_AUTH_SOCK=…` を書く案内は AI のシェルも読む。`commit.gpgsign = true` と `~/.gitallowedsigners` は AI のコミットのたびに承認を求める上、AI が書ける場所）。署名するときだけ、コマンドの頭に `SSH_AUTH_SOCK="$HOME/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"` を付ける（§3.4）
4. Secretive の画面で、その鍵の **公開鍵のパス（Public Key Path）** と **SHA256指紋** を見る。指紋は `ssh-keygen -lf <公開鍵のパス>` の `SHA256:…` とも一致することを確かめ、**紙に控える**（公開鍵の指紋は秘密ではない。突き合わせの基準）

### 3.2 検証用の allowed signers を、AI が書き換えられない場所に置く（別の管理者ユーザーで）
1. Mark のユーザーで、公開鍵の 1 行を作って受け渡し用に置く（公開鍵は公開情報。`namespaces="git"` で他用途の署名の流用を防ぐ。`ssh-keygen.1`: ①）:
   ```
   printf 'mark namespaces="git" %s\n' "$(cut -d' ' -f1,2 <公開鍵のパス>)" > /Users/Shared/allowed_signers_luminous
   ```
2. **別の管理者ユーザーにログインし、その Terminal で**置く。**親ディレクトリまで root 所有で、group と other が書けない場所**に（ファイルだけ root 所有でも、親を Mark のユーザーが書けるなら AI がディレクトリごと差し替えられる。Intel Mac の Homebrew は `/usr/local/etc`・`/usr/local/bin` を利用者の所有にする）。`/etc` は `/private/etc` へのリンクで root 所有。**最初に PATH を標準だけにし、コマンドは絶対パスで**。コピーは「読むのは自分の権限、書くときだけ root」にする（`/Users/Shared` は誰でも書けるので、AI がそのファイルを root しか読めないファイルへのリンクにすり替えうる。`sudo cp` はリンクの先を root でコピーしてしまうが、`cat | sudo tee` なら読めずに失敗する）:
   ```
   export PATH=/usr/bin:/bin:/usr/sbin:/sbin
   /usr/bin/sudo /bin/mkdir -p /etc/luminous && /usr/bin/sudo /bin/chmod 700 /etc/luminous   # 確かめるまで root だけが入れる（既にあっても 700 にする。2 回目以降・作り直し・試しの後も同じ）
   /bin/cat /Users/Shared/allowed_signers_luminous | /usr/bin/sudo /usr/bin/tee /etc/luminous/allowed_signers >/dev/null
   /usr/bin/sudo /bin/cat /etc/luminous/allowed_signers                            # ちょうど 1 行で、鍵の種類は ecdsa-sha2-nistp256
   /usr/bin/sudo /usr/bin/cut -d' ' -f3,4 /etc/luminous/allowed_signers | /usr/bin/ssh-keygen -lf -   # 出た SHA256:… が紙の控えと一致すること（長い公開鍵の目視では比べない。先頭の約 52 文字はどの鍵でも同じ）
   # ↑ 1 行・種類・指紋がすべて合ったときだけ、次で誰でも読める形にする。合わなければ /usr/bin/sudo /bin/rm -r /etc/luminous で消して司令塔に知らせる
   /usr/bin/sudo /usr/sbin/chown -R root:wheel /etc/luminous && /usr/bin/sudo /bin/chmod 755 /etc/luminous && /usr/bin/sudo /bin/chmod 644 /etc/luminous/allowed_signers
   /usr/bin/sudo -k
   /bin/ls -ld /private /private/etc /private/etc/luminous /private/etc/luminous/allowed_signers   # すべて root の所有で、group・other に w が無いこと
   ```
   順序の理由: `/Users/Shared` のファイルは AI が「別ユーザー自身なら読めるファイル（例: そのユーザーのログインのキーチェーン）」へのリンクにすり替えうる。最初から 644 で置くと、Mark が異常に気づく前に AI が読める。確かめるまで root だけが読める形にすれば漏れない。
   （`ssh-keygen -lf` に allowed signers の行をそのまま渡すと先頭の名前と namespaces を読み飛ばせず指紋が出ないので、`cut` で鍵の部分だけを渡す。`-lf -` は標準入力。OpenSSH の `ssh-keygen.c`: ①）。終わったら Mark のユーザーに戻って `rm /Users/Shared/allowed_signers_luminous`（`/Users/Shared` は持ち主しか消せないので、別ユーザーでは消せない）
3. **同じ公開鍵を GitHub の Signing Key として登録する**（必須）。**ブラウザの Settings → SSH and GPG keys → New SSH key → Key type を Signing Key、だけで行う。`gh ssh-key add` は使わない**（Signing Key を足す API には署名鍵用の権限が要り、その権限を gh に足すと、キーチェーンの資格を同じユーザーの AI も使えて自分の鍵を Mark のアカウントに足せる。gh のソースで確認: ①。もし足してしまったら外す）。GitHub は SSH 署名のタグにも Verified を付ける（GitHub の文書 "About commit signature verification": ①）。Verified が付く条件（タグを付けた人のメールが GitHub で確認済みのメールであること）は §8 で要確認。登録後、GitHub の画面に出る鍵の指紋が紙の控えと一致し、**Signing Key が自分の 1 つだけ**であることを見る
4. 照合の基準はこの root 所有のファイルと紙の控え。リポジトリにも同じ 1 行を記録として置く（`.claude/allowed_signers`。保護ファイル。**記録用で、検証の設定には使わない**）。`VIRTUAL_MARK.md` §7 に書く指紋も**記録**（検証される HEAD の中にあるので、単独では基準にならない）。どちらも許可台帳の適用の差分（Mark が差分を見て承認）で入れる

### 3.3 git の設定
- **設定ファイル（`~/.gitconfig`・`.git/config`）には何も書かない。** 署名と検証の設定は毎回コマンドに `-c` で書く（`-c` は設定ファイルの値より優先。git の `git.adoc`: ①）。`tag.forceSignAnnotated` も付けない（`-s` を明示するので要らず、余計な承認の求めの元になる）

### 3.4 承認タグの付け方（保護ファイル・台帳の行を変えるたび。Mark）
タグの名前は `luminous-approved-YYYYMMDD-n`（SessionStart の hook が探す名前。README「承認タグによる事後検知」）。**紙の控え**には、承認のたびに「タグの名前・40 桁のハッシュ・日付」を書き足す（次回の差分の起点になる）。
1. **ハッシュを控える**: 司令塔が対象のコミットを push 済みであることを確かめ（push は司令塔の仕事）、ルミナスのフォルダで `git --no-pager rev-parse HEAD` → 40 桁を紙に写す。以後は必ずこの値を使う
2. **変更をブラウザの GitHub で読む**（端末の表示は信用しない）: `https://github.com/Mark555Limitless/Mark_Limitless/compare/<前の承認の 40 桁>..<新しい 40 桁>`（**2 点リーダー**で直接比べる。起点は**紙に控えた前のハッシュ**。タグ名やブランチ名は使わない。GitHub は同じ名前のブランチがあるとブランチを優先し、AI は同名のブランチや署名の無いタグを push できる。3 点リーダーは共通の祖先からの差分なので、承認済みの状態からの「戻し」が出ない。GitHub の文書 "Comparing commits": ①）。compare が開けなければ push が済んでいないので手順 1 へ戻る。読むのは保護ファイルの全体（`CHARTER.md`・`VIRTUAL_MARK.md`・`ROUTINE.md`・`CLAUDE.md`・`AGENTS.md`・`.env.example`・`prompts/ルミナス_最終プロンプト.md`・`.claude/`・`.codex/`・`.githooks/`・`.mcp.json`・`scripts/secret-scan.sh`・`scripts/sync-obsidian.sh`・`scripts/build-final-prompt-docx.mjs`・`package.json`・`package-lock.json`。`restore-charter.sh` の PROTECTED と同じ）。タグはそのコミットの保護ファイル全体を承認する
   - **初めてのタグ**（前の承認が無い）: 保護ファイルの全文を GitHub の画面（そのハッシュのツリー `https://github.com/Mark555Limitless/Mark_Limitless/tree/<40 桁>/ルミナス`）で読む
   - 端末で見るなら `git --no-pager diff --no-ext-diff --no-textconv <前の 40 桁> <新しい 40 桁> -- <保護ファイル>`（表示の差し替えを避ける書き方。それでも基準は GitHub）
3. **署名**（Touch ID はこの直後の 1 回だけ）:
   ```
   SSH_AUTH_SOCK="$HOME/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh" \
   git -c gpg.format=ssh -c gpg.ssh.program=/usr/bin/ssh-keygen -c user.signingkey=<公開鍵のパス> \
     tag -s luminous-approved-YYYYMMDD-1 <40 桁のハッシュ> -m "承認: <要点>"
   ```
   - Secretive の求め（「シークレット “<鍵名>” を使って “<アプリ名>” の要求に署名します」の趣旨。実機の文言は §8）に Touch ID で応える。**2 回目の求め・「複数の求めが保留中」が出たら全部拒否**し、打ち直さず手順 6 へ。「ロックを解除したままにする」は押さない。任意: 通知センターに「…の要求に署名しました」が 1 件だけであることを見る
4. **検証**（その場で。root 所有のファイルと SIP で守られた `ssh-keygen` を明示）:
   ```
   git -c gpg.ssh.program=/usr/bin/ssh-keygen -c gpg.ssh.allowedSignersFile=/etc/luminous/allowed_signers verify-tag --raw luminous-approved-YYYYMMDD-1
   ```
   期待する 1 行目: `Good "git" signature for mark with ECDSA key SHA256:<指紋>`（書式は git の `gpg-interface.c` と OpenSSH の `ssh-keygen.c`: ①）。**`SHA256:` の後が紙の控えと一致**することを目で確かめる。`Good "git" signature with …`＋`No principal matched.` は「署名は正しいが登録の鍵ではない」で失敗 → 手順 6
5. **push と、端末の外での確かめ（3 点とも必須。1 つでも満たさなければ手順 6）**: `git push origin luminous-approved-YYYYMMDD-1` → ブラウザで `https://github.com/Mark555Limitless/Mark_Limitless/releases/tag/luminous-approved-YYYYMMDD-1`（または tags の画面からそのタグ）を開き、
   - (i) タグに **Verified** が付いている（署名の無い同名タグに差し替えられていない）
   - (ii) Verified の詳細に出る**署名者が自分のアカウント**で、SSH の指紋が**紙の控えと一致**する（Mark のトークンを持つ AI が自分の鍵を Signing Key に足していないか。別のアカウントの鍵でも、タグを付けた人のメールが合えば Verified になる。詳細に指紋が出るかは §8 で要確認）。**毎回、ブラウザの Settings → SSH and GPG keys の Signing Key が自分の 1 つだけ**であることも見る（AI が自分の鍵を足していれば AI のタグも Verified になるため）
   - (iii) タグが指すコミットの **40 桁全部**が手順 1 の控えと一致する（画面の 7 桁では足りない。先頭 7 桁を合わせた別のコミットは作れる。コミットのページを開いて 40 桁を見る、または控えの 40 桁をブラウザの検索 Cmd+F に貼る）。API でも確かめられる: `https://api.github.com/repos/Mark555Limitless/Mark_Limitless/git/ref/tags/luminous-approved-YYYYMMDD-1` の `object.sha` → `https://api.github.com/repos/Mark555Limitless/Mark_Limitless/git/tags/<その sha>` の `object.sha`（指すコミット）と `verification.verified`（欄の名前は §8 で要確認）
6. **失敗したとき**:
   - **Touch ID に応える前**の失敗（パスの打ち間違い・push 前で compare が開けない など）: 原因を直して打ち直してよい
   - **Touch ID に応えた後**の失敗（検証が通らない・Verified が無い・指紋や 40 桁が合わない・2 回目の求めが出た・誤って承認した）: 同じコマンドを打ち直さない（1 回目の Touch ID が別の中身に使われた可能性がある）。司令塔に知らせ、§3.1 から鍵を作り直して、次の 4 つを新しい鍵に更新する: `/etc/luminous/allowed_signers`（新しい鍵だけに。**置き直しは §3.2-2 の手順をそのまま**（700 にしてから書き、確かめてから公開）。古い鍵のタグはすべて無効になる）、GitHub の Signing Key（古い鍵を外し新しい鍵を足す）、`.claude/allowed_signers` と `VIRTUAL_MARK.md` §7 の記録（司令塔が差分を出し Mark が承認）、紙の控え。作り直すと古い鍵の承認タグはすべて無効になり台帳は空とみなされる（安全側）ので、**今の承認済みの状態に新しい鍵でタグを付け直す**（§3.4 を最初から。起点は紙に控えた前のハッシュ）

### 3.5 本番の前に試す
試しの鍵（名前 `luminous-trial`）で 3.1〜3.4 を一通り行う（§3.1-1 の本物の確認は試しでも同じ。試しのタグの 40 桁を紙に書くなら「試し」と印を付け、本番の差分の起点には使わない）。**タグの名前は `luminous-trial-YYYYMMDD-1`**（本番の `luminous-approved-*` を使うと SessionStart の hook が最新の承認タグとして拾う）。検証の出力と GitHub のタグの画面（Verified・指紋・40 桁）を見てから、本番の鍵を作る。終わったら 3 つを消す: GitHub 上の試しのタグ（`git push origin :refs/tags/luminous-trial-YYYYMMDD-1` とローカルの `git tag -d`）、試しの Signing Key、`/etc/luminous/allowed_signers` の試しの 1 行（本番の鍵の 1 行だけにする。**置き直しは §3.2-2 の手順をそのまま**）。

## 4. 司令塔（AI）側の検証と、その限界
- 司令塔は、台帳を使う前に `git -c gpg.ssh.program=/usr/bin/ssh-keygen -c gpg.ssh.allowedSignersFile=/etc/luminous/allowed_signers verify-tag --raw <タグ>` を実行し、1 行目が `Good "git" signature for` で始まるタグだけを承認とみなす（**基準は root 所有のファイルを指定した検証が通ること**。提案書 §3.1「有効の条件」）。あわせて指紋が `VIRTUAL_MARK.md` §7 の記録と一致するかを見るが、これは**追加の照合**（記録との食い違いの検知）であり、判定の基準ではない
- 司令塔は、あわせて GitHub の API（上の 3.4-5 の URL）で、そのタグが指すコミットの 40 桁と `verification.verified` を読み、ローカルの `rev-parse <タグ>^{commit}` と一致することも確かめる（ローカルだけの判定にしない）
- 限界: AI が `git`・PATH・出力を差し替える経路は残る。guard-protected による鍵と署名の操作の禁止（`.git/config` の編集も含める）は台帳の適用の差分で入れる。それでも「確認は自己点検で、強制はまだ無い」（提案書）。本当の基準は §3.4 の Mark の GitHub での確認
- 今の `restore-charter.sh` の承認タグの確認は allowed signers を指定していないので、SSH の署名では常に「検証できません」と出る。台帳の適用の差分で `-c gpg.ssh.allowedSignersFile=/etc/luminous/allowed_signers` を付ける（司令塔の宿題）

## 5. 行を消す・狭めるとき
有効の条件は「いずれかの検証済みタグと同じ中身」なので、AI が保護ファイルを**古い承認タグの中身に戻す**と、消したはずの行が生き返る。行を消す・狭めるときは、新しい承認タグに加えて **`state/grants_revoked` に行の ID・日時・理由を 1 行追記してコミットする**（取り消しは追記だけで、誰でもできる。提案書 §3.1 にも反映）。

## 6. 落とし穴（出典つき）
1. 検証の差し替え: `gpg.ssh.program` 未設定なら PATH 上の `ssh-keygen`。git は出力の先頭が `Good` で終了 0 なら成功とみなす（`gpg-interface.c`: ①）→ `-c` で絶対パスと root 所有のファイルを明示
2. 署名の差し替え・git の差し替え・表示の差し替え（§1 の a〜c）→ ハッシュ指定・`-c`・GitHub での確認・Touch ID は 1 回
3. agent のキャッシュ: `ssh-add -t` の間・`ssh-agent` の既定（無期限）はパスフレーズなしで署名できる（①）。Secretive の「ロックを解除したままにする」、1Password の「アプリ単位の承認」も同類
4. allowed signers の書式: `principal namespaces="git" 鍵種 鍵`（`ssh-keygen.1`: ①）。失効は `gpg.ssh.revocationFile`、有効期間は OpenSSH 8.8 以降の `valid-after`／`valid-before`。親ディレクトリの所有も確かめる（§3.2）
5. 鍵の複製: Secure Enclave と FIDO は不可、ファイル鍵と 1Password は可（①）。Secure Enclave の鍵は Mac を替えると使えない → 新しい鍵・新しい allowed signers・新しい指紋（Mark の操作で）
6. 「タッチされた」ことの証明: `ssh-keygen -Y verify` は user-presence のフラグを検査しない（①）。検証の成功は「その鍵で署名された」ことまで

## 7. 画面の名前（Secretive 4.0.0。英語・日本語）
保護のレベル／Protection Level ・ 認証を要求する／Require Authentication ・ 現在の生体認証／Current Biometrics ・ 詳細／Advanced ・ 公開鍵のパス／Public Key Path ・ SHA256指紋／SHA256 Fingerprint ・ ロックを解除したままにする／Leave Unlocked（1 分・5 分・1 時間・24 時間）・ 複数の求めが保留中／Multiple authenticated requests are pending（`Localizable.xcstrings`: ①）

## 8. 不明（Mac で確かめる・原文を取る）
- `spctl -a -vv` の出力の書式（1 行目 `…: accepted`、`source=Notarized Developer ID`、`origin=Developer ID Application: … (Z72PRUAWF6)` の形か）
- 別の管理者ユーザーの作り方の画面（システム設定 → ユーザとグループ）の文言
- Mark の Mac の `/usr/local`・`/usr/local/bin`・`/usr/local/etc` の所有（Finder で確認。**Mark の所有なら進めない**。§3.1-0）。`/etc/zshrc` に `locale` を PATH から呼ぶ行があるか（別ユーザーの端末が開いた時点で乗っ取られる経路の実在の確認）
- スクリプトエディタの `do shell script … with administrator privileges` が起動の設定を読まない固定の PATH の sh で動くか（`/usr/local/bin` が Mark の所有のときの代替）
- 「現在の生体認証」の鍵の実機の動き（PR #845 の修正前の版でパスワードが通らないこと）と、Touch ID の求めの実際の文言
- GitHub のタグの Verified の詳細に SSH の鍵の指紋が出るか。Verified が付くためのメールの条件（タグを付けた人のメールが確認済みであること）。API の `verification` の欄の名前（SSH 署名のタグは Verified になる、は GitHub の文書で確認済み: ①）
- 1Password の公式文書の原文（本件では使わないので優先度は低い）
- macOS 26 以降で標準の ssh が FIDO に対応したか／標準の `ssh-keygen` で `sk-` 鍵の署名を検証できるか
- `git verify-tag --raw` の実機の出力（このクラウドには `ssh-keygen` が無く未再現。書式はソースから）
- Mark の Mac の `git --version`・`ssh -V`・macOS の版・`ls -ld /private/etc` の結果

## 9. 出典（①のみ列挙）
- Secretive: https://github.com/maxgoedjen/secretive （README・FAQ・LICENSE、v4.0.0 のソース `CreationOptions.swift`・`SecureEnclaveStore.swift`・`AuthenticationHandler.swift`・`SigningRequestTracer.swift`・`Notifier.swift`・`PendingRequestsView.swift`・`Instructions.swift`・`Localizable.xcstrings`・`Config.xcconfig`、PR #845）、https://github.com/maxgoedjen/secretive/releases/tag/v4.0.0
- Apple: https://developer.apple.com/documentation/security/protecting-keys-with-the-secure-enclave （`codesign`・`spctl` は macOS 標準。Developer ID と公証の確認） 、https://developer.apple.com/documentation/security/secaccesscontrolcreateflags/userpresence 、同 `biometrycurrentset`
- OpenSSH（openssh-portable）: `ssh-keygen.1`・`ssh-keygen.c`・`sk-usbhid.c`・`PROTOCOL.u2f`・`PROTOCOL.sshsig`・`ssh-add.1`・`ssh-agent.1`
- git: `Documentation/config/gpg.adoc`・`config/user.adoc`・`config/tag.adoc`・`git-tag.adoc`・`git-verify-tag.adoc`・`git.adoc`・`RelNotes/2.34.0.adoc`・`gpg-interface.c`・`t/t7031-verify-tag-signed-ssh.sh`
- Yubico: https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html 、https://developers.yubico.com/SSH/Securing_git_with_SSH_and_FIDO2.html
- GitHub の文書（github/docs）: "Comparing commits"（2 点リーダー・同名のブランチの優先）、"About commit signature verification"（SSH 署名のタグの Verified）、"Adding a new SSH key"（Signing Key）、"Displaying verification statuses"。gh CLI のソース（`pkg/cmd/ssh-key/add`・`login_flow.go`: Signing Key の API の権限と既定のログインの権限）
