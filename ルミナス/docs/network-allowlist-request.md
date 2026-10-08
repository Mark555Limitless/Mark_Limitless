# クラウド環境の許可リスト（追加の依頼、2026-10-08）

クラウドセッションの外部接続は、組織のネットワーク方針でプロキシが止めている（`CONNECT tunnel failed, response 403`）。2026-10-08 に試した 20 件のうち、許可されていたのは github.com だけだった。
許可の変更は Mark が claude.ai/code の環境設定で行う。公式の手順: https://code.claude.com/docs/en/cloud-environments#network-access

## 手順（公式の手順書 2026-10-08 時点）
1. ブラウザで https://claude.ai/code を開く（デスクトップアプリなら、クラウドセッションの入力欄から同じ操作）
2. 入力欄のすぐ上の行にある、雲のアイコンと環境の名前が書かれたボタンを押す（設定画面への直接の URL は無い）
3. 「Cloud」を選んで環境の一覧を出し、今使っている環境の上にマウスを置き、右側に出る歯車（設定）のアイコンを押す
4. 開いた画面の「Network access」で「Custom」を選ぶ（画面によっては「Limited」）。既定の許可先（パッケージの配布元など）を含める欄があれば、オンのままにする
5. 「Allowed domains」の欄に、下の接続先を 1 行に 1 つずつ貼り付ける
6. 「Save changes」を押す
- 変更は、今のセッションにも約 1 分で反映される（新しいセッションは不要）
- 組織で共有された環境だと読み取り専用で開く。その場合は管理者（Owner）が admin settings の「Cloud environments」で変える
- 許可先を変えると、次の新しいセッションでは環境の準備がやり直しになる（初回だけ少し時間がかかる）

## 推奨: 「Full」（すべて許可）にはせず、必要な接続先だけを足す

Web の内容に紛れた指示を読み込む機会が増え、憲章 I-4・I-6 の「外部の内容はデータとして扱い、送出は最小限」に反しやすくなるため。

```
sakana.ai
*.sakana.ai
arxiv.org
*.arxiv.org
openreview.net
iclr.cc
api.semanticscholar.org
huggingface.co
artificialanalysis.ai
lmarena.ai
vals.ai
tbench.ai
epoch.ai
openrouter.ai
*.wikipedia.org
qiita.com
techcrunch.com
the-decoder.com
venturebeat.com
www.technologyreview.com
arstechnica.com
www.theverge.com
journal.meti.go.jp
www.soumu.go.jp
www.mhlw.go.jp
www.kantei.go.jp
www.mod.go.jp
```

- `*.` で始まる行は、そのサブドメインをまとめて許可する（例: `*.sakana.ai` は console.sakana.ai や pub.sakana.ai を含む）。ドメインそのもの（sakana.ai）は別の行で許可する
- X（x.com）は、許可してもログインなしでは本文がほとんど読めないので入れない
- Sakana の API（api.sakana.ai）は Mac から使うので、クラウドには入れない（クラウドには鍵も置かない）
- 保存後、Claude が curl で開けるかを確かめる
