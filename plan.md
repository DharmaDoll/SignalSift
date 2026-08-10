# SignalSift MVP 実装チェックリスト

このチェックリストは [アプリケーション仕様書](docs/SPECIFICATION.md) を実装可能な単位へ分割したものである。上から順に進めることを基本とし、各フェーズの完了条件を満たしてから次へ進む。

## 進め方

- `[ ]` を未完了、`[x]` を完了として更新する。
- 各機能は、実装と同時にその境界を証明するテストを追加する。
- 公開FeedやSlackを自動テストから呼び出さない。
- 既存の `config/sources.yaml` と `config/filters.yaml` をSecurity Profileの正本として扱う。
- 実装中に仕様変更が必要になった場合は、コードだけを先行変更せず `docs/SPECIFICATION.md` と本チェックリストを更新する。
- 将来機能のための抽象化を追加せず、MVPで実際に使う経路だけを実装する。

## フェーズ0: 実装基盤とプロジェクト設定

### 0.1 Pythonパッケージ基盤

- [ ] `pyproject.toml` を作成する。
- [ ] Python要件を `>=3.12` として定義する。
- [ ] `src` レイアウトで `signalsift` パッケージを定義する。
- [ ] `signalsift = signalsift.cli:main` のCLIエントリーポイントを定義する。
- [ ] `src/signalsift/__init__.py` を作成する。
- [ ] アプリケーションバージョンを一箇所で管理できるようにする。
- [ ] runtime依存関係を最小限に選定する。
- [ ] YAML読込、HTTP、Feed解析に必要な依存関係だけを追加する。
- [ ] test依存関係として `pytest` 等の必要最小限を追加する。
- [ ] 依存関係のバージョンを固定またはロックする。
- [ ] `.gitignore` に仮想環境、Pythonキャッシュ、テストキャッシュ、coverage出力を追加する。

### 0.2 初期ディレクトリ

- [ ] `src/signalsift/cli.py` を作成する。
- [ ] `src/signalsift/models.py` を作成する。
- [ ] `src/signalsift/fetch.py` を作成する。
- [ ] `src/signalsift/adapters.py` を作成する。
- [ ] `src/signalsift/filter.py` を作成する。
- [ ] `src/signalsift/dedupe.py` を作成する。
- [ ] `src/signalsift/state.py` を作成する。
- [ ] `src/signalsift/slack.py` を作成する。
- [ ] `tests/` と `tests/fixtures/` を作成する。
- [ ] 空の追加モジュール、plugin基盤、profiles階層を作らないことを確認する。

### 0.3 基本ツール設定

- [ ] テスト実行コマンドを決め、ローカルで空のテストスイートが起動することを確認する。
- [ ] formatter/linter/type checkerを採用する場合は、MVPに必要な最小構成にする。
- [ ] CIとローカルで同じテストコマンドを使えるようにする。
- [ ] `signalsift --help` または `signalsift run --help` が起動できる最小CLIを用意する。

### フェーズ0完了条件

- [ ] Python 3.12環境でパッケージをインストールできる。
- [ ] `signalsift` コマンドが解決される。
- [ ] テストコマンドが成功する。
- [ ] 不要なインフラ・フレームワーク依存がない。

## フェーズ1: 設定ローダー

### 1.1 設定モデル

- [ ] `SourceConfig` を定義する。
- [ ] `id`、`name`、`enabled`、`type`、`url`、`priority` を表現する。
- [ ] `adapter`、`force_notify_new_entries`、`source_filter`、`notes` を表現する。
- [ ] `SourceFilterConfig` に `include_any` と `exclude` を定義する。
- [ ] notification設定モデルを定義する。
- [ ] rule、all_groups、boost、watch_terms、source_priority_scoreの設定モデルを定義する。
- [ ] 未知フィールドを検出できる構造にする。
- [ ] 設定モデルをSecurity Profile固有語へ不必要に結合しない。

### 1.2 `sources.yaml` 読込と検証

- [ ] UTF-8 YAMLとして読み込む。
- [ ] `sources` が配列であることを検証する。
- [ ] 必須フィールドの欠落をエラーにする。
- [ ] フィールド型の不一致をエラーにする。
- [ ] source IDの重複をエラーにする。
- [ ] `type` が `rss` または `json` であることを検証する。
- [ ] URLが有効なHTTPS URLであることを検証する。
- [ ] priorityが1～3であることを検証する。
- [ ] `force_notify_new_entries` の既定値を `false` にする。
- [ ] `include_any` と `exclude` の各要素が空でない文字列であることを検証する。
- [ ] `type: json` の有効情報源に登録済みadapterが必要となる検証境界を用意する。
- [ ] コメントアウトされた候補情報源が読み込まれないことを確認する。
- [ ] `enabled: false` の情報源を実行対象から除外できるようにする。

### 1.3 `filters.yaml` 読込と検証

- [ ] 必須トップレベル項目を検証する。
- [ ] `threshold >= 1` を検証する。
- [ ] `initial_lookback_hours >= 1` を検証する。
- [ ] `state_retention_days >= 1` を検証する。
- [ ] `max_individual_messages_per_run >= 1` を検証する。
- [ ] ruleとboostのscoreが整数であることを検証する。
- [ ] `any` と `all_groups` の構造を検証する。
- [ ] 空のキーワードと空のrule groupを拒否する。
- [ ] `source_priority_score` にpriority 1～3の写像があることを検証する。
- [ ] 未知のトップレベルキーと未知フィールドを拒否する。

### 1.4 設定テスト

- [ ] 現行2設定ファイルを正常に読み込めるテストを追加する。
- [ ] source ID重複の失敗テストを追加する。
- [ ] HTTP URL拒否のテストを追加する。
- [ ] priority範囲外の失敗テストを追加する。
- [ ] notification数値境界のテストを追加する。
- [ ] 未知フィールド拒否のテストを追加する。
- [ ] 不正なrule構造の失敗テストを追加する。
- [ ] adapter不明の失敗テストを追加する。

### フェーズ1完了条件

- [ ] 現行設定が型付きオブジェクトとして読み込める。
- [ ] 実行前にすべての設定不正を検出できる。
- [ ] YAMLに解析DSLを追加していない。

## フェーズ2: 共通データモデル

### 2.1 `NormalizedItem`

- [ ] `id: str | None` を定義する。
- [ ] `source_id: str` を定義する。
- [ ] `title: str` を定義する。
- [ ] `url: str | None` を定義する。
- [ ] `published_at: datetime | None` を定義する。
- [ ] `summary: str` と `content: str` を定義する。
- [ ] `categories: list[str]` を定義する。
- [ ] `external_ids: list[str]` を定義する。
- [ ] `raw_metadata: dict` を定義する。
- [ ] list/dictの可変既定値をインスタンス間で共有しない。
- [ ] titleが空の項目を拒否または明示的にスキップできるようにする。
- [ ] timezone付きUTC日時へ統一する補助処理を用意する。
- [ ] CVE専用必須フィールドを追加しない。

### 2.2 評価・集計モデル

- [ ] score、why_matched、matched_topic、article_keyを持つ評価結果を定義する。
- [ ] source別のfetched/candidate/matched/duplicate/notified集計を定義する。
- [ ] fetch状態とエラー概要を集計へ持たせる。
- [ ] Slack送信結果を記事単位またはダイジェスト単位で表現する。
- [ ] 同じ入力からwhy_matchedの順序を安定させられるデータ構造を選ぶ。

### 2.3 モデルテスト

- [ ] 空の任意フィールドが正規化されるテストを追加する。
- [ ] 可変既定値が共有されないテストを追加する。
- [ ] naive datetimeのUTC化規則をテストする。
- [ ] timezone付き日時がUTCへ変換されるテストを追加する。

### フェーズ2完了条件

- [ ] 全取得経路が同じ `NormalizedItem` を返せる。
- [ ] 下流処理がsource固有レスポンスに依存しない。

## フェーズ3: 制限付きHTTPクライアント

### 3.1 HTTP境界

- [ ] 取得処理をテスト時に差し替え可能な小さな境界にする。
- [ ] TLS証明書検証を常に有効にする。
- [ ] HTTP timeoutを10秒にする。
- [ ] 最大レスポンスサイズを5 MiBにする。
- [ ] Content-Lengthが上限超過なら本文読込前に失敗させる。
- [ ] Content-Lengthがない場合もstream読込中に上限を検査する。
- [ ] リダイレクトを最大3回に制限する。
- [ ] HTTPS以外へのリダイレクトを拒否する。
- [ ] HTTP 2xxだけを成功にする。
- [ ] `SignalSift/<version>` User-Agentを設定する。
- [ ] 記事本文中のリンクを取得しない構造にする。
- [ ] 応答本文をログへ丸ごと出さない。

### 3.2 任意の限定リトライ

- [ ] リトライを実装するか、単回取得にするかを決定する。
- [ ] 実装する場合は一時的障害だけを対象に最大2回とする。
- [ ] 実装する場合は短い指数バックオフを用いる。
- [ ] 設定不正、恒久的4xx、サイズ超過、解析エラーを無条件再試行しない。

### 3.3 HTTPテスト

- [ ] 2xx成功のテストを追加する。
- [ ] 4xx/5xx失敗のテストを追加する。
- [ ] timeoutのテストを追加する。
- [ ] Content-Length超過のテストを追加する。
- [ ] stream途中のサイズ超過テストを追加する。
- [ ] リダイレクト上限のテストを追加する。
- [ ] HTTPへのリダイレクト拒否テストを追加する。
- [ ] TLS検証を無効化するコードがないことをレビューする。

### フェーズ3完了条件

- [ ] 外部取得にtimeout、サイズ、redirectの上限がある。
- [ ] HTTPクライアントのテストがネットワークなしで成功する。

## フェーズ4: 汎用RSS / Atom / RDF Fetcher

### 4.1 安全なFeed解析

- [ ] RSS 2.0を解析する。
- [ ] Atomを解析する。
- [ ] RSS 1.0/RDFを解析する。
- [ ] XML外部実体とDTDを処理しないパーサーを使用する。
- [ ] Feed全体が解析不能な場合をsource失敗にする。
- [ ] 壊れた1entryだけを警告してスキップする。
- [ ] Feed contentをコードやテンプレートとして実行しない。

### 4.2 共通フィールドへの写像

- [ ] GUID/Atom IDを `id` へ写像する。
- [ ] alternate link/linkを `url` へ写像する。
- [ ] titleを必須として取り出す。
- [ ] published/updated/pubDate/dc:dateを仕様順で選ぶ。
- [ ] Feed日時をtimezone付きUTCへ変換する。
- [ ] 日時にtimezoneがない場合はUTCとして警告またはdebugログを残す。
- [ ] summary/descriptionを `summary` へ写像する。
- [ ] Atom content/content:encodedを `content` へ写像する。
- [ ] category/tag/subjectを `categories` へ写像する。
- [ ] CVE/GHSA等を抽出する場合は `external_ids` へ格納する。
- [ ] `source_id` を設定から付与する。

### 4.3 Feedテキストの安全化

- [ ] HTML entityをテキストへ戻す。
- [ ] HTMLタグを除去する。
- [ ] script/styleの内容を除去する。
- [ ] 制御文字を除去する。
- [ ] summary/contentがない場合は空文字にする。
- [ ] titleが空のentryをスキップする。
- [ ] `raw_metadata` にレスポンス全体を保存しない。

### 4.4 Feedフィクスチャとテスト

- [ ] RSS 2.0フィクスチャを作成する。
- [ ] Atomフィクスチャを作成する。
- [ ] JPCERT向けRDFフィクスチャを作成する。
- [ ] HTMLを含むsummary/contentフィクスチャを作成する。
- [ ] 日時なし、timezoneなし、壊れたentryのフィクスチャを作成する。
- [ ] 外部実体を含む危険なXMLの拒否テストを追加する。
- [ ] AC-11: 2種類以上の通常Feedが同じFetcherを通ることを確認する。
- [ ] 通常Feedごとの専用クラスを作成していないことをレビューする。

### フェーズ4完了条件

- [ ] 有効な通常RSS情報源を汎用Fetcherだけで処理できる。
- [ ] 安全でないXMLと壊れたFeedの障害境界がテストされている。

## フェーズ5: CISA KEVアダプター

### 5.1 Adapter境界

- [ ] `ADAPTERS = {"cisa_kev": fetch_cisa_kev}` の静的レジストリーを作る。
- [ ] 動的importやplugin discoveryを実装しない。
- [ ] `type: json` とadapter名からCISA KEV処理へdispatchする。
- [ ] 未知adapterを実行時まで見逃さない。

### 5.2 KEV正規化

- [ ] JSONトップレベルと `vulnerabilities[]` の型を検証する。
- [ ] `cveID` を `id` と `external_ids` へ写像する。
- [ ] `vulnerabilityName` をtitleへ写像する。
- [ ] `dateAdded` を00:00:00 UTCのpublished_atへ変換する。
- [ ] `shortDescription` をsummaryへ写像する。
- [ ] `requiredAction` をcontentへ含める。
- [ ] vendorProject/productをcontentとraw_metadataへ含める。
- [ ] ransomware use、dueDate、notesを必要最小限のraw_metadataへ写像する。
- [ ] 安定したHTTPS URLを生成する。
- [ ] 必須KEVフィールド欠落時のentryスキップまたはsource失敗境界を定める。

### 5.3 強制採用に必要なメタデータ

- [ ] `force_notify_new_entries` を評価できる情報を保持する。
- [ ] `dateAdded >= initial_cutoff_at` を判定できるようにする。
- [ ] 閾値をバイパスしても重複、初回基準日時、Slack成功順序をバイパスしない。
- [ ] `force-notify:cisa_kev` をwhy_matchedへ追加できるようにする。

### 5.4 KEVテスト

- [ ] 正常なKEV JSONフィクスチャを作成する。
- [ ] 不正なトップレベルJSONの失敗テストを追加する。
- [ ] 必須フィールド欠落entryのテストを追加する。
- [ ] dateAdded境界のテストを追加する。
- [ ] AC-15: 新規KEVが強制採用されることを確認する。
- [ ] 古いKEVが強制採用されないことを確認する。

### フェーズ5完了条件

- [ ] CISA KEVが `NormalizedItem` のみを下流へ返す。
- [ ] CISA以外の未使用adapterを追加していない。

## フェーズ6: 情報源固有の事前フィルター

### 6.1 照合用テキスト

- [ ] title、summary、content、categories、external_idsを仕様順に連結する。
- [ ] Unicode NFKC正規化を行う。
- [ ] 英字をcase-insensitiveにする。
- [ ] 連続空白を1文字へ圧縮する。
- [ ] 日本語と記号を含む語を部分文字列一致にする。
- [ ] 英数字語句に単語境界を適用する。
- [ ] `event` が `prevent` に一致しないテストを追加する。
- [ ] `CVE-` のprefix一致を実装する。
- [ ] 表示用原文を照合正規化で上書きしない。

### 6.2 source filter評価

- [ ] `exclude` のいずれかに一致した記事を即時除外する。
- [ ] `include_any` がある場合、1語以上一致した記事だけを通す。
- [ ] excludeをinclude_anyより先に評価する。
- [ ] excludeとincludeの両方に一致した記事を除外する。
- [ ] 除外理由をsource集計またはdebugログへ残す。
- [ ] Security Profileのグローバル語をsource設定へ複製しない。

### 6.3 source filterテスト

- [ ] Wizのwebinar/customer story/event除外をテストする。
- [ ] StepSecurityのinclude_any通過・不通過をテストする。
- [ ] Aikidoのcompany update/funding除外をテストする。
- [ ] exclude優先順位をテストする。
- [ ] source_filter未指定時に全記事を通すことをテストする。

### フェーズ6完了条件

- [ ] source固有ノイズとグローバル関連性の責務が分離されている。
- [ ] 有効sourceの現在のsource_filterを設定どおり評価できる。

## フェーズ7: 決定論的フィルターとスコアリング

### 7.1 ルール評価器

- [ ] `any` を1語以上一致として評価する。
- [ ] `all_groups` を各group内OR、group間ANDとして評価する。
- [ ] 同じ語の複数出現で得点を重複加算しない。
- [ ] 1ruleにつきscoreを1回加算する。
- [ ] 複数rule成立時はそれぞれ加算する。
- [ ] 成立ruleと代表一致語を安定順で返す。

### 7.2 負の語

- [ ] `product announcement` と `release notes` だけの一致を−3にする。
- [ ] その他のnegative term一致を−5にする。
- [ ] 複数negative term一致でも1回だけ減点する。
- [ ] −3対象と−5対象の同時一致では−5だけを適用する。
- [ ] `negative:<term>:<penalty>` をwhy_matchedへ含める。
- [ ] 強い正シグナルがある場合は減点後も採用され得ることをテストする。

### 7.3 主題ルール

- [ ] supply_chainのanyルールを評価する。
- [ ] vulnerabilityの脆弱性文脈AND悪用・影響文脈を評価する。
- [ ] ai_securityのAI文脈ANDsecurity文脈を評価する。
- [ ] 通常記事は主題ルールが1つ以上必要とする。
- [ ] 普通のCVEだけでは主題ルール不成立とする。
- [ ] 一般的なAI記事だけでは主題ルール不成立とする。

### 7.4 加点

- [ ] source priorityを設定写像で1回加算する。
- [ ] active_exploitation boostを1回加算する。
- [ ] severe_impact boostを1回加算する。
- [ ] actionable boostを1回加算する。
- [ ] 各boostの複数語一致で重複加算しない。
- [ ] watch termが1語以上一致したら記事ごとに1回だけ加算する。
- [ ] 一致した具体的なwatch termをwhy_matchedへ含める。
- [ ] source priorityとboostだけでは通常記事を採用しない。

### 7.5 採否と説明

- [ ] 合計scoreを仕様の式どおり計算する。
- [ ] `score >= threshold` を境界値込みで採用する。
- [ ] 主題ルール未成立を不採用にする。
- [ ] CISA KEV強制採用だけが主題ルールと閾値をバイパスできるようにする。
- [ ] matched_topicを決定する。
- [ ] why_matchedを「主題、代表語、boost、負の語、watch、priority、強制理由」の順にする。
- [ ] why_matchedから重複を除き、順序を安定させる。

### 7.6 フィルターテスト

- [ ] AC-01: 悪性npmパッケージを採用する。
- [ ] AC-02: supply chainウェビナーを減点後に不採用とする。
- [ ] AC-03: CVE + exploited in the wildを採用する。
- [ ] AC-04: 通常CVEを不採用とする。
- [ ] AC-05: MCP/AI agent + security issueを採用する。
- [ ] AC-06: 一般AI発表を不採用とする。
- [ ] 日本語の主要キーワードをテストする。
- [ ] thresholdちょうどの採用境界をテストする。
- [ ] why_matchedとscoreを手計算で再現できるテストを追加する。
- [ ] 同じ入力を複数回評価して結果が同じことを確認する。

### フェーズ7完了条件

- [ ] Security Profileの採否が設定駆動である。
- [ ] 全採用記事のscoreと理由を説明できる。
- [ ] 必須の信号品質テストAC-01～AC-06が成功する。

## フェーズ8: 記事キーと重複排除

### 8.1 URL正規化

- [ ] schemeとhostを小文字化する。
- [ ] IDN hostを一貫したASCII表現へ変換する。
- [ ] 既定portを除去する。
- [ ] fragmentを除去する。
- [ ] `utm_*` を除去する。
- [ ] `fbclid` と `gclid` を除去する。
- [ ] 残るquery parameterをキー・値で安定ソートする。
- [ ] root以外の末尾slash差を除去する。
- [ ] HTTPとHTTPSのscheme自体は同一視しない。

### 8.2 タイトル正規化

- [ ] NFKC正規化を行う。
- [ ] 大文字小文字を統一する。
- [ ] 前後空白を除去する。
- [ ] 連続空白を圧縮する。

### 8.3 `article_key`

- [ ] 安定Feed IDを最優先する。
- [ ] 不安定なFeed IDをURLへフォールバックできる境界を用意する。
- [ ] IDがなければcanonical URLを使う。
- [ ] URLもなければsource ID + normalized titleを使う。
- [ ] 入力に `guid:`、`url:`、`title:` namespaceを付ける。
- [ ] SHA-256の小文字16進文字列を保存キーにする。
- [ ] CVE IDだけを記事キーにしない。

### 8.4 重複判定

- [ ] 保存状態のarticle_keyと照合する。
- [ ] 同一実行内のarticle_key集合と照合する。
- [ ] 設定順で先に処理した記事を残す。
- [ ] 後続重複をduplicate_countへ加算する。

### 8.5 重複排除テスト

- [ ] GUID優先のテストを追加する。
- [ ] URLフォールバックのテストを追加する。
- [ ] titleフォールバックのテストを追加する。
- [ ] AC-16: UTMとfragment違いのURLが同じキーになることを確認する。
- [ ] query順序違いが同じキーになることを確認する。
- [ ] root pathと末尾slashの境界をテストする。
- [ ] 同じCVEの異なる記事が別キーになることを確認する。
- [ ] 実行内重複が1件だけ残ることを確認する。

### フェーズ8完了条件

- [ ] 仕様の3段階フォールバックで安定キーを生成できる。
- [ ] URL追跡情報の差で再通知しない。

## フェーズ9: 初回基準日時と永続状態

### 9.1 状態モデルと読込

- [ ] version 1の状態モデルを定義する。
- [ ] `initial_cutoff_at` をtimezone付きUTCで保持する。
- [ ] `items` をarticle_keyから通知記録へのmapとして保持する。
- [ ] source、title、url、published_at、notified_atを記録する。
- [ ] 状態ファイル不在を初回実行として扱う。
- [ ] 初回開始時刻−lookbackで `initial_cutoff_at` を生成する。
- [ ] 初回作成後に `initial_cutoff_at` を変更しない。
- [ ] 未対応versionを拒否する。
- [ ] `initial_cutoff_at` 欠落・不正を拒否する。
- [ ] JSON破損時に空状態へフォールバックしない。
- [ ] 状態の未知フィールドは読み飛ばせるようにする。
- [ ] 必須構造の型不正を拒否する。

### 9.2 初回バックフィル防止

- [ ] `published_at >= initial_cutoff_at` の記事だけを候補にする。
- [ ] 境界日時ちょうどの記事を含める。
- [ ] CISA KEVはdateAddedを使う。
- [ ] published_at不明の記事を除外する。
- [ ] 現在より24時間超未来の記事を不正としてスキップする。
- [ ] 2回目以降も保存済みcutoffを適用する。

### 9.3 状態更新とprune

- [ ] Slack成功記事だけを状態へ追加するAPIを作る。
- [ ] Slack失敗記事を追加しない。
- [ ] notified_atを実際の送信成功時刻にする。
- [ ] retention日数より古い記録を削除する。
- [ ] retention境界ちょうどの記録を保持する。
- [ ] 不正なnotified_atを警告して保持する。
- [ ] pruneだけの変更も保存対象にする。

### 9.4 原子的なローカル保存

- [ ] UTF-8 JSONとして保存する。
- [ ] 出力順序とindentを固定し、不要な差分を防ぐ。
- [ ] 同一ディレクトリの一時ファイルへ完全に書く。
- [ ] flush後に原子的renameで置き換える。
- [ ] 途中書き込みで既存状態を破損させない。
- [ ] 内容に変更がない場合はファイルを書き換えない、またはGit差分を発生させない。

### 9.5 状態テスト

- [ ] 初回状態生成テストを追加する。
- [ ] 正常状態読込テストを追加する。
- [ ] AC-17: 破損JSONで安全に失敗することを確認する。
- [ ] 未対応versionの失敗テストを追加する。
- [ ] AC-09: 初回の古い記事を除外する。
- [ ] AC-10: 日時不明記事を除外する。
- [ ] AC-18: 180日より古い状態をpruneする。
- [ ] AC-19: 初回に除外した古い記事を2回目も除外する。
- [ ] 原子的保存失敗時に既存ファイルが残ることをテストする。

### フェーズ9完了条件

- [ ] 初回と2回目以降のバックフィルを防止できる。
- [ ] 180日保持と安全な状態読込・保存がテストされている。

## フェーズ10: Slack通知

### 10.1 表示用テキスト

- [ ] Slack用の `&`、`<`、`>` escapeを実装する。
- [ ] 意図しない `@channel`、`@here` 等のメンションを抑止する。
- [ ] titleとsummaryの元言語を維持する。
- [ ] HTMLや制御文字をSlack本文へ流さない。
- [ ] summaryを優先し、空ならcontentを使う。
- [ ] 要約を最大300文字へ切り詰め、省略記号を付ける。

### 10.2 個別通知フォーマット

- [ ] 絵文字、分類、titleを先頭へ置く。
- [ ] source名を表示する。
- [ ] why_matchedを安定順で `/` 区切り表示する。
- [ ] published_atをUTC表示する。
- [ ] 日時不明時の `Unknown` 表示を実装する。
- [ ] URLがある場合だけURL行を表示する。
- [ ] 複数topic時の主分類優先順を実装する。

### 10.3 ダイジェスト

- [ ] 未通知採用数が個別通知上限を超えたらダイジェストへ切り替える。
- [ ] score降順に並べる。
- [ ] 同scoreではpublished_at降順に並べる。
- [ ] さらに同順位ならarticle_key昇順にする。
- [ ] 各記事に分類、title、source、主要why、URLを含める。
- [ ] Slackペイロード上限を超える場合だけ複数ダイジェストへ分割する。
- [ ] 分割境界を決定論的にする。

### 10.4 Webhook送信

- [ ] `SLACK_WEBHOOK_URL` を環境変数から受け取る。
- [ ] HTTPS WebhookへPOSTする。
- [ ] HTTP 2xxだけを成功にする。
- [ ] timeoutと非2xxを失敗として返す。
- [ ] Webhook URLを例外・ログへ含めない。
- [ ] 個別通知失敗後も他記事を送信する。
- [ ] ダイジェスト単位の成功記事集合を返す。
- [ ] 失敗記事を成功集合へ含めない。

### 10.5 Slackテスト

- [ ] 個別メッセージのsnapshotまたは完全一致テストを追加する。
- [ ] escapeとメンション抑止をテストする。
- [ ] 300文字境界をテストする。
- [ ] URLなしの記事をテストする。
- [ ] 非2xx、timeoutのテストを追加する。
- [ ] AC-14: 6件以上でダイジェストになることを確認する。
- [ ] ダイジェスト分割時の部分成功をテストする。
- [ ] Webhook URLがログへ出ないことをテストする。

### フェーズ10完了条件

- [ ] 個別・ダイジェストを安全なプレーンテキストで送信できる。
- [ ] Slack失敗を記事・ダイジェスト単位で追跡できる。

## フェーズ11: run-once CLIとパイプライン統合

### 11.1 CLI引数と起動前検証

- [ ] `signalsift run` subcommandを実装する。
- [ ] 既定の2設定パスを使用する。
- [ ] 必須設定を全件検証してから外部取得を始める。
- [ ] `SLACK_WEBHOOK_URL` 欠落を終了コード2にする。
- [ ] 状態読込エラーを安全に報告する。
- [ ] 秘密値をCLI表示へ出さない。

### 11.2 パイプライン順序

- [ ] 設定を読み込む。
- [ ] Slack Secretを確認する。
- [ ] 状態を読み込み、期限切れ記録をpruneする。
- [ ] 有効sourceだけを設定順に処理する。
- [ ] sourceを取得・正規化する。
- [ ] source filterを適用する。
- [ ] initial_cutoff_atを適用する。
- [ ] グローバルfilterとscoreを評価する。
- [ ] article_keyを生成する。
- [ ] 保存済み・実行内重複を除外する。
- [ ] 採用記事を通知順へ安定ソートする。
- [ ] 個別またはダイジェストでSlack送信する。
- [ ] Slack成功記事だけを状態へ追加する。
- [ ] 状態変更時だけ原子的に保存する。
- [ ] 実行集計を出力する。

### 11.3 障害分離と終了コード

- [ ] 1sourceのHTTP失敗後も次sourceを処理する。
- [ ] 1sourceの解析失敗後も次sourceを処理する。
- [ ] 信頼できない部分データを通知しない。
- [ ] 1件のSlack失敗後も残りを送る。
- [ ] 部分成功した通知の状態を保存する。
- [ ] 全成功時に終了コード0を返す。
- [ ] source/Slack/stateの部分障害時に終了コード1を返す。
- [ ] 設定・Secret欠落時に終了コード2を返す。
- [ ] 状態保存失敗を終了コード1にする。

### 11.4 ログと集計

- [ ] source_idを全sourceログへ含める。
- [ ] fetch_statusを出力する。
- [ ] fetched_countを出力する。
- [ ] candidate_countを出力する。
- [ ] matched_countを出力する。
- [ ] duplicate_countを出力する。
- [ ] notified_countを出力する。
- [ ] sourceエラーに段階、例外種別、短い説明を含める。
- [ ] 実行全体の追加・prune件数、所要時間、終了状態を出力する。
- [ ] 記事本文全文とHTTPレスポンス全文をログへ出さない。

### 11.5 統合テスト

- [ ] AC-07: 同じ記事を2回処理して1回だけ通知する。
- [ ] AC-08: Slack失敗時に状態を更新せず終了コード1にする。
- [ ] AC-12: 1source失敗後も他sourceを通知する。
- [ ] AC-13: Slack成功後だけversion 1状態へ追加する。
- [ ] source部分失敗かつSlack成功時に成功分状態が残ることを確認する。
- [ ] 全成功時の終了コード0を確認する。
- [ ] 設定不正時に外部通信せず終了コード2となることを確認する。
- [ ] 同じ固定入力・時計で結果と並び順が同じことを確認する。

### フェーズ11完了条件

- [ ] `signalsift run` が1回の完全な処理を実行して終了する。
- [ ] at-least-onceの順序が統合テストで証明される。
- [ ] source障害とSlack障害が他の処理から分離されている。

## フェーズ12: GitHub Actionsとstateブランチ

### 12.1 ワークフロー基本設定

- [ ] `.github/workflows/signalsift.yml` を作成する。
- [ ] `schedule` triggerを追加する。
- [ ] cronを `17,47 * * * *` にする。
- [ ] `workflow_dispatch` を追加する。
- [ ] Python 3.12以上をセットアップする。
- [ ] job timeoutを10分にする。
- [ ] `permissions: contents: write` を明示し、不要な権限を付けない。
- [ ] concurrency groupを `signalsift-state` にする。
- [ ] `cancel-in-progress: false` にする。
- [ ] `SLACK_WEBHOOK_URL` をActions SecretからCLIへ渡す。

### 12.2 安全なcheckoutと依存準備

- [ ] Actionsをcommit SHAで固定する。
- [ ] main側checkoutで不要な認証情報を永続化しない。
- [ ] ロック済み依存関係から再現可能にインストールする。
- [ ] testを実行してから本処理を起動するか、別CIとの責務を明示する。

### 12.3 stateブランチ処理

- [ ] `state` ブランチから `state/notified.json` を取得する。
- [ ] stateブランチ不在を初回実行として扱う。
- [ ] stateブランチには状態ファイルだけを置く。
- [ ] CLIが終了コード1でも成功通知分の状態保存stepを実行する。
- [ ] 状態差分の有無を確認する。
- [ ] 差分がある場合だけcommitする。
- [ ] 差分がある場合だけstateブランチへpushする。
- [ ] mainへ実行時状態をcommitしない。
- [ ] push失敗時にworkflowを失敗させる。
- [ ] CLIの終了状態を保存処理後にworkflow結果へ反映する。
- [ ] Actions Cacheを通知履歴の正本にしない。

### 12.4 ワークフロー検証

- [ ] YAML構文をローカルで検証する。
- [ ] permissionsが過剰でないことをレビューする。
- [ ] concurrency設定がworkflow/jobの適切な位置にあることを確認する。
- [ ] Secretがログやコマンド展開へ露出しないことを確認する。
- [ ] state差分なしで空commitしないことを確認する。
- [ ] state初回作成フローを確認する。
- [ ] CLI部分失敗時にも成功分を保存する制御フローを確認する。

### フェーズ12完了条件

- [ ] 定期実行と手動実行の両方を起動できる。
- [ ] runnerをまたいで通知状態を保持できる。
- [ ] 同時実行でstate更新が競合しない。

## フェーズ13: テストフィクスチャと受入試験の完成

### 13.1 フィクスチャ監査

- [ ] RSS、Atom、RDFの全フィクスチャがローカルにある。
- [ ] CISA KEV JSONフィクスチャがある。
- [ ] 正常・破損状態JSONフィクスチャがある。
- [ ] Slack 2xx、非2xx、timeoutを模擬できる。
- [ ] 日本語と英語の両方の信号記事がある。
- [ ] marketing、通常CVE、一般AI記事のnegative fixtureがある。
- [ ] すべて架空または安全な公開情報形式で、秘密値を含まない。

### 13.2 受入条件トレーサビリティ

- [ ] AC-01のテスト名と対象コードを記録する。
- [ ] AC-02のテスト名と対象コードを記録する。
- [ ] AC-03のテスト名と対象コードを記録する。
- [ ] AC-04のテスト名と対象コードを記録する。
- [ ] AC-05のテスト名と対象コードを記録する。
- [ ] AC-06のテスト名と対象コードを記録する。
- [ ] AC-07のテスト名と対象コードを記録する。
- [ ] AC-08のテスト名と対象コードを記録する。
- [ ] AC-09のテスト名と対象コードを記録する。
- [ ] AC-10のテスト名と対象コードを記録する。
- [ ] AC-11のテスト名と対象コードを記録する。
- [ ] AC-12のテスト名と対象コードを記録する。
- [ ] AC-13のテスト名と対象コードを記録する。
- [ ] AC-14のテスト名と対象コードを記録する。
- [ ] AC-15のテスト名と対象コードを記録する。
- [ ] AC-16のテスト名と対象コードを記録する。
- [ ] AC-17のテスト名と対象コードを記録する。
- [ ] AC-18のテスト名と対象コードを記録する。
- [ ] AC-19のテスト名と対象コードを記録する。

### 13.3 全体テスト

- [ ] 固定時計を用いて全テストを実行する。
- [ ] 外部ネットワークを無効化して全テストが成功することを確認する。
- [ ] テスト実行順を変えても成功することを確認する。
- [ ] 一時ファイルと状態がテスト間で共有されないことを確認する。
- [ ] CLI、filter、dedupe、state、Slackの主要分岐を確認する。
- [ ] 10分未満でテストと通常runが完了できる構成であることを確認する。

### フェーズ13完了条件

- [ ] AC-01～AC-19がすべて自動テストに対応している。
- [ ] 全テストがライブインターネットなしで成功する。
- [ ] 不安定な現在時刻・実行順依存がない。

## フェーズ14: ドキュメント、セキュリティ、最終受入

### 14.1 README運用手順

- [ ] Python要件とインストール手順をREADMEへ追加する。
- [ ] `signalsift run` の実行方法を追加する。
- [ ] `SLACK_WEBHOOK_URL` の設定方法を追加する。
- [ ] GitHub Actions Secretの登録方法を追加する。
- [ ] `state` ブランチの初回動作を説明する。
- [ ] sources/filtersの安全な変更方法を説明する。
- [ ] ローカルテスト手順を追加する。
- [ ] 部分障害時の終了コードと再実行挙動を説明する。

### 14.2 セキュリティレビュー

- [ ] 全外部取得でHTTPSとTLS検証を確認する。
- [ ] timeout、サイズ、redirect制限が全取得経路に適用されることを確認する。
- [ ] XML外部実体とDTDが処理されないことを確認する。
- [ ] arbitrary article linkを自動取得しないことを確認する。
- [ ] Slack文字列escapeとメンション抑止を確認する。
- [ ] Webhook URLがコード、fixture、状態、ログにないことを検索する。
- [ ] Actions権限をレビューする。
- [ ] 依存関係が固定・ロックされていることを確認する。
- [ ] Feed本文がコードとして実行される経路がないことを確認する。

### 14.3 アーキテクチャレビュー

- [ ] CoreモデルにCVE必須前提がないことを確認する。
- [ ] Security Profileの語が主に設定へ留まっていることを確認する。
- [ ] CISA固有処理がadapterへ閉じていることを確認する。
- [ ] 通常RSS sourceごとの専用classがないことを確認する。
- [ ] notifier plugin frameworkを作っていないことを確認する。
- [ ] profiles階層・動的loaderを作っていないことを確認する。
- [ ] 外部DB、queue、scheduler、browser automationを追加していないことを確認する。
- [ ] モジュールを具体的な複雑性なく細分化していないことを確認する。

### 14.4 最終実行確認

- [ ] cleanなPython 3.12環境で依存関係をインストールする。
- [ ] formatter/linter/type checkerを採用した場合は全件成功させる。
- [ ] 全自動テストを成功させる。
- [ ] fixture HTTPとfixture Slackを使ったrun-once統合実行を成功させる。
- [ ] 全成功時の終了コード0を確認する。
- [ ] 部分障害時の終了コード1と成功分状態保存を確認する。
- [ ] 構成エラー時の終了コード2を確認する。
- [ ] 状態差分なしの実行が不要なGit差分を作らないことを確認する。
- [ ] ログにsource別集計と全体集計があることを確認する。
- [ ] 仕様書の受入完了条件を1項目ずつ照合する。

### フェーズ14完了条件

- [ ] MVPの全受入条件を満たす。
- [ ] README、仕様書、実装、設定、テストに矛盾がない。
- [ ] GitHub Actionsへ配置可能な状態である。

## 最終Definition of Done

- [ ] `signalsift run` が明示されたパイプライン順で1サイクル実行する。
- [ ] 有効な7情報源を汎用Feed経路またはCISA KEV adapterで処理する。
- [ ] relevant supply-chain、悪用脆弱性、AI/MCP securityだけを低ノイズで採用する。
- [ ] 全採用記事に決定論的なscoreとwhy_matchedがある。
- [ ] Slack成功前には通知済み状態を更新しない。
- [ ] 同一記事を正常時に再通知しない。
- [ ] 初回および2回目以降に過去Feedをバックフィルしない。
- [ ] sourceまたはSlackの部分障害後も成功分を処理・保存する。
- [ ] `state` ブランチで180日分の通知履歴を維持する。
- [ ] GitHub Actionsが30分ごとおよび手動で起動できる。
- [ ] 全テストがローカルfixtureだけで成功する。
- [ ] 秘密情報がリポジトリ、状態、ログに残らない。
- [ ] 外部DB、常駐server、内部scheduler、必須LLM、plugin frameworkを含まない。
