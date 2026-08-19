# SignalSift 運用手順

この文書は、SignalSiftを自分のGitHubリポジトリとSlackで運用開始するための手順です。

## 0. Forkから運用開始までのクイックスタート

この章は、公開リポジトリをForkし、Webhookなしの検証を経てSlack配信を開始するまでの一本道の手順です。組織内の専用リポジトリへコピーして運用する場合も、Fork操作以外は同じです。

### 0.1 事前に必要な権限

次を確認してください。

- GitHubでリポジトリをForkし、Fork先のSettingsとActions Secretsを変更できる
- Slack workspaceへAppを追加できる
- 通知先SlackチャンネルへAppを追加できる
- 組織のGitHub Actionsポリシーが`actions/checkout`と`astral-sh/setup-uv`を許可している

組織やEnterpriseのポリシーでActionsやwrite tokenが制限されている場合は、リポジトリ設定だけでは変更できません。管理者へ依頼してください。

### 0.2 リポジトリをForkする

1. [SignalSiftリポジトリ](https://github.com/DharmaDoll/SignalSift)を開く
2. 右上の **Fork** を選択する
3. 運用する個人アカウントまたはOrganizationをOwnerに選ぶ
4. Repository nameを確認する
5. **Copy the `main` branch only** を有効にしたまま **Create fork** を選択する
6. 作成後、URLが自分のFork（`https://github.com/<OWNER>/SignalSift`）であることを確認する

Forkは元リポジトリとは別のSettings、Secrets、Actions実行履歴を持ちます。元リポジトリのSecretや`state`、`state-test`ブランチは引き継がれません。

### 0.3 Fork側でActionsとwrite権限を有効にする

1. Forkの **Actions** タブを開く
2. 無効化の案内が表示された場合は、内容を確認して **I understand my workflows, go ahead and enable them** を選択する
3. **Settings → Actions → General** を開く
4. **Actions permissions** で、少なくともWorkflowが使用する`actions/checkout`と`astral-sh/setup-uv`を許可する
5. **Workflow permissions** で **Read and write permissions** を選択して保存する

Workflow自身も`permissions: contents: write`だけを要求します。このwrite権限は通知履歴を`state`または`state-test`ブランチへpushするために必要です。Pull Requestを作成・承認する権限は不要です。GitHubの設定項目は[公式のActions設定手順](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)も参照してください。

### 0.4 WebhookなしでActionsとstateを検証する

Slackを準備する前に、シミュレーションでForkの動作を確認します。

1. Forkの **Actions → SignalSift Profiles** を開く
2. **Run workflow** を選択する
3. Branchに`main`を選択する
4. `simulate_delivery`を有効にして実行する
5. `Test`、`Load notification state`、両Profile、`Persist notification state`が成功することを確認する
6. 同じ条件でもう一度実行する

1回目は`state-test`ブランチを作成し、採用記事があればシミュレーション済みとして保存します。2回目は別runnerが同ブランチを読み込みます。ログの期待値は次です。

```text
state_branch=state-test
simulated_delivery=true

# 1回目（採用記事がある場合）
notifications=<1以上>
state_changed=true

# 2回目
duplicates=<1回目に保存した件数>
notifications=0
state_changed=false
slack_sent=false
```

対象記事が0件なら`notifications=0`でも正常です。その場合も1回目にstateファイルが作成され、2回目は`state_changed=false`になります。Forkの **Code → Branches** で`state-test`が作成され、次の2ファイルだけが保存されていることを確認します。

```text
state/supply_chain_vulnerability.json
state/ai_security.json
```

`state-test`はSlack送信成功を示しません。本番の`state`へコピーしないでください。

### 0.5 Slack Incoming Webhookを作成する

最初は本番チャンネルではなく、SignalSift検証用チャンネルを推奨します。

1. [SlackのIncoming Webhook手順](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks)からSlack Appを作成する
2. App設定の **Incoming Webhooks** を開く
3. **Activate Incoming Webhooks** をOnにする
4. **Add New Webhook to Workspace** を選択する
5. 投稿先チャンネルを選び、許可する
6. **Webhook URLs for Your Workspace** に表示されたURLをコピーする

Webhookは選択したチャンネルに紐付きます。非公開チャンネルの場合、作成者がそのチャンネルへ参加している必要があります。URL自体がSecretなので、Issue、Pull Request、ソース、ログ、チャットへ貼らないでください。

Profileごとにチャンネルを分ける場合はWebhookを2つ作ります。同じチャンネルへ送る場合は、同じWebhook URLを両方のRepository secretへ登録できます。

### 0.6 ForkへRepository Secretsを登録する

1. Forkの **Settings → Secrets and variables → Actions** を開く
2. **New repository secret** を選択する
3. 次の2つを正確な名前で登録する

```text
SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY
SLACK_WEBHOOK_URL_AI_SECURITY
```

値には対応するIncoming Webhook URLを設定します。登録後、GitHub画面から値を再表示することはできません。環境名やVariableではなく、Repository secretとして登録してください。

### 0.7 初回の実配信と本番stateを確認する

1. **Actions → SignalSift Profiles → Run workflow** を開く
2. Branchに`main`を選ぶ
3. `simulate_delivery`を無効にして実行する
4. Slackに期待した通知が届くことを確認する
5. Workflowの`Persist notification state`が成功することを確認する
6. ForkのBranchesで`state`ブランチが作成されたことを確認する
7. 同じ条件でもう一度手動実行する

2回目はSlack成功済みの記事が`duplicates`へ数えられ、同じ記事が再投稿されません。新着記事が発生した場合は、その記事だけが通知されるため`notifications=0`にならないことがあります。

Slack送信が失敗した記事は`state`へ追加されず、次回実行で再試行されます。`state-test`と`state`は役割が異なるため、統合・コピーしないでください。

### 0.8 定期的な品質評価

現在のscheduleは、Webhookなしでソース取得とフィルタ品質を確認するためのシミュレーション実行として動作します。schedule実行ではSlackへ送信せず、`state-test`ブランチだけを読み書きします。本番`state`ブランチは変更しません。Actionsログで各sourceの取得件数、候補数、matched数、drop理由を確認できます。

本番Slack配信は、Repository secretsを設定した後に`workflow_dispatch`で`simulate_delivery`を無効にして実行します。定期的な本番配信へ切り替える場合は、scheduleの実行モードを意図的に変更し、Webhookと`state`の運用を確認してから行ってください。

### 0.8.1 scheduleを本番配信へ切り替えるチェックリスト

本番時は、次の順番で確認・修正します。

1. Repository Secretsに次の2つが登録されていることを確認する。

   ```text
   SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY
   SLACK_WEBHOOK_URL_AI_SECURITY
   ```

2. `workflow_dispatch` で `simulate_delivery=false` を実行し、次を確認する。

   - 両Profileの実行が成功する
   - Slackへ通知が届く
   - `state` ブランチへstateが保存される
   - 同じworkflowを再実行しても同じ記事が重複通知されない

3. [`.github/workflows/signalsift.yml`](../.github/workflows/signalsift.yml) を確認し、scheduleが`state-test`向けシミュレーション実行になっている箇所を本番実行へ変更する。

   変更対象は、workflow冒頭のJob環境変数2行です。

   現在の品質評価・state-test設定：

   ```yaml
   STATE_BRANCH: ${{ (github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.simulate_delivery)) && 'state-test' || 'state' }}
   SIMULATE_DELIVERY: ${{ github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.simulate_delivery) }}
   ```

   本番scheduleへ切り替える設定：

   ```yaml
   STATE_BRANCH: ${{ (github.event_name == 'workflow_dispatch' && inputs.simulate_delivery) && 'state-test' || 'state' }}
   SIMULATE_DELIVERY: ${{ github.event_name == 'workflow_dispatch' && inputs.simulate_delivery }}
   ```

   この2行以外のPythonコードやstateスクリプトを変更する必要はありません。変更後は、scheduleが`state`を使い、`--simulate-delivery`なしで実行されることを確認します。

4. workflow変更をレビューしてmainへ反映し、scheduleを1回実行する。

5. Actionsログで、両ProfileのSlack送信成功、`state_changed=true`、`state` ブランチ更新を確認する。次回実行では既通知記事が `duplicates` になり、再通知されないことを確認する。

本番化前にscheduleを無効化する必要はありません。切り替え作業中はシミュレーションのまま動作し、Webhook送信や本番`state`変更は発生しません。`state-test`にはシミュレーション結果が蓄積されます。

公開リポジトリをForkした場合、scheduled workflowはGitHubによって初期状態で無効化されます。また、公開リポジトリは60日間活動がないとscheduled workflowが自動無効化されることがあります。scheduleをmergeした後、**Actions → SignalSift Profiles** のメニューに **Enable workflow** が表示される場合は有効化してください。詳細は[GitHubのWorkflow有効化手順](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)を参照してください。

有効化後は、Actions画面で次回実行が作成されること、シミュレーション評価ログが出力されること、`state-test`ブランチが更新されることを確認します。cronはUTC基準です。

### 0.9 upstreamの更新を取り込む

セキュリティ修正や情報源変更を取り込む場合は、Forkのトップ画面にある **Sync fork → Update branch** を使用できます。更新内容とWorkflow差分を必ず確認してから同期してください。詳しくは[GitHubのFork同期手順](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/syncing-a-fork)を参照してください。

このリポジトリのscheduleは、初期状態ではWebhookなしの`state-test`向けシミュレーションとして動作します。upstream同期後は、Fork側で本番配信へ切り替えたworkflowの変更が上書きされていないか確認してください。Profile設定をForkで変更している場合も競合や上書きに注意してください。`state`と`state-test`は別ブランチなので、通常の`main`同期では変更されません。

### 0.10 運用開始チェックリスト

- [ ] Fork側でActionsが有効
- [ ] `GITHUB_TOKEN`が`contents: write`を使用可能
- [ ] WebhookなしのWorkflowを2回実行し、`state-test`のrunner間重複排除を確認
- [ ] Slack Incoming Webhookを検証用チャンネルへ作成
- [ ] 2つのRepository secretをFork側へ登録
- [ ] `simulate_delivery=false`でSlack実配信を確認
- [ ] `state`ブランチ作成と2回目の重複抑止を確認
- [ ] 通知内容と誤検知件数を数日間確認
- [ ] scheduleの品質評価dry-runが正常に動作することを確認
- [ ] 本番配信へ切り替える場合はworkflowのdry-run/state条件をレビュー
- [ ] scheduled workflowがGitHub上で有効
- [ ] Webhook URLがソース、ログ、Issue、Pull Requestへ露出していない

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

scheduleはWebhookなしのシミュレーションとして有効です。定期実行ではSlackへ送信せず、`state-test`だけを更新します。

Webhookを設定する前にActionsと両Profileの取得・state重複排除だけを確認する場合は、**Run workflow** で `simulate_delivery` を有効にします。Slackと本番の`state`ブランチは使わず、シミュレーション結果を専用の`state-test`ブランチへ保存します。同じcommitを対象にWorkflowを2回実行し、1回目の`state_changed=true`と、別runnerで動く2回目の`duplicates`、`notifications=0`、`state_changed=false`を確認してください。

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

## 6. scheduleの品質評価を確認する

Fork後にActionsを有効化すると、scheduleが毎時実行されます。scheduleはWebhookなしの`--simulate-delivery`で動作し、`state-test`へ取得・フィルタ・重複排除の結果を保存します。

次を確認してください。

1. Actions画面で`SignalSift Profiles`が有効になっている
2. schedule実行が成功する
3. 各sourceの取得件数・候補数・matched数を確認する
4. `state-test`ブランチが作成または更新される
5. 次回実行で既存記事が`duplicates`になる

cronはGitHub ActionsのUTC基準です。本番Slackをscheduleで配信する場合は、先に「0.8.1 scheduleを本番配信へ切り替えるチェックリスト」を実施してください。

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

停止する場合はGitHub Actions画面でWorkflowを無効化するか、scheduleを削除します。既存の`state`と`state-test`はそのまま保持されます。

再開時は、まず`workflow_dispatch`で`simulate_delivery=true`を実行し、`state-test`更新を確認します。本番配信を再開する場合は、Secretsと`simulate_delivery=false`の手動実行を確認してからscheduleの実行モードを見直します。

## 11. セキュリティ上の注意

- 信頼できないPull RequestのWorkflowでSlack Secretを使わない
- `workflow_dispatch`を実行できる権限を限定する
- `main`へのWorkflow変更をレビューする
- `state`ブランチをbot以外から直接変更させない
- Actionsで外部入力をshellコマンドとして評価しない
- Slack Webhook URLをログ、Issue、コミットへ出さない
