# SignalSift MVP 実装チェックリスト

本書は [アプリケーション仕様書](docs/SPECIFICATION.md) の実装進捗だけを管理する。詳細な挙動は重複記載せず、仕様書を参照する。

進め方:

- 上から順に実施し、完了した項目を `[x]` にする。
- テストは各機能と同じ変更で追加する。
- 仕様変更はコードより先に仕様書へ反映する。
- 各フェーズをレビュー可能な小さなPRまたはcommit単位にする。

## 0. 人間レビューとMVP仕様確定

- [x] Supply Chain VulnerabilityとAI Securityの2Profile、有効情報源、通知閾値7を承認する。
- [x] negative termの−5／−3を各Profile設定に持たせる。
- [x] CISA KEVを強制通知し、日付だけの `dateAdded` はcutoffとUTC日付単位で比較する。
- [x] `initial_cutoff_at`、日時不明記事の除外、180日保持を承認する。
- [x] source部分障害時に処理を継続し、最終的にActionsを失敗表示する方針を承認する。
- [x] 6件以上をSlackダイジェストにする方針を承認する。
- [x] 決定事項を仕様書と設定へ反映し、「MVP仕様確定」とする。

## 1. Python基盤、設定、共通モデル

- [x] Python 3.12以上の `pyproject.toml`、`src` layout、`signalsift` entry pointを作る。
- [x] `uv` を標準toolとし、dev groupを含む最小依存関係と `uv.lock` を変更へ含める。
- [x] `uv sync --locked` で `.venv` を再現し、IDEから `.venv/bin/python` を選べることを確認する。
- [x] `signalsift` packageと最小のtest構成を作り、残りのmoduleは担当phaseで必要になった時だけ追加する。
- [x] source、profile、notification、rule、任意boost/watch termの型付き設定モデルを作る。
- [x] 必須値、型、未知field、HTTPS URL、priority、source ID重複、adapter名を検証する。
- [x] `NormalizedItem`、評価結果、source別集計モデルを実装する。
- [x] 現行3設定ファイルの正常系と代表的な設定不正をテストする。
- [x] `uv run --locked signalsift run --help` と `uv run --locked pytest` がclean環境で動くことを確認する。

## 2. 制限付きHTTPと汎用Feed取得

- [x] TLS検証、10秒timeout、5 MiB上限、redirect最大3回、HTTPS維持を実装する。
- [x] HTTP 2xxだけを成功とし、User-Agentと安全なエラー処理を実装する。
- [x] RSS 2.0、Atom、RSS 1.0/RDFを同じ汎用Fetcherで解析する。
- [x] GUID、URL、日時、summary、content、categoryを `NormalizedItem` へ写像する。
- [x] 外部実体・DTDを処理せず、HTML・script・style・制御文字を安全化する。
- [x] 壊れたentryはskipし、Feed全体の解析不能はsource失敗にする。
- [x] HTTP境界と2種類以上の通常Feedをローカルfixtureでテストする（AC-11）。

## 3. CISA KEVとsource pre-filter

- [x] 静的な `cisa_kev` adapter registryを作り、動的plugin loadingを使わない。
- [x] KEV JSONを検証し、CVE、title、dateAdded、説明、対応、製品情報を正規化する。
- [x] Supply Chain Vulnerability ProfileのCISA強制採用が閾値だけをバイパスし、AI Profileには適用されないようにする。
- [x] NFKC、case-insensitive、英単語境界、日本語部分一致の共通照合を実装する。
- [x] source `exclude` を `include_any` より優先して評価する。
- [x] KEVの新旧境界と、Wiz・StepSecurity・Aikidoのpre-filterをテストする（AC-15）。
- [x] FlattはRSS全文ノイズを避け、トップページの記事カードだけを専用adapterで正規化する（AC-21）。
- [x] GTIは全文入りsummaryを保持しつつ、採否を冒頭500文字へ制限する（AC-24）。
- [x] StepSecurity/Aikidoの明白な企業更新・比較記事をsource filterで除外する。

## 4. 決定論的フィルターとscore

- [x] `any` と `all_groups` を実装し、同一ruleを1回だけ加点する。
- [x] Supply Chain Vulnerabilityの短い単純ORと、AI Securityの2群ANDを設定から評価する。
- [x] negative termとsource priorityを計算し、未使用boost/watch辞書をProfile設定から除く。
- [x] 通常記事に主題rule成立とthreshold到達の両方を要求する。
- [x] `why_matched` と主分類を重複なしの安定順で生成する。
- [x] supply-chain事件とマーケティング記事をテストする（AC-01、AC-02）。
- [x] 悪用脆弱性と通常CVEをテストする（AC-03、AC-04）。
- [x] MCP/AI securityと一般AI記事をテストする（AC-05、AC-06）。
- [x] source-scoped ruleでJPCERTの通常脆弱性と強いシグナルを分離する。
- [x] `CVE`/`CVEs`と`vulnerability`/`vulnerabilities`を明示的に扱う。
- [x] bare `agent`と調査手段としてのbare `AI`をAI文脈にしない（AC-25）。

## 5. 記事キー、初回cutoff、状態

- [x] URLのhost、port、fragment、tracking query、query順、末尾slashを正規化する。
- [x] GUID、canonical URL、source ID + titleの順でSHA-256 article keyを作る。
- [x] 保存状態と同一実行内の両方で記事重複を除外する。
- [x] version 1、`initial_cutoff_at`、`items` の状態読込・検証を実装する。
- [x] 初回cutoff、日時不明、24時間超の未来日時を仕様どおり扱う。
- [x] Slack成功記事だけを追加し、180日超の記録をpruneする。
- [x] JSONを安定形式かつ原子的に保存し、破損状態へ空でfallbackしない。
- [x] 重複、URL正規化、破損、prune、2回目のbackfill防止をテストする（AC-07、AC-09、AC-10、AC-16～AC-19）。
- [x] RDF `rdf:about`をentry IDとして扱い、文書内fragmentの項目を区別する（AC-23）。
- [x] JPCERTでは広いCVE/vulnerability ruleを除外し、強いシグナルだけのsource-scoped ruleを適用する。

## 6. Slack通知

- [x] Slack表示文字をescapeし、意図しないmentionとHTML・制御文字を抑止する。
- [x] 分類、title、source、why、日時、300文字以内の要約、URLを個別通知へ整形する。
- [x] 規定件数超過時にscore・日時・article keyの安定順でdigestを作る。
- [x] payload上限時だけdigestを決定論的に分割する。
- [x] Profile専用Slack WebhookへPOSTし、2xxだけを成功にする境界を実装する。
- [x] 個別・digestの部分失敗を返し、失敗記事を通知済みにしない。
- [x] escape、timeout、非2xx、digest切替と分割をテストする（AC-08、AC-14）。

## 7. run-once CLIと障害分離

- [x] `signalsift run` で設定、Secret、状態を起動前に検証する。
- [x] `--state-path` と、Webhook送信・状態書込を行わない `--dry-run` を実装する。
- [x] Fetch → Normalize → pre-filter → cutoff → Score → Dedupe → Slack → Stateの順で統合する。
- [x] 有効sourceだけを処理し、1sourceの失敗後も残りを継続する。
- [x] Slack失敗後も残りを送信し、成功分の状態を保存する。
- [x] 全成功0、部分・永続化失敗1、構成エラー2の終了codeを実装する。
- [x] sourceごとのfetch、candidate、match、duplicate、notify件数をログに出す。
- [x] source障害を秘密や本文なしの1件のSlack運用通知へ整形・送信する境界を実装する。
- [x] 通常CLIでsource障害の運用通知を呼び出し、dry-runではpreviewだけにする（AC-22）。
- [x] Secret、レスポンス全文、記事本文全文をログへ出さない。
- [x] source障害、Slack失敗、成功後状態更新を統合テストする（AC-08、AC-12、AC-13）。

## 8. GitHub Actionsとstateブランチ

- [x] workflowにコメントアウト状態のschedule `17,47 * * * *` と `workflow_dispatch` を定義する。cron有効化は運用者承認後に行う。
- [x] Python 3.12、10分timeout、`contents: write` だけを設定する。
- [x] concurrency `signalsift-state` と `cancel-in-progress: false` を設定する。
- [x] Actionsをcommit SHAで固定し、checkout credentialsを永続化しない。
- [x] commit SHA固定のsetup actionで `uv` を準備し、`uv sync/run --locked` でテストとCLIを実行する。
- [x] `state` ブランチ不在の初回作成と既存状態取得をWorkflowへ実装する。
- [x] CLIが1でも成功分状態を保存し、差分がある場合だけcommit・pushする。
- [x] state保存後にCLI結果をjobへ反映し、push失敗をjob失敗にする。

## 9. 受入試験、セキュリティ、文書

- [x] RSS、Atom、RDF、Flatt HTML、KEV、状態、Slack応答のfixtureを揃える。
- [x] AC-01～AC-25の各項目が少なくとも1つの自動テストへ対応することを確認する。
- [x] 外部networkと実Webhookなしで全テストを成功させる。
- [x] 固定時計で実行順に依存しないことと、同じ入力の決定性を確認する。
- [x] HTTPS、XML、size、redirect、Slack escape、Secret非露出をレビューする。
- [x] CoreにCVE必須前提や未使用plugin/profile frameworkがないことをレビューする。
- [x] READMEへinstall、実行、Secret、state、設定変更、テスト、障害時動作を記載する。
- [x] 仕様書、設定、実装、READMEの矛盾がないことを確認する。

## 10. 手動試運転とschedule有効化

- [ ] scheduleを無効のまま、テスト用Slackで `workflow_dispatch` を実行する。
- [ ] 自前PCで `.venv` を使い、dry-run、debugger、ローカル専用state pathを確認する。
- [ ] 初回状態作成、Slack成功後のstate更新、再実行時の重複抑止を確認する。
- [ ] 1source障害とSlack失敗を安全なfixtureまたはテスト環境で確認する。
- [ ] 数日間手動実行し、通知件数、false positive、false negative候補を記録する。
- [ ] 必要なfilter調整を設定・fixture・テストへ反映する。
- [ ] repository設定、Secret、state branch、権限を最終確認する。
- [ ] 人間の運用承認後に30分scheduleを有効化する。

## Definition of Done

- [x] `signalsift run` が有効な8情報源を独立して処理する。
- [x] 重要な3領域だけを説明可能なscoreで低ノイズ通知する。
- [x] Slack成功前に状態を更新せず、正常時に同一記事を再通知しない。
- [x] runnerをまたいでstateを維持し、初回の過去記事をbackfillしない。
- [x] AC-01～AC-25がローカルfixtureだけで成功する。
- [x] 外部DB、常駐server、内部scheduler、必須LLM、plugin frameworkを含まない。
