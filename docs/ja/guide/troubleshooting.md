# トラブルシューティング

> この文書は[英語版](../../guide/troubleshooting.md)の翻訳です。食い違う場合は英語版が正です。

症状を探し、対処を見てください。`optopus-studio` を動かしているターミナルには、すべてのリクエストと
エラーが記録されます。ページの表示だけでは分からないときは、まずそこを見てください。

エラーメッセージは英語で表示されるので、見出しも英語のままにしています。

## インストール

### `uv sync` が optopus のビルド中に失敗する

optopus はソースからコンパイルされるので、原因はほぼ Rust のツールチェーンかネットワークです。

- **Rust が無い、または古い。** 同じターミナルで `cargo --version` が動き、1.88 以上であること。
  <https://rustup.rs> から入れるか `rustup update` を実行し、`cargo` が `PATH` に入るよう新しい
  ターミナルを開いてから、もう一度 `uv sync` を実行します。
- **GitHub に接続できない。** uv は git で optopus-py を取得します。
  `git ls-remote https://github.com/trash-iine/optopus-py` が動くか確認してください。プロキシの
  内側では `HTTPS_PROXY` を設定します。
- **C コンパイラやリンカが無い。** macOS では `xcode-select --install`、Debian や Ubuntu では
  `sudo apt install build-essential` を実行します。

### `npm install` や `npm run build` が失敗する

`node --version` が v24 であることを確認します。mise を使うなら、チェックアウトしたディレクトリで
`mise install` を実行し、シェルで mise が有効になっていることを確かめます。そうでなければ別の方法で
Node 24 を入れます。バージョンを切り替えたら、`frontend/node_modules` を消して `npm install` を
やり直してください。

## 起動

### ``optopus-studio: error: the studio needs its agent: install it with `uv sync` (the studio group)``

Claude Agent SDK が入っていません。`uv sync` が `--no-default-groups` や `--only-group` 付きで実行
されています。チェックアウトしたディレクトリで、オプション無しの `uv sync` を実行してください。

### `[Errno 48] … address already in use`(Linux では `Errno 98`)

別のプログラム(多くは前に起動した studio)がポート 8765 を使っています。それを止めるか、別のポートで
起動します: `uv run optopus-studio --port 8770`。

### ページに `{"detail":"Not Found"}` としか表示されない

Web ページがビルドされていないので、サーバーには表示するものがありません。
`(cd frontend && npm install && npm run build)` を実行し、studio を再起動します。ビルド済みのページは
起動時に探されます。

### ページは開くが、点が灰色のままで欄に "Connecting…" と出る

ページがサーバーに届いていません。サーバーが止まっている(ターミナルを確認)か、サーバーが待ち受けて
いるのとは別のアドレスやポートを開いています。ページは 1 秒ごとに再接続を試みるので、サーバーが戻れば
すぐにつながります。

## エージェント

### ログイン、認証、API キーについての赤いエラーがチャットに出る

エージェントは API キーではなく Claude Code のログインで動きます
([ADR 0003](../../adr/0003-agent-on-claude-code-login.md))。`claude` を起動して `/login` を実行し、
メッセージを送り直してください。`ANTHROPIC_API_KEY` と `ANTHROPIC_AUTH_TOKEN` は、意図して studio の
環境から取り除かれます(ターミナルに "ignoring ANTHROPIC_API_KEY; the agent uses the Claude Code
login" と記録されます)。

エラーが利用上限に触れているなら、Claude のプランの上限に達しています。リセットされるまで待ってください。

### "the agent stopped: …"

エージェントのセッションがエラーで終わりました。メッセージの続きに理由があり、ターミナルには完全な
トレースバックがあります。メッセージを送り直すとエージェントがまた動き出します。プロジェクト、ファイル、
リビジョンは残っています。

### "the agent is still working"

エージェントが作業中にメッセージを送りました。**Stop** が **Send** に戻るまで待つか、先に **Stop** を
押してください。

### エージェントが optopus のドキュメントを読めなかったと言う

エージェントは optopus-py のユーザーガイドを、各ページを初めて読むときに GitHub から取得し、
`~/.optopus-studio/docs/` に保存します。オフラインのときや、`raw.githubusercontent.com` を遮断する
プロキシの内側では取得に失敗します。エージェントは `api_help` でクラスを調べることはできますが、
ガイドがあるほうが良いモデルになります。ネットワークを直すか、optopus-py を固定されたコミット
(`pyproject.toml` に記載)でクローンし、`OPTOPUS_STUDIO_DOCS=<checkout>/docs/source` を設定して
ください。

### エージェントがモデルを何度も間違える

目的関数と制約をもっと具体的に伝える、良い解の小さな例を示す、問題が見えるビューを指定する、などを
試してください。結果が間違いではなく良くないだけなら、ヒューリスティックの比較を頼みます。長く
回り道した会話の後は、明確な最初のメッセージで **New project** から始め直すのも効果があります。

## 求解

### 赤いバナー "The solve failed at …"

求解がその段階(request、build、heuristic、run、encode)でエラーになりました。エージェントにも同じ
メッセージとトレースバックが見えていて、たいていは自分で直します。止まっているなら、エラーを直すよう
頼んでください。

### "the solve took longer than 300.0s"

求解は、全ランが停止条件上かかりうる合計時間に 30 秒を足した時間(最大 20 分)で、時間制限の無い
ヒューリスティックがあれば 300 秒で打ち切られます。エージェントに時間制限を頼む(「各ランを 10 秒で
止めて」)か、studio の起動前に `OPTOPUS_STUDIO_SOLVE_TIMEOUT`(秒)を設定してください。

### 黄色いバナー "view.py failed"

求解はできていて、描画だけが失敗しました。結果は Runs タブにあります。ビューを直すようエージェントに
頼んでください。

### Rust 移植がビルドできない

`cargo is not installed; see https://rustup.rs` は、studio を起動したときの `PATH` に `cargo` が
見つからないという意味です。それ以外のビルドエラーはエージェントが直すものなので、直すよう頼んで
ください。移植は `~/.optopus-studio/rust/` でビルドされます。このフォルダを消すと、まっさらな状態から
ビルドし直します。

## ファイルと共有

### ファイルの添付に失敗する

欄の下に理由が出ます。

- `… expected one of ('.csv', '.tsv', '.txt', '.xlsx', '.json')`: それ以外の形式(古い `.xls` を
  含む)は読めません。`.xlsx` か CSV で保存し直してください。
- `… is larger than 20 MiB`: ファイルを分けるか、モデルに要らない列を落としてください。
- `invalid file name …`: 英字、数字、空白、`.`、`-`、`_` だけの、ドットで始まらない名前に変えて
  ください。

### Import で "not a zip file" や "not an exported studio project" と出る

**Import** が受け付けるのは **Export** で作った zip だけです。**Package** で作ったパッケージはアプリ
なので、`uv run optopus-studio app <zip>` で動かします。アプリからエクスポートしたケースは、チャットの
**+** で添付します。

### "Cannot package revision N"

`revision N has no app.json` は、そのリビジョンがモデルをアプリにする前に解かれたという意味です。
エージェントにアプリにするよう頼み、それで解かれたリビジョンをパッケージ化してください。
`app.json does not fit the revision` には何が問題かが並んでいるので、直すようエージェントに頼みます。

### Docker イメージのビルドに失敗する

`docker is not installed` や `docker is not running` なら、Docker Desktop(またはデーモン)を入れるか
起動してから、やり直してください。Apple Silicon ではビルドが `linux/amd64` をエミュレートするため
10 分ほどかかりますが、想定どおりです。

## やり直す

studio を止め、`~/.optopus-studio/projects/` の下のプロジェクトのフォルダ、または `~/.optopus-studio`
ディレクトリ全体を削除します。チェックアウトしたリポジトリには影響しません。

## それでも解決しないとき

<https://github.com/trash-iine/optopus-studio/issues> に issue を立ててください。何をしたか、何を
期待したか、ページのメッセージ、ターミナルのログの末尾を書きます。データを共有してよいなら、
プロジェクトをエクスポート(**Export**)して添付すると助かります。
