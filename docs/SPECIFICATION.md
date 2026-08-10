# SignalSift アプリケーション仕様書

| 項目 | 内容 |
|---|---|
| 文書種別 | MVP機能・非機能仕様書 |
| 対象 | SignalSift Core + Security Profile + Slack通知 |
| 文書バージョン | 1.0 |
| 基準日 | 2026-08-10 |
| 実装状態 | 仕様策定済み・アプリケーション本体は未実装 |

## 1. 文書の目的

本書は、SignalSiftのMVPを設計、実装、試験、運用するための規範的な仕様を定義する。

本書中の「必須」「する」「しない」はMVPの必須要件を表す。「将来」はMVPの対象外を表す。既存資料と本書が矛盾する場合は、プロダクト原則については `AGENTS.md`、MVPの具体的なアプリケーション挙動については本書を優先する。

## 2. プロダクト概要

SignalSiftは、厳選した公開情報源から記事を取得し、決定論的なルールで有用性を判定し、未通知の重要な記事だけをSlackへ送る、run-once型の情報選別アプリケーションである。

最初のユースケースであるSecurity Profileは、次の3領域を対象とする。

1. ソフトウェア・サプライチェーン攻撃
2. 重要または実際に悪用されている脆弱性
3. LLM、AIエージェント、MCPに関するセキュリティ脅威

価値基準は収集件数ではなく、次の4点である。

- 情報源の品質
- 選別精度
- 通知量の少なさ
- 判断理由の説明可能性

本システムは脅威インテリジェンス基盤、CVEデータベース、全文検索サービス、汎用クローラーではない。

## 3. スコープ

### 3.1 MVPに含むもの

- Python 3.12以上で動作する `signalsift run` CLI
- YAMLによる情報源およびフィルターポリシー設定
- RSS 2.0、Atom、RSS 1.0/RDFの汎用取得と正規化
- CISA KEV用の小さなJSONアダプター
- 情報源固有の事前フィルター
- 決定論的な複合ルールと整数スコアリング
- 記事単位の重複排除
- Slack Incoming Webhook通知
- Gitの専用 `state` ブランチを用いた通知済み状態の永続化
- GitHub Actionsによる定期実行と手動実行
- 情報源単位の障害分離、構造化された実行ログ
- ローカルフィクスチャだけで完結する自動テスト

### 3.2 MVPに含まないもの

- 常駐サーバーおよび内部スケジューラー
- Web UI、認証、ユーザー管理
- PostgreSQL、Redis、キュー、Kafka、Kubernetes
- RAG、ベクトルDB、必須のLLM呼び出し
- 記事本文ページの自動巡回
- ブラウザー自動操作、汎用HTMLクローラー
- イベント単位の相関・重複排除
- 動的プラグインロード、プラグイン市場
- 複数プロファイル選択、プロファイル継承
- 未使用の通知先実装や通知先レジストリー
- 候補としてコメントアウトされている情報源とそのアダプター

## 4. 利用者と利用シナリオ

### 4.1 想定利用者

主な利用者は、重要なセキュリティ動向を少ない通知で把握したい開発者、セキュリティ担当者、運用担当者である。

### 4.2 主要シナリオ

1. GitHub Actionsが30分ごとにCLIを起動する。
2. CLIが有効な情報源を取得する。
3. 各記事を共通モデルへ正規化する。
4. 明白な媒体固有ノイズを除外する。
5. Security Profileのルールでスコアと選定理由を計算する。
6. 通知済み記事を除外する。
7. 未通知の採用記事をSlackへ送信する。
8. Slackが成功を返した記事だけを通知済みとして保存する。

運用者は同じ処理を `workflow_dispatch` から手動実行できる。

## 5. システム構成

```text
GitHub Actions
      │
      ▼
signalsift run
      │
      ├── config/sources.yaml
      ├── config/filters.yaml
      └── state branch: state/notified.json
      │
      ▼
Fetch → Normalize → Source pre-filter → Score → Dedupe → Slack
                                                         │
                                                         ▼
                                                  Persist state
```

論理的には次の2層で構成する。

- **SignalSift Core**: 取得、正規化、ルール評価、スコア、記事キー、状態、通知境界
- **Security Profile**: 情報源、セキュリティ用キーワード、CISA KEVアダプター、Slack向け表示分類

Coreの共通モデルにCVE専用必須フィールドなどのセキュリティ固有前提を持ち込まない。

## 6. 実行インターフェース

### 6.1 CLI

MVPが公開するコマンドは次の1つとする。

```bash
signalsift run
```

コマンドは1回の処理サイクルを実行して終了する。待機、ループ、スケジューリングは行わない。

設定ファイルの既定位置は以下とする。

```text
config/sources.yaml
config/filters.yaml
```

状態ファイルの論理パスは以下とする。

```text
state/notified.json
```

GitHub Actionsは `state` ブランチの内容を上記パスへ準備してからCLIを起動し、CLI終了後に変更がある場合だけ同ブランチへコミット・pushする。Git操作そのものをCoreのドメイン処理へ混在させない。

### 6.2 環境変数

| 変数 | 必須 | 用途 | 取扱い |
|---|---:|---|---|
| `SLACK_WEBHOOK_URL` | はい | Slack Incoming Webhook送信先 | GitHub Actions Secretsから注入し、ログへ出力しない |

MVPではLLM用APIキーや外部DB接続情報を要求しない。

### 6.3 終了コード

| コード | 意味 |
|---:|---|
| `0` | 全有効情報源の処理、必要なSlack送信、必要な状態保存が成功した |
| `1` | 取得・Slack送信・状態保存のいずれかに部分障害または全体障害があった |
| `2` | 設定不正、必須秘密情報の欠落など、処理開始不能な利用・構成エラー |

一部情報源や一部Slack送信が失敗しても、残りの処理と成功分の状態更新を完了してから終了する。状態永続化に失敗した場合は必ず非ゼロで終了する。

## 7. 設定仕様

### 7.1 共通規則

- YAMLはUTF-8で保存する。
- 未知のトップレベルキーまたは未知のフィールドは設定ミスとして拒否する。
- 必須値の欠落、型不一致、範囲外の数値、情報源IDの重複は起動前エラーとする。
- キーワードの照合順に依存する仕様は設けない。
- YAMLにCSSセレクター、XPath、JSONPath、変換用正規表現列などの解析DSLを追加しない。
- 設定は運用者が変更する値を表し、解析手順はコードに置く。

### 7.2 `config/sources.yaml`

トップレベルは `sources` の配列とする。

| フィールド | 型 | 必須 | 制約・意味 |
|---|---|---:|---|
| `id` | string | はい | リポジトリ内で一意。小文字英数字と `_` を推奨 |
| `name` | string | はい | ログとSlackに表示する名称 |
| `enabled` | boolean | はい | `false` の情報源は取得も検証対象処理も行わない |
| `type` | enum | はい | `rss` または `json` |
| `url` | string | はい | HTTPSの取得先URL |
| `adapter` | string | 条件付き | `json` かつ固有アダプター利用時に指定 |
| `priority` | integer | はい | 1～3。スコアへ変換する |
| `force_notify_new_entries` | boolean | いいえ | 新規構造化項目を閾値に関係なく採用する。既定 `false` |
| `source_filter` | object | いいえ | 媒体固有の明白なノイズを除く |
| `notes` | string | いいえ | 人間向けメモ。処理結果に影響しない |

`source_filter` は以下を受け付ける。

| フィールド | 型 | 意味 |
|---|---|---|
| `include_any` | string[] | 1語以上一致した記事だけを通す |
| `exclude` | string[] | 1語以上一致した記事を除外する |

両方を指定した場合は `exclude` を先に評価し、除外一致は常に優先する。

MVPの有効な情報源は以下の7件である。

| ID | 種別 | 優先度 | 役割 |
|---|---|---:|---|
| `jpcert` | RSS/RDF | 3 | 国内向け運用情報、注意喚起 |
| `cisa_kev` | JSON + `cisa_kev` | 3 | 悪用確認済み脆弱性 |
| `flatt` | RSS | 3 | 国内AppSec、サプライチェーン分析 |
| `wiz` | RSS | 3 | クラウド、脆弱性、AI/MCP研究 |
| `stepsecurity` | RSS | 3 | GitHub Actions、パッケージ侵害 |
| `aikido` | RSS | 2 | OSSマルウェア、パッケージ侵害 |
| `google_threat_intel` | RSS | 3 | 大規模攻撃、悪用、脅威研究 |

コメントアウトされた候補は設定値ではなく、MVPで取得・実装・試験しない。

MVPでは、アダプターなしの汎用JSONスキーマは定義しない。`type: json` の有効情報源には登録済みアダプターを必須とし、未知のアダプター名は設定エラーとする。

### 7.3 `config/filters.yaml`

トップレベル項目は以下とする。

| 項目 | 意味 |
|---|---|
| `notification` | 通知閾値、初回期間、状態保持期間、個別通知上限 |
| `negative_terms` | 明白なノイズ記事を減点する語 |
| `rules` | 主題を成立させる基本ルール |
| `boosts` | 緊急性、深刻度、実用性による加点 |
| `watch_terms` | 組織内で関心が高い技術語による加点 |
| `source_priority_score` | 情報源優先度から得点への写像 |

`notification` の現在値は以下とする。

| 項目 | 現在値 | 意味 |
|---|---:|---|
| `threshold` | 7 | 採用に必要な最低得点 |
| `initial_lookback_hours` | 24 | 状態が存在しない初回実行で扱う期間 |
| `state_retention_days` | 180 | 通知履歴の保持期間 |
| `max_individual_messages_per_run` | 5 | 個別通知を用いる最大採用件数 |

数値制約は、閾値1以上、初回期間1以上、保持期間1以上、個別通知上限1以上とする。

## 8. 共通データモデル

### 8.1 `NormalizedItem`

全FetcherとAdapterは次のモデルを返す。

| フィールド | 型 | 必須 | 意味 |
|---|---|---:|---|
| `id` | string/null | はい | feed GUID、entry ID等。安定IDがなければ `null` |
| `source_id` | string | はい | `sources.yaml` のID |
| `title` | string | はい | 表示用タイトル。空文字不可 |
| `url` | string/null | はい | 原記事URL。取得できなければ `null` |
| `published_at` | datetime/null | はい | UTCへ正規化したタイムゾーン付き日時 |
| `summary` | string | はい | 要約。なければ空文字 |
| `content` | string | はい | Feed内本文。なければ空文字 |
| `categories` | string[] | はい | タグ・カテゴリ。なければ空配列 |
| `external_ids` | string[] | はい | CVE、GHSA等の外部ID。なければ空配列 |
| `raw_metadata` | object | はい | アダプター固有の補助情報。下流の必須判断には使わない |

`raw_metadata` はログやデバッグ用の最小限の値だけを保持し、取得レスポンス全体の保存場所にはしない。

### 8.2 内部評価結果

フィルター評価後は少なくとも次の値を保持する。

| フィールド | 型 | 意味 |
|---|---|---|
| `score` | integer | 合計得点 |
| `why_matched` | string[] | 得点・強制採用の決定論的な理由 |
| `matched_topic` | enum/string | `supply-chain`、`vulnerability`、`ai-security`等の主分類 |
| `article_key` | string | 通知済み判定に使う安定キー |

`why_matched` は同じ入力と設定から常に同じ順序・内容で生成する。秘密情報、記事本文全文、Webhook URLを含めない。

## 9. 取得・正規化仕様

### 9.1 共通HTTP要件

- 設定されたHTTPS URLだけを取得する。
- TLS証明書検証を無効化しない。
- 接続と応答を合わせたタイムアウトを1リクエスト10秒とする。
- 最大レスポンスサイズを5 MiBとし、超過時はその情報源を失敗とする。
- リダイレクトは最大3回とし、HTTPS以外への遷移を拒否する。
- 成功扱いはHTTP 2xxだけとする。
- 記事本文中のURLやFeed内リンクを追加取得しない。
- レスポンスをコード、テンプレート、シェル入力として実行しない。
- User-Agentには `SignalSift/<version>` を設定する。

情報源は順次処理してよい。MVPでは非同期処理、キュー、リトライ基盤を必須としない。HTTPの自動再試行を行う場合も、同一実行内で一時的障害に対して最大2回、短い指数バックオフまでとする。

### 9.2 RSS / Atom / RDF

汎用FetcherはRSS 2.0、Atom、RSS 1.0/RDFを同一のコードパスで処理する。

対応する代表的な写像は以下とする。

| 共通フィールド | Feed候補 |
|---|---|
| `id` | `guid`、Atom `id` |
| `title` | `title` |
| `url` | alternate link、`link` |
| `published_at` | `published`、`updated`、`pubDate`、`dc:date` の順で利用可能な値 |
| `summary` | `summary`、`description` |
| `content` | Atom content、content:encoded |
| `categories` | category、tag、subject |

- XML外部実体とDTDを処理しない安全なパーサーを用いる。
- 壊れた1エントリーは警告してスキップし、解析可能な他エントリーは継続する。
- Feed全体が解析不能なら情報源失敗とする。
- タイトルが空のエントリーは記事として扱わずスキップする。
- HTMLを含むsummary/contentはテキスト化し、スクリプト、スタイル、制御文字を除去する。
- 日時にタイムゾーンがない場合はUTCと解釈し、その事実をデバッグログへ残す。
- CVEやGHSA等の外部IDを抽出する場合は `external_ids` へ格納するが、Coreモデルへ専用フィールドを追加しない。

少なくとも2つの通常RSS情報源が、情報源固有クラスなしで同じFetcherを通ることを試験する。

### 9.3 CISA KEVアダプター

Adapterレジストリーは小さな静的辞書とする。

```python
ADAPTERS = {
    "cisa_kev": fetch_cisa_kev,
}
```

CISA KEVの各 `vulnerabilities[]` 要素を1件の `NormalizedItem` に変換する。

| KEVフィールド | 正規化先 |
|---|---|
| `cveID` | `id` および `external_ids[]` |
| `vulnerabilityName` | `title` |
| `dateAdded` | `published_at`。日付の00:00:00 UTCとして扱う |
| `shortDescription` | `summary` |
| `requiredAction` | `content` の一部 |
| `vendorProject`、`product` | `content` と `raw_metadata` |
| `knownRansomwareCampaignUse`、`dueDate`、`notes` | `raw_metadata`。必要な表示文脈は `content` に含めてよい |

原記事URLがKEV項目にない場合は、CISAの該当カタログまたはCVE詳細へ到達可能な安定したHTTPS URLを生成する。

`force_notify_new_entries: true` の情報源では、保存済みの初回基準日時以降に追加され、かつ状態に存在しない項目を閾値に関係なく採用する。ただし次はバイパスしない。

- 保存済みの初回基準日時
- 記事重複判定
- Slack成功後にのみ状態更新する規則

強制採用時は `why_matched` に `force-notify:cisa_kev` を含める。

### 9.4 取得障害の分離

1つの情報源でHTTP、サイズ、解析、スキーマのエラーが起きても他の情報源を処理する。失敗した情報源から部分的で信頼できないデータを通知しない。全情報源の処理終了後、失敗が1件以上あれば終了コード1とする。

## 10. テキスト照合仕様

照合対象文字列は以下をこの順に連結したものとする。

```text
title + summary + content + categories + external_ids
```

照合時は次を行う。

- UnicodeをNFKC正規化する。
- 英字の大文字・小文字を区別しない。
- HTMLタグを除去し、HTML entityをテキストへ戻す。
- 連続する空白を1文字へ畳み込む。
- 日本語および記号を含む語は部分文字列一致とする。
- 英数字だけの単語・フレーズは単語境界を考慮し、例えば `event` を `prevent` に一致させない。
- `CVE-` のように末尾が記号のprefix語は、そのprefixから始まるトークンへ一致させる。
- 同じ語が複数回現れても、同じルールの得点は1回だけ加算する。

この正規化は照合用コピーに対して行い、Slackに表示する原文タイトルの文字種を不必要に変更しない。

## 11. フィルター・スコアリング仕様

### 11.1 評価順序

記事ごとに以下の順で評価する。

1. 正規化データの最低要件確認
2. 情報源固有 `exclude`
3. 情報源固有 `include_any`
4. グローバル `negative_terms` の減点判定
5. 主題ルール `rules`
6. 情報源優先度
7. `boosts`
8. `watch_terms`
9. 強制採用判定
10. 閾値判定

### 11.2 負の語による減点

`negative_terms` は、正の主題シグナルを持つ記事を一律に破棄せず、マーケティング等の明白なノイズを閾値未満へ下げるために用いる。

- `product announcement` または `release notes` だけに一致した場合は記事ごとに −3点とする。
- 上記以外の負の語に1つ以上一致した場合は記事ごとに −5点とする。
- 複数の負の語が一致しても重複減点しない。
- −3対象と−5対象の両方に一致した場合は −5だけを適用する。
- 一致した場合は `why_matched` に `negative:<term>:<penalty>` を含め、得点を再現可能にする。

情報源固有の `exclude` は得点に関係なく即時除外する。グローバル負の語は減点なので、十分に強い侵害・悪用シグナルを持つ記事は採用され得る。

### 11.3 主題ルール

ルール形式と判定は以下とする。

- `any`: 列挙語の1つ以上が一致すればルール成立。
- `all_groups`: 各グループ内で1語以上一致し、すべてのグループが成立すればルール成立。
- 1ルールが成立するたび、そのルールの `score` を1回加算する。
- 複数の主題ルールが成立した場合はそれぞれ加算する。

Security Profileでは以下を定義する。

| ルール | 条件 | 得点 |
|---|---|---:|
| `supply_chain` | 強いサプライチェーン侵害語のいずれか | +3 |
| `vulnerability` | 脆弱性文脈 AND 悪用・重大影響文脈 | +3 |
| `ai_security` | AI文脈 AND セキュリティ文脈 | +3 |

単なるCVE言及は `vulnerability` を成立させない。単なるAI製品発表は `ai_security` を成立させない。

通常記事の合計得点は次の式で求める。

```text
score = source priority
      + 成立した主題ルール
      + 成立したboost
      + watch term（一致時1回）
      + negative term penalty（一致時1回）
```

### 11.4 情報源優先度

`source_priority_score` に従って必ず1回加算する。

| priority | 得点 |
|---:|---:|
| 1 | +1 |
| 2 | +2 |
| 3 | +3 |

情報源優先度だけで通知閾値へ到達してはならない。

### 11.5 ブースト

成立したブーストごとに1回加算する。

| ブースト | 代表的条件 | 得点 |
|---|---|---:|
| `active_exploitation` | in-the-wild、known exploited、KEV等 | +4 |
| `severe_impact` | pre-auth RCE、認証回避、0-day等 | +3 |
| `actionable` | affected versions、mitigation、IOC等 | +2 |

ブーストは主題ルールの代替ではない。強制採用対象を除き、主題ルールが1つも成立しない記事は、ブーストと情報源優先度だけで閾値以上になっても通知しない。

### 11.6 Watch term

`watch_terms.terms` の1語以上に一致した場合、`watch_terms.score` を1回だけ加算する。複数語一致しても語数分は加算しない。一致した具体語は `why_matched` に含める。

### 11.7 採用条件

通常記事は、以下をすべて満たした場合に採用する。

```text
主題ルールが1つ以上成立
AND score >= notification.threshold
AND 情報源固有フィルターで除外されていない
```

`force_notify_new_entries` の対象記事は、主題ルールと閾値だけを置き換える。最低要件、保存済みの初回基準日時、重複排除は通常どおり適用する。

### 11.8 `why_matched`

採用記事には、人間が得点を再現できる理由を付与する。順序は以下とする。

1. 成立した主題ルール
2. ルール内で一致した代表語
3. 成立したブースト
4. 負の語と減点
5. 一致したwatch term
6. `source-priority:<n>`
7. 強制採用理由

同一理由は重複させない。例:

```text
supply-chain
malicious-package
npm
actionable
source-priority:3
```

## 12. 初回実行と記事日時

`state/notified.json` が存在しない実行を初回実行とする。初回実行開始時に次を計算し、状態の `initial_cutoff_at` へ保存する。

```text
initial_cutoff_at = 初回実行開始時刻 - initial_lookback_hours
```

初回とそれ以降の全実行で、`initial_cutoff_at` 以降に公開された記事だけを候補にする。境界時刻と同じ記事は含める。これにより初回に除外した過去記事が2回目の実行で通知されることを防ぎ、初回以降に公開された記事は一時的な実行停止が24時間を超えても候補にできる。

- RSS等は `published_at` を使用する。
- CISA KEVは `dateAdded` を使用する。
- `published_at` が不明な記事は、過去記事か新着記事かを安全に判定できないため除外し、ログに `published_at=unknown` を記録する。
- 未来日時が現在より24時間を超えている記事は不正データとしてスキップする。

## 13. 記事重複排除

### 13.1 基本原則

Slackへの送信に成功した同一記事を再通知しない。重複排除はセキュリティイベント単位ではなく記事単位とする。同じCVEを扱う別媒体の記事は別記事として扱える。

### 13.2 記事キー生成

利用可能な最初の識別子を次の優先順位で使う。

1. 安定したfeed GUID / entry ID
2. 正規化したcanonical URL
3. `source_id + 正規化タイトル`

衝突と機微な生値の露出を避けるため、保存キーは次の概念入力のSHA-256を16進小文字で表した値とする。

```text
guid:<source_id>:<id>
url:<normalized_url>
title:<source_id>:<normalized_title>
```

feed IDが恒久IDではなく毎回変わると明らかな場合は使用せずURLへフォールバックする。

### 13.3 URL正規化

- schemeとhostを小文字化する。
- IDN hostは一貫したASCII表現へ正規化する。
- 既定ポート `:80` / `:443` を除く。
- fragmentを除く。
- `utm_*`、`fbclid`、`gclid`等の一般的な追跡パラメーターを除く。
- 残るquery parameterはキー、値の順に安定ソートする。
- 空でないpathの末尾 `/` の差を除く。ただしroot `/` は維持する。
- scheme自体は保持し、HTTPとHTTPSを自動的に同一視しない。

タイトルのフォールバック正規化ではNFKC、大文字小文字の統一、前後空白除去、連続空白の圧縮を行う。

### 13.4 実行内重複

同じ実行内で同一 `article_key` が複数回現れた場合も1件だけを残す。先に処理された記事を採用し、後続をduplicateとして数える。

## 14. 状態管理

### 14.1 保存場所と形式

永続状態は専用Gitブランチ `state` の `state/notified.json` だけに保存する。

```json
{
  "version": 1,
  "initial_cutoff_at": "2026-08-09T01:23:45Z",
  "items": {
    "<article_key>": {
      "source": "wiz",
      "title": "...",
      "url": "https://...",
      "published_at": "2026-08-10T00:00:00Z",
      "notified_at": "2026-08-10T01:23:45Z"
    }
  }
}
```

日時はUTCのISO 8601形式で保存する。元記事日時が不明な場合、`published_at` は `null` とする。`initial_cutoff_at` は初回作成後に変更しない。

### 14.2 読み込み

- ファイル不在は初回実行として扱い、実行開始時刻と設定から `initial_cutoff_at` を持つ空のversion 1状態を生成する。
- 未対応の `version` は推測で移行せず構成エラーとする。
- `initial_cutoff_at` の欠落または日時不正は、大量再通知を防ぐため構成エラーとする。
- JSON破損は空状態へ自動フォールバックしない。大量再通知を避けるため実行を中止する。
- 余分な未知フィールドは将来互換性のため読み飛ばしてよいが、必須構造の型不正は拒否する。

### 14.3 更新タイミング

記事はSlackが成功を返した後だけ状態へ追加する。送信前、送信失敗、タイムアウト時には追加しない。

個別通知では各成功記事を追加する。ダイジェスト通知では、ダイジェスト全体が成功した後に、そのダイジェストへ実際に含めた全記事を追加する。

### 14.4 保持期間

実行時に、`notified_at` が実行開始時刻から `state_retention_days` より古いレコードを削除する。境界日時と同じレコードは保持する。日時不正のレコードは警告して保持し、黙って重複防止を失わない。

pruneだけで状態が変わった場合も永続化対象とする。

### 14.5 Git永続化

- `state` ブランチには `state/notified.json` だけを置く。
- ファイル内容に実質的な変更がある場合だけcommit・pushする。
- `main` ブランチへ実行時状態をcommitしない。
- GitHub Actionsの単一concurrency group `signalsift-state` で同時更新を防ぐ。
- `cancel-in-progress: false` とし、進行中の状態更新を新しい実行で中断しない。
- Slack成功後にGit pushが失敗した場合は終了コード1とする。この場合、次回に稀な再通知が起こり得るが、通知漏れを避けるat-least-onceとして許容する。

## 15. Slack通知

### 15.1 送信方式

GitHub Actions Secret `SLACK_WEBHOOK_URL` のIncoming WebhookへHTTPS POSTする。成功はHTTP 2xxとする。Webhookレスポンスが非2xxまたはタイムアウトなら失敗とする。

通知本文に翻訳やLLM要約を必須としない。タイトルと要約は取得元の言語を維持する。

### 15.2 個別通知

1実行の採用・未通知記事数が `max_individual_messages_per_run` 以下なら、記事ごとに1メッセージ送る。

表示項目は以下とする。

```text
🚨 [分類] タイトル

Source: 情報源名
Why: 理由1 / 理由2 / ...
Published: YYYY-MM-DD HH:mm UTC または Unknown

要約

URL
```

- 分類は成立した主題ルールから決定する。複数成立時は `Supply Chain`、`Vulnerability`、`AI Security` の順で主表示を選び、他分類はWhyに残す。
- 要約はsummaryを優先し、なければcontentから作る。
- 要約は空白を整えたプレーンテキストで最大300文字とし、超過時は省略記号を付ける。
- URLが存在しない場合はURL行を省略する。
- Slackで特別扱いされる `&`、`<`、`>` を安全にエスケープする。
- `@channel` 等を意図せずメンションとして解釈させない。

### 15.3 ダイジェスト通知

採用・未通知記事数が個別通知上限を超える場合は、チャンネルを大量通知しないため1つ以上のコンパクトなダイジェストとして送る。

- 記事を得点の降順、公開日時の降順、`article_key` の昇順で安定ソートする。
- 各記事には分類、タイトル、情報源、主要なWhy、URLを含める。
- Slackのペイロード上限を超える場合だけ複数ダイジェストへ分割する。
- 1つのダイジェスト送信が成功したら、そのダイジェストに含まれた記事だけを状態へ追加する。
- 後続ダイジェストが失敗しても成功済み分を巻き戻さない。

### 15.4 送信失敗

- ある個別通知が失敗しても、他の記事の送信を継続する。
- 失敗記事は状態へ追加せず、次回実行で再試行可能にする。
- Slack送信失敗が1件以上あれば、成功分の状態を保存した後に終了コード1とする。
- Webhook URLおよびWebhook URLから導出した情報をログへ出さない。

## 16. パイプライン詳細

1回の実行は次の順序を厳守する。

1. 設定を読み込み、完全に検証する。
2. `SLACK_WEBHOOK_URL` の存在を確認する。
3. 通知済み状態を読み込む。
4. 保持期限を過ぎた状態をpruneする。
5. 有効な情報源を設定順に処理する。
6. 情報源を取得し、共通モデルへ正規化する。
7. 情報源固有フィルターを適用する。
8. 保存済みの初回基準日時を適用する。
9. グローバルルールとスコアを評価する。
10. `article_key` を生成し、通知済み・実行内重複を除外する。
11. 採用記事を安定ソートする。
12. 個別またはダイジェストでSlackへ送る。
13. 成功した記事だけ状態へ追加する。
14. 状態変更があれば原子的にローカルファイルへ書く。
15. 実行集計をログ出力して終了する。
16. GitHub Actionsが状態差分を `state` ブランチへ保存する。

ローカル状態ファイルの更新は、同一ディレクトリの一時ファイルへ完全なJSONを書き、flush後にrenameする方式など、途中書き込みが見えない原子的な方法を用いる。

## 17. ログ・可観測性

ログは標準出力・標準エラーへ出し、GitHub Actionsから確認できるようにする。少なくとも情報源ごとに以下を1行または一まとまりで記録する。

| 項目 | 意味 |
|---|---|
| `source_id` | 情報源ID |
| `fetch_status` | `ok` / `failed` |
| `fetched_count` | 正規化前後を通じて取得できた記事数 |
| `candidate_count` | 情報源フィルターと保存済みの初回基準日時を通過した数 |
| `matched_count` | グローバル採用条件を満たした数 |
| `duplicate_count` | 状態または実行内で重複した数 |
| `notified_count` | Slack成功後に通知済みとなった数 |

実行終了時に全体集計、状態の追加・削除件数、所要時間、終了状態を出す。

通常ログには記事本文全文、レスポンス本文全文、環境変数、Webhook URLを出さない。エラーは情報源ID、段階、例外種別、人が対応可能な短い説明を含める。

## 18. GitHub Actions仕様

ワークフローは次のパスに置く。

```text
.github/workflows/signalsift.yml
```

必須設定は以下とする。

| 項目 | 仕様 |
|---|---|
| Trigger | `schedule` と `workflow_dispatch` |
| Cron | `17,47 * * * *` |
| Runtime | Python 3.12以上 |
| Permissions | `contents: write` のみを明示 |
| Concurrency group | `signalsift-state` |
| Cancel in progress | `false` |
| Timeout | 10分 |
| Secret | `SLACK_WEBHOOK_URL` |

ワークフローは概ね次を行う。

1. 実行対象commitをcheckoutする。認証情報の不要な永続化を避ける設定を用いる。
2. Pythonとロック済み依存関係を準備する。
3. `state` ブランチから状態ファイルを取得する。ブランチ不在は初回として扱う。
4. `signalsift run` を実行する。
5. CLIが部分障害を報告しても、成功済み通知の状態保存を試みる。
6. 状態ファイルに差分がある場合だけ `state` ブランチへcommit・pushする。
7. CLIまたは状態保存が失敗していればジョブを失敗として終了する。

Actions Cacheを通知履歴の正本にしない。

## 19. セキュリティ要件

- すべての外部コンテンツを信頼できない入力として扱う。
- HTTPSと証明書検証を必須とする。
- XML外部実体、DTD、任意コード実行を禁止する。
- 応答サイズ、リダイレクト回数、HTTPタイムアウトを制限する。
- Feedが示す任意リンクを自動巡回しない。
- Slack表示文字列をエスケープし、意図しないメンションを抑止する。
- Webhook URLをリポジトリ、状態、例外メッセージ、ログへ保存しない。
- GitHub Actionsの権限は `contents: write` に限定し、不要な権限を付与しない。
- 依存関係はバージョンを固定またはロックし、CIで再現可能にする。
- GitHub Actionsはcommit SHAで固定し、更新時に明示レビューすることを推奨する。
- 取得コンテンツをHTMLとして再配信せず、Slackには安全なプレーンテキストを送る。

## 20. 性能・信頼性要件

### 20.1 性能

- 通常の7情報源構成でGitHub Actionsの10分timeout内に完了する。
- 1情報源の遅延はHTTP timeoutで上限を設ける。
- 全レスポンスを無制限にメモリへ読み込まない。
- MVPの想定規模では単一プロセス、単一ジョブで処理する。

### 20.2 配信保証

配信意味論はat-least-onceとする。

```text
Slack成功 → 状態更新 → 状態永続化
```

Slack成功後かつ状態永続化前の障害では重複が起こり得る。重要通知の恒久的欠落より稀な重複を優先する。

### 20.3 決定性

同じ設定、状態、実行時刻、取得入力に対して、採否、得点、`why_matched`、並び順、記事キーは同じ結果になること。

## 21. モジュール責務

推奨する最小構成と責務は以下とする。具体的な関数分割は実装に委ねる。

| ファイル | 主責務 |
|---|---|
| `cli.py` | 設定読込、run-onceオーケストレーション、終了コード |
| `models.py` | 設定モデル、`NormalizedItem`、評価結果 |
| `fetch.py` | 制限付きHTTP、汎用RSS/Atom/RDF取得 |
| `adapters.py` | CISA KEV変換、静的Adapterレジストリー |
| `filter.py` | source filter、複合ルール、得点、理由 |
| `dedupe.py` | URL・タイトル正規化、`article_key` |
| `state.py` | JSON状態読込、prune、原子的保存 |
| `slack.py` | 個別・ダイジェスト整形、Webhook送信 |

設定ローダーが小さい間は `cli.py` または `models.py` に含め、必要性が現れる前にファイルを増やさない。

## 22. テスト仕様

テストはネットワークを使わず、ローカルのRSS、Atom、RDF、JSON、状態、Slack応答フィクスチャを用いる。

### 22.1 必須受入ケース

| ID | 入力・条件 | 期待結果 |
|---|---|---|
| AC-01 | 悪性npmパッケージによるサプライチェーン事件 | 採用されSlack通知される |
| AC-02 | supply chainを含むウェビナー・製品宣伝 | `negative_terms` の減点で閾値未満となる |
| AC-03 | CVE + exploited in the wild | 採用される |
| AC-04 | 重大性・悪用文脈のない通常CVE | 不採用となる |
| AC-05 | MCPまたはAI agent + vulnerability/attack | 採用される |
| AC-06 | セキュリティ文脈のないAI製品発表 | 不採用となる |
| AC-07 | 同じ記事を2回処理 | Slack成功後、2回目は通知されない |
| AC-08 | Slackが非2xxを返す | 状態に追加されず終了コード1となる |
| AC-09 | 初回実行で24時間より古い記事 | 通知されない |
| AC-10 | 初回実行で日時不明の記事 | 通知されない |
| AC-11 | 2種類以上の通常Feed | 同じ汎用Fetcherで正規化される |
| AC-12 | 1情報源が取得失敗 | 他情報源は処理・通知され、最終終了コード1となる |
| AC-13 | Slack成功後に状態を保存 | 記事がversion 1状態へ追加される |
| AC-14 | 6件以上が採用 | 個別連投せずダイジェストになる |
| AC-15 | CISA KEVの新規項目 | `dateAdded` を使い、未通知なら強制採用される |
| AC-16 | URLのUTMとfragmentだけが異なる2記事 | 同じ `article_key` になる |
| AC-17 | 状態JSONが破損 | 空状態で続行せず安全に失敗する |
| AC-18 | 180日より古い状態 | pruneされ、状態差分が保存される |
| AC-19 | 初回に除外した古いFeed記事を2回目にも取得 | 保存した基準日時により引き続き通知されない |

### 22.2 単体試験の重点

- 各複合ルールのAND/OR境界
- 大文字小文字、Unicode、和英キーワード
- ルール得点が出現回数で重複加算されないこと
- watch termが複数一致しても1回加算であること
- source filterでexcludeがincludeより優先されること
- 記事キーの3段階フォールバック
- URL追跡パラメーター除去
- Slackエスケープと文字数制限
- 状態保持期間の境界値
- CISA KEVフィールドの正規化
- HTTP timeout、サイズ、redirect、非2xx

### 22.3 テスト禁止事項

- 公開FeedやSlackへ実通信しない。
- 実Webhook URLをフィクスチャに含めない。
- 実行順や現在日時に依存する不安定なテストにしない。時計とHTTP応答は注入または固定する。

## 23. 受入完了条件

MVPは以下をすべて満たしたとき完成とする。

- `signalsift run` が1回の完全な処理を実行して終了する。
- 有効な7情報源を仕様どおり処理できる。
- 通常Feedが情報源固有クラスなしで正規化される。
- CISA KEVが専用アダプターで正規化される。
- フィルターと得点が設定駆動かつ説明可能である。
- 普通のCVEと一般的なAIニュースを通知しない。
- 採用記事だけをSlackへ通知する。
- Slack成功前に記事を通知済みにしない。
- 同一記事を正常時に再通知しない。
- 初回に過去記事を大量送信しない。
- 1情報源の障害で他情報源を停止しない。
- GitHub-hosted runnerをまたいで状態が維持される。
- scheduleとworkflow_dispatchの両方で動作する。
- 必須受入ケースがローカルフィクスチャで成功する。
- 外部DB、常駐サービス、必須LLMを必要としない。

## 24. 将来拡張の扱い

以下は運用上の実需要が確認された場合だけ検討する。

- イベント単位の重複排除
- EPSS等のエンリッチメント
- 組織固有の製品・パッケージwatchlist
- 中優先度の日次ダイジェスト
- 選定済み記事への日本語LLM要約
- Slack threadによる更新
- 2つ目の実プロファイルと、それに伴う設定ディレクトリ再編

LLMを追加する場合もfeature flagで無効化可能とし、決定論的な選定処理をフォールバックとして維持する。秘密情報や内部資産情報をLLMへ送らない。

## 25. 前提として確定した補足判断

既存資料で方向性のみ示されていた項目について、本書ではMVPの挙動を一意にするため以下のように確定した。

- `negative_terms` は記事ごとに重複させず、マーケティング系を−5、一般製品発表系を−3とする。
- 主題ルール未成立の記事は、加点だけで通知しない。
- watch termの加点は記事ごとに1回とする。
- 初回実行で日時不明の記事は除外する。
- 初回基準日時を状態へ保存し、2回目以降の過去記事バックフィルも防ぐ。
- 部分障害後も成功分を保存し、最終終了コードは1とする。
- 5件を超える採用記事はダイジェストへ切り替える。
- アダプターなし汎用JSONは、実需要のあるスキーマがないためMVP対象外とする。

これらは、低ノイズ、説明可能性、小さな実装、通知漏れより稀な重複を許容するという既存の設計原則から導出したものである。

## 付録A: 参照資料

- `AGENTS.md`: プロジェクト原則と実装制約
- `README.md`: プロダクト概要と運用モデル
- `docs/DESIGN.md`: アーキテクチャ判断
- `config/sources.yaml`: 現行Security Profileの情報源
- `config/filters.yaml`: 現行Security Profileの選定ポリシー
- `CODEX_PROMPT.md`: MVP実装方針と完了基準
