# SignalSift 運用手順

この文書は、SignalSiftを自分のGitHubリポジトリとSlackで運用開始するための手順です。

## 1. 運用リポジトリを用意する

共有元のリポジトリを直接本番運用せず、次のいずれかを用意します。

- Forkした自分のリポジトリ
- 組織内の専用リポジトリ

ForkではActions Secretは引き継がれません。Slack Webhookは必ず運用先リポジトリで登録してください。

## 2. Slack Webhookを登録する

ProfileごとにSlack Incoming Webhookを用意します。同じチャンネルへ送る場合は同じWebhook URLを登録しても構いません。

リポジトリの **Settings → Secrets and variables → Actions** で、次のRepository secretを登録します。

```text
SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY
SLACK_WEBHOOK_URL_AI_SECURITY
```

Webhook URLをソースファイル、stateブランチ、Workflow本文、ログへ書き込まないでください。

## 3. Actions権限を確認する

リポジトリの **Settings → Actions → General** でActionsを許可します。

Workflowは次の権限を使います。

```yaml
permissions:
  contents: write
```

これは通知済み状態を`state`ブランチへ保存するために必要です。`main`ブランチはPull Requestレビュー必須、`state`ブランチは通常の開発者が直接変更できないよう保護してください。

## 4. 初回の手動実行

現在、誤通知を避けるため定期実行cronはコメントアウトされています。

Webhookを設定する前にActionsと両Profileの取得・state重複排除だけを確認する場合は、**Run workflow** で `simulate_delivery` を有効にします。各Profileを同じ一時stateで2回実行し、Slack送信と`state`ブランチへのpushは行いません。ログで1回目の`simulated_delivery=true`と、2回目の`duplicates`を確認してください。

実配信を確認する場合は、Repository secretsを設定してから `simulate_delivery` を無効にして手動実行します。

1. **Actions → SignalSift Profiles** を開く
2. **Run workflow** を選択
3. `main`を対象に実行する
4. Workflowの各Stepが成功することを確認する
5. Slackに通知が届いたことを確認する

初回実行では、各Profileの状態ファイルが作成されます。`state`ブランチが存在しない場合、Workflowがブランチを作成します。既存の`state`ブランチを取得できない場合は、誤って初期化せずWorkflowを失敗させます。認証・権限・GitHub障害を先に解消してください。

状態ファイルは次の2つです。

```text
state/supply_chain_vulnerability.json
state/ai_security.json
```

初回実行時は`initial_lookback_hours: 24`の範囲だけが候補です。過去記事を一括通知するバックフィルは行いません。

## 5. 通知内容を確認する

初回は、まずdry-runで候補と理由を確認できます。dry-runはSlack送信とstate変更を行いません。

```bash
uv sync --locked
uv run --locked pytest
uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --dry-run \
  --review-lookback-hours 168 \
  --state-path .local/state/supply_chain_vulnerability.json
```

AI Security Profileを確認する場合は`--profile ai-security`と対応するstate pathへ置き換えます。

`--review-lookback-hours`は精度調整用です。本番の24時間cutoffや通知履歴を変更しません。

## 6. cronを有効化する

手動実行とSlack通知を確認してから、`.github/workflows/signalsift.yml`のcronコメントを解除します。

```yaml
on:
  schedule:
    - cron: "17,47 * * * *"
  workflow_dispatch:
```

cronはGitHub ActionsのUTC基準です。変更をpushすると、Workflowの構文チェック後、次回スケジュールから定期実行されます。push直後に自動実行される設定ではありません。

## 7. 通常運用の確認項目

Workflowログでは、情報源ごとに次を確認できます。

```text
fetch
fetched
candidates
matched
duplicates
notified
```

通常実行の原則は次のとおりです。

- Slack送信に成功した記事だけstateへ追加する
- Slack送信に失敗した記事は次回実行で再試行する
- 情報源1件の失敗で他の情報源を止めない
- 情報源障害は同じWebhookへ運用通知する
- stateは`state`ブランチだけを正本とする

## 8. 障害対応

### Slack通知が届かない

1. Actions Secret名がProfile設定と一致しているか確認する
2. Webhook URLが失効していないか確認する
3. Workflowログの`notification failed`を確認する
4. stateファイルに該当記事が追加されていないことを確認する
5. Webhookを更新し、手動実行で再確認する

Slack失敗記事は通知済みとして記録されないため、復旧後に再送されます。

### 情報源障害がある

Workflowログの`fetch=failed`と運用通知を確認します。1情報源の障害は他の情報源の処理を止めません。Feedの構造変更が疑われる場合は、まずdry-runで候補数とエラー内容を確認してください。

### stateブランチの問題

`state`ブランチのJSONを手動編集しないでください。破損した場合は、Actionsを停止してからバックアップを取得し、JSONの形式と`version`、`initial_cutoff_at`、`items`を確認します。

stateを復旧できない場合は、別名でバックアップしたうえでstate branchを再作成します。再作成後は初回24時間cutoffから再開され、過去180日分の通知履歴は引き継がれません。

## 9. ローカル実行

PCでのデバッグと運用前検証は`uv`を使います。ローカル検証ではGitHub Actionsの`state`ブランチを直接使わず、`.local/state`を使用してください。

```bash
cd /home/calvet/git/SignalSift
uv sync --locked
uv run --locked pytest
uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --dry-run \
  --state-path .local/state/supply_chain_vulnerability.json
```

実Slackへ送る場合は、テスト用Webhookと`.local/state`を使用してください。

```bash
export SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY="..."
uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --state-path .local/state/supply_chain_vulnerability.json
```

`.venv`、`.local`、`.env`、Webhook URLはGitへ追加しないでください。

### 9.1 Webhookなしでstateと重複排除を検証

`--simulate-delivery`はSlackを呼ばず、採用記事をローカルstateへシミュレーション成功として保存します。誤って本番stateを更新しないよう、`--state-path`は`.local/`配下に限定されます。

```bash
mkdir -p .local/state .local/reviews

uv run --locked signalsift run \
  --profile ai-security \
  --simulate-delivery \
  --state-path .local/state/ai_security.json \
  | tee .local/reviews/ai-security-simulated-first.log

uv run --locked signalsift run \
  --profile ai-security \
  --simulate-delivery \
  --state-path .local/state/ai_security.json \
  | tee .local/reviews/ai-security-simulated-second.log
```

2回目に既記録記事が通知候補へ戻らないことを確認します。このstateはSlackへの実送信を証明しないため、本番の通知台帳へコピーしないでください。通常の`--dry-run`は従来どおりstateを変更しません。

### 9.2 7日間のdry-runレビュー

dry-runはSlack送信とstate変更を行いません。`--review-lookback-hours`を指定すると通知履歴を一時的に無視し、過去記事を再評価できます。

```bash
mkdir -p .local/reviews .local/state

uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --dry-run \
  --review-lookback-hours 168 \
  --state-path .local/state/supply_chain_vulnerability.json \
  | tee ".local/reviews/supply-chain-$(date -u +%Y%m%dT%H%M%SZ).log"

uv run --locked signalsift run \
  --profile ai-security \
  --dry-run \
  --review-lookback-hours 168 \
  --state-path .local/state/ai_security.json \
  | tee ".local/reviews/ai-$(date -u +%Y%m%dT%H%M%SZ).log"
```

候補ごとに`title`、`source`、`score`、`why`、URLを確認し、誤検知・見逃し候補をログと別のレビュー記録へ残します。

### 9.3 日次観測

数日間の頻度を測る場合は、毎日1回、直近24時間を再評価します。

```bash
uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --dry-run \
  --review-lookback-hours 24 \
  --state-path .local/state/supply_chain_vulnerability.json \
  | tee ".local/reviews/supply-chain-$(date -u +%Y%m%d).log"
```

AI Securityも同じコマンドの`--profile`とstate pathを置き換えて実行します。日ごとに次を記録します。

- `matched`と`notifications`の件数
- 情報源ごとの候補数
- 誤検知・見逃し候補
- Feed取得失敗
- 同一記事の再出現

`--review-lookback-hours`付き実行はレビュー専用で、同じ記事が複数日に表示されることがあります。本番の重複排除確認には、次のテストSlack実送信を使います。

### 9.4 テストSlackへの実送信

dry-runの内容を確認した後、テスト用SlackチャンネルのWebhookを環境変数へ設定します。本番チャンネルのWebhookは使わないでください。

```bash
export SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY='テスト用Webhook URL'
export SLACK_WEBHOOK_URL_AI_SECURITY='テスト用Webhook URL'

uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --state-path .local/state/supply_chain_vulnerability.json \
  | tee .local/reviews/live-supply-chain.log
```

AI Securityは`--profile ai-security`と`.local/state/ai_security.json`へ置き換えます。実送信ではSlack成功記事だけがstateへ保存され、同じコマンドを再実行しても同じ記事は再通知されません。

### 9.5 ローカル検証後の確認と後片付け

実送信後に以下を確認します。

```bash
uv run --locked signalsift run \
  --profile supply-chain-vulnerability \
  --dry-run \
  --state-path .local/state/supply_chain_vulnerability.json

git status --short
```

2回目のdry-runで既通知記事が候補に戻らないこと、Webhook URLや記事本文全文がログに出ていないことを確認します。検証終了後はWebhookをSlack側で失効・ローテーションし、`.local/reviews`と`.local/state`を必要に応じて安全に保管または削除してください。これらはGitへcommitしません。

## 10. 停止・再開

停止する場合はWorkflowのcronをコメントアウトします。既存のstateはそのまま保持されます。

再開時は、まず`workflow_dispatch`で手動実行し、Slackとstate更新を確認してからcronを再有効化します。

## 11. セキュリティ上の注意

- 信頼できないPull RequestのWorkflowでSlack Secretを使わない
- `workflow_dispatch`を実行できる権限を限定する
- `main`へのWorkflow変更をレビューする
- `state`ブランチをbot以外から直接変更させない
- Actionsで外部入力をshellコマンドとして評価しない
- Slack Webhook URLをログ、Issue、コミットへ出さない
