# 開発

> この文書は[英語版](../../guide/development.md)の翻訳です。食い違う場合は英語版が正です。

このページは studio 自体を変更する人のためのものです。まず[はじめに](getting-started.md)のとおりに
セットアップしてください。[`AGENTS.md`](../../../AGENTS.md)(英語)は、このページをコーディング
エージェント向けに短くしたものです。両者は揃えておきます。

## 開発の流れ

バックエンドをリロード付きで動かし、その横でフロントエンドの開発サーバーを動かします。

```bash
OPTOPUS_STUDIO_HOME=/tmp/studio-dev uv run optopus-studio --reload   # ターミナル 1、:8765
(cd frontend && npm run dev)                                         # ターミナル 2、:5173
```

<http://127.0.0.1:5173> を開きます。Vite はフロントエンドが変わるたびにページを再読み込みし、`/api`
(HTTP と WebSocket)を 8765 のバックエンドに転送します。`OPTOPUS_STUDIO_HOME` を分けておくと、
試しのプロジェクトが普段のものと混ざりません。

パッケージ化したアプリは `uv run optopus-studio app <zip またはフォルダ>` で :8766 に起動します。
`/api/mode` が `"app"` を返すと、同じフロントエンドがアプリモードで表示します。

## 全体の構成

```
browser (React)  <-- WebSocket: ServerEvent / ClientEvent -->  backend (FastAPI, Agent SDK)
                                                                  |  stdin/stdout JSON Lines:
                                                                  |  SolveRequest -> WorkerEvent
                                                                  v
                                                          solver worker (a subprocess)
```

エージェントがプロジェクトのファイルを編集する手段は `agent.py` のツールだけで、Claude Code の組み込み
ツールは持ちません。求解のたびに、ファイルはリビジョンとして固定されます。

| ファイル | 動く場所 | 内容 |
|---|---|---|
| `instance.json` | — | データ |
| `model.py` | ワーカー | `build(instance)` が optopus の問題を返す。任意の `encode_solution` が解を JSON にする |
| `solve.json` | ワーカー | `{"kind": ..., **arguments}` 形式のヒューリスティック、または比較用のラベル付き `"heuristics"`。ラン数、シード |
| `view.py` | バックエンドのビューアプロセス | `to_view(instance, result)` がキャンバス用の `ViewSpec` を返す |
| `rust/main.rs`(任意) | Rust ワーカー | Rust に移植したモデル。`solve.json` の `"worker": "rust"` で使われる |
| `app.json`(任意) | パッケージ化したアプリ | アプリの利用者が変えられるもの: 入力の表とパラメータ |

3 つの契約は `src/optopus_studio/protocol.py` にあり、`schema/` のスキーマと
`frontend/src/generated/` の TypeScript 型の唯一の元です。ワーカーは `SolveRequest` / `WorkerEvent`
しか話さず、キャンバスは `ViewSpec` しか読まないので、Rust で書いたソルバーが GUI に触れずに Python
ワーカーを置き換えられます([ADR 0001](../../adr/0001-solver-behind-a-process-boundary.md))。

## どこに何があるか

| パス | 中身 |
|---|---|
| `src/optopus_studio/protocol.py` | すべての契約: ワーカーのプロトコル、`ViewSpec`、WebSocket のイベント |
| `cli.py` | `optopus-studio` コマンドと、その `app`、`image` サブコマンド |
| `app.py` | studio の FastAPI サーバーと WebSocket |
| `agent.py` | Agent SDK のセッション、エージェントのツール、システムプロンプト |
| `projects.py` | ディスク上のプロジェクト、リビジョン、アップロード |
| `tables.py` | アップロードされた CSV、TSV、Excel、JSON の読み込み |
| `solving.py` | モデルのファイルを求解に変える。エージェントとアプリの両方が使う |
| `runner.py`、`worker.py`、`viewer.py` | ソルバーとビューのプロセスを起動する側と、その中で動くもの |
| `rust.py`、`verify.py` | プロジェクトの Rust 移植をビルドする。Python のモデルと照合する |
| `apps.py`、`appserver.py` | リビジョンを `app.json` 付きでパッケージ化し、エージェント無しで提供する |
| `image.py`、`docker/app.Dockerfile` | パッケージを Docker イメージにビルドする |
| `frontend.py` | 両サーバーにビルド済みのフロントエンドを提供する |
| `docs.py` | エージェントが読む optopus-py のガイドのページを取得する |
| `frontend/` | React + Vite + ECharts。`src/generated/` は生成物なので編集しない |
| `workers/rust/` | 移植が利用する Rust ワーカーのライブラリ([GUIDE.md](../../../workers/rust/GUIDE.md) はエージェントが読むもの) |
| `examples/` | テストが解く 4 つの完成したプロジェクト |
| `schema/` | `protocol.py` から生成した JSON Schema |
| `docs/adr/` | 上の境界の背後にある判断 |

## 破りやすい決まり

- 生成されたコード(`model.py`、`view.py`)は、タイムアウト付きのサブプロセスでだけ動かし、サーバーの
  プロセスでは決して動かさない。
- エージェントは Claude Code のログインでサインインする。API キーの扱いを追加しない
  ([ADR 0003](../../adr/0003-agent-on-claude-code-login.md))。
- アプリが動かすもの(`appserver.py`、`apps.py` とそれらが import するもの)は `agent.py` や `app.py`
  を import しない。アプリのイメージには Agent SDK が無い
  ([ADR 0010](../../adr/0010-deliver-an-app-as-a-docker-image.md)。`tests/test_image.py` が確認する)。
- アップロードされたデータがモデルに届くのは `instance.json` 経由だけ。`model.py` は `uploads/` を
  読まない([ADR 0004](../../adr/0004-import-uploads-into-the-instance.md))。
- ワーカーのプロトコルを変えるときは、`protocol.py`、`worker.py`、`workers/rust/src` を一緒に変える。
- フロントエンドの色は `src/theme.ts` から取る。
- コード、コメント、ドキュメントは英語。`docs/ja/` の日本語ガイドは `docs/guide/` の翻訳なので、両方を
  一緒に変える。

## チェック

コミットの前にすべて実行します。CI でも実行されます。

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
(cd frontend && npm test && npm run typecheck)
(cd workers/rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings)
```

次の 2 つのテスト群は、指定したときだけ実行されます。

```bash
uv run pytest -m network   # GitHub から読む: エージェントが読むドキュメントのページ、vendor された core
uv run pytest -m docker    # アプリのイメージをビルドして動かす。Docker が必要
```

テストは小さなインスタンスを使い、`tmp_path` の中で完結させます。

## プロトコルを変える

まず `protocol.py` を変え、それからスキーマと TypeScript の型を生成し直します。

```bash
uv run python -m optopus_studio.schema && (cd frontend && npm run gen:types)
```

両方を済ませるまで `tests/test_schema.py` は失敗します。CI は `frontend/src/generated` がスキーマと
一致するかを確認します。

## 新しい optopus-py に移る

optopus は optopus-py の固定されたコミットから、Rust ワーカーの core はそのコミットが vendor している
コミットから取得します([ADR 0008](../../adr/0008-depend-on-a-pinned-optopus-py-commit.md))。移るには:

1. `pyproject.toml` の `rev` を新しい optopus-py のコミットにする。
2. `workers/rust/Cargo.toml` の `rev` を、その `vendor/optopus` のコミットにする。
3. `uv sync` の後、`uv run pytest` と `uv run pytest -m network` を実行する。

マージ前の optopus-py のチェックアウトを試すには、`[tool.uv.sources]` を `path` でそれに向け、
`OPTOPUS_STUDIO_DOCS` をその `docs/source` に向けます。これはコミットしません。

## Rust ワーカー

`workers/rust/` は、プロジェクトの `rust/main.rs` が利用するライブラリです
([ADR 0005](../../adr/0005-rust-worker-as-a-verified-port.md))。`src/serve.rs` は `worker.py` の
実行ループを、`src/factory.rs` は optopus-py のヒューリスティックの引数を写しているので、シードを
固定した実行は両方のワーカーで同じ結果になります。`tests/test_rust_worker.py` がそれを Python の
モデルと照合します。`GUIDE.md` はエージェントがモデルを移植するときに読むもので、ライブラリと揃えて
おきます。

## 判断の記録

ADR が述べている境界を変える前に、その ADR を読んでください(いずれも英語)。

| ADR | 判断 |
|---|---|
| [0001](../../adr/0001-solver-behind-a-process-boundary.md) | ソルバーはプロセス境界の向こうで動かす。まず Python から |
| [0002](../../adr/0002-build-optopus-from-the-sibling-checkout.md) | optopus を隣の optopus-py チェックアウトからビルドする(0008 で置き換え) |
| [0003](../../adr/0003-agent-on-claude-code-login.md) | エージェントは Agent SDK を通じて Claude Code のログインで動かす |
| [0004](../../adr/0004-import-uploads-into-the-instance.md) | アップロードされたファイルは `instance.json` に取り込む |
| [0005](../../adr/0005-rust-worker-as-a-verified-port.md) | Rust ワーカーはプロジェクトごとの移植で、動かす前に照合する |
| [0006](../../adr/0006-python-worker-progress-through-on-improvement.md) | Python ワーカーは `on_improvement` で進捗を報告する |
| [0007](../../adr/0007-share-a-project-as-a-zip.md) | プロジェクトはエージェントのセッション抜きの zip で共有する |
| [0008](../../adr/0008-depend-on-a-pinned-optopus-py-commit.md) | 固定した optopus-py のコミットに依存し、そのドキュメントを取得する |
| [0009](../../adr/0009-package-a-revision-as-an-app.md) | リビジョンをエージェント無しで動くアプリとしてパッケージ化する |
| [0010](../../adr/0010-deliver-an-app-as-a-docker-image.md) | パッケージ化したアプリは Docker イメージで届ける |
