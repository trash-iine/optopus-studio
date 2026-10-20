# はじめに

> この文書は[英語版](../../guide/getting-started.md)の翻訳です。食い違う場合は英語版が正です。

このページでは studio をインストールし、ブラウザで開くところまで進めます。各手順の最後に確認方法が
あります。確認に失敗したら、よくある原因が[トラブルシューティング](troubleshooting.md)にあります。

studio は自分のマシン(macOS、Linux、Windows では WSL)で動きます。インストール中と、エージェントが
optopus のドキュメントを読むときに GitHub へのネットワーク接続が必要です。

## 1. ツールを入れる

| ツール | 用途 | 確認 |
|---|---|---|
| [git](https://git-scm.com/) | このリポジトリの取得。uv も optopus の取得に使う | `git --version` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Python と studio のパッケージを入れる | `uv --version` |
| Python 3.12 以上 | studio を動かす | `uv python find 3.12`(無ければ手順 3 で uv がダウンロードする) |
| [Rust](https://rustup.rs/) 1.88 以上 | optopus をソースからコンパイルする。モデルの Rust 移植も同様 | `cargo --version` |
| Node 24 | Web ページをビルドする | `node --version` |
| [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) と [Codex](https://developers.openai.com/codex/cli) 0.153 以上の一方または両方 | エージェントはどちらかのログインで動く | `claude --version`、`codex --version` |

Node はリポジトリの `mise.toml` でバージョン 24 に固定されています。[mise](https://mise.jdx.dev/)
を使うなら、チェックアウトしたディレクトリで `mise install` を実行すれば入ります。ほかの方法で入れた
Node 24 でも構いません。

## 2. Claude Code か Codex にサインインする

チャットのエージェントは、あなたの Claude Code のログインで Claude として、または Codex のログインで
Codex として動きます。どちらか一方があれば十分です。両方あれば、プロジェクトごとにどちらでも使えます
(チャットの **Agent** メニュー)。一度サインインしてください。

```bash
claude        # 起動したら /login と入力してブラウザの指示に従い、終わったら /exit
codex login   # Codex の場合: ブラウザの指示に従う
```

確認: `claude` がログインを求めずに起動すること、または `codex login status` がログイン済みと
表示すること。環境変数の API キーは使われません。studio は起動時に `ANTHROPIC_API_KEY` を取り除き、
Codex を `OPENAI_API_KEY` 無しで起動するので、常にログインが使われます
([ADR 0003](../../adr/0003-agent-on-claude-code-login.md)、
[ADR 0012](../../adr/0012-run-the-agent-on-claude-code-or-codex.md))。

## 3. studio をインストールする

```bash
git clone https://github.com/trash-iine/optopus-studio.git
cd optopus-studio
uv sync
```

`uv sync` は `.venv/` を作り、必要なら Python 3.12 を入れ、
[optopus-py](https://github.com/trash-iine/optopus-py) の固定されたコミットから optopus を
コンパイルします。初回は Rust のコンパイルで数分かかります。2 回目以降はすぐ終わります。

確認: `uv run python -c "import optopus; print('ok')"` が `ok` と表示すること。

## 4. Web ページをビルドする

```bash
cd frontend
npm install
npm run build
cd ..
```

確認: `frontend/dist/index.html` があること。これが無くてもサーバーは起動しますが、そのアドレスを
開いても `{"detail":"Not Found"}` としか表示されません。

`frontend/` の変更を pull したら、もう一度ビルドしてください。

## 5. studio を起動する

```bash
uv run optopus-studio
```

<http://127.0.0.1:8765> を開きます。次のように表示されれば成功です。

- ヘッダー: **optopus studio**、プロジェクトのメニュー、ページがサーバーにつながっている間は緑になる
  小さな点、**Import**、**Export**、**New project**
- 左側のチャット: 短い案内と 3 つの例文
- 右側のキャンバス: "No result yet" という表示

studio はターミナルで `Ctrl+C` を押すと止まります。プロジェクトは残るので、もう一度起動すれば続きから
作業できます。

続きは[最初のセッション](first-session.md)へ。

## オプション

```bash
uv run optopus-studio --port 9000              # 別のポートで起動
uv run optopus-studio --host 0.0.0.0           # 他のマシンから接続可能にする(認証は無いので信頼できるネットワークでのみ)
uv run optopus-studio --reload                 # Python のソースが変わったら再起動する(開発用)
uv run optopus-studio --agent codex            # 新しいプロジェクトを Codex で始める(チャットで切り替え可)
```

| 変数 | 既定値 | 意味 |
|---|---|---|
| `OPTOPUS_STUDIO_HOME` | `~/.optopus-studio` | プロジェクトとリビジョンの保存先 |
| `OPTOPUS_STUDIO_AGENT` | 動くもののうち先のもの(Claude が先) | 新しいプロジェクトのエージェント: `claude` か `codex`(`--agent` と同じ) |
| `OPTOPUS_STUDIO_CLAUDE_MODEL` | Claude Code の既定 | Claude で動くときにエージェントが使うモデル(`OPTOPUS_STUDIO_MODEL` も可) |
| `OPTOPUS_STUDIO_CODEX_MODEL` | Codex の既定 | Codex で動くときにエージェントが使うモデル |
| `OPTOPUS_STUDIO_CODEX` | `PATH` 上の `codex` | Codex の実行ファイル |
| `OPTOPUS_STUDIO_DOCS` | GitHub から取得 | 代わりにエージェントに読ませる optopus-py の `docs/source` |
| `OPTOPUS_STUDIO_WORKER` | Python ワーカー | ソルバーのコマンド(例: Rust ワーカー) |
| `OPTOPUS_STUDIO_SOLVE_TIMEOUT` | 停止条件から計算 | 求解を打ち切るまでの秒数 |
| `OPTOPUS_STUDIO_RUST_DIR` | `$OPTOPUS_STUDIO_HOME/rust` | Rust 移植をビルドし、バイナリを置く場所 |

`OPTOPUS_STUDIO_SOLVE_TIMEOUT` が無いとき、求解は全ランが停止条件上かかりうる合計時間に 30 秒を足した
時間(最大 20 分)で打ち切られます。時間制限(`max_duration_secs`)の無いヒューリスティックがあれば
300 秒で打ち切られます。

## データの保存場所

studio が保存するものはすべて `OPTOPUS_STUDIO_HOME`(既定は `~/.optopus-studio`)の下にあります。

```
~/.optopus-studio/
    projects/<id>/
        chat.jsonl      会話
        work/           エージェントが編集中のモデルのファイル
        revs/<n>/       各求解: 解いたときのファイルと result.json、view.json
        uploads/        チャットで添付したファイル
        cases/<id>/     パッケージ化したアプリから添付されたケース
        meta.json       会話を再開するためのエージェントのセッション
    docs/<commit>/      エージェントが読んだ optopus-py のドキュメント
    rust/               ビルド中の Rust 移植
```

やり直したいときは、studio を止めてプロジェクトのフォルダ、またはディレクトリ全体を削除します。
プロジェクトを別々に管理したいときは、`OPTOPUS_STUDIO_HOME` を別のフォルダに向けます。

## 更新

```bash
git pull
uv sync
(cd frontend && npm install && npm run build)
```

その後、studio を起動し直してください。
