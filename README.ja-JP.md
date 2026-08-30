<p align="center">
  <img src="backend/app/static/assets/logo.svg" alt="VerdictAI Logo" width="110" />
</p>

<h1 align="center">⚖️ VerdictAI · インテリジェント法廷合議</h1>

<p align="center">
  <em>マルチエージェント司法ディベート＆判決システム</em>
</p>

<p align="center">
  <a href="https://github.com/Morningstar202604/VerdictAI/stargazers"><img src="https://img.shields.io/github/stars/Morningstar202604/VerdictAI?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/network/members"><img src="https://img.shields.io/github/forks/Morningstar202604/VerdictAI?style=social" alt="GitHub Forks" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/issues"><img src="https://img.shields.io/github/issues/Morningstar202604/VerdictAI" alt="GitHub Issues" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-FF6B35" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/WebSocket-Real--time-7C3AED" alt="WebSocket" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License" />
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">中文</a> · <strong>日本語</strong>
</p>

---

> **7人のAI専門家が法廷に入ります。** 実際の事件記録を検討し、複数ラウンドにわたって反対尋問を行い、法条を引用し、ツールを呼び出し、相互に矛盾を指摘し合い——最後に裁判長が判決を下します。全工程がブラウザにリアルタイム配信されます。

**ご自身の文書をどうぞ。** PDF形式の捜査報告書や起訴状をアップロードすると——VerdictAIが内容を読み取り、人物・証拠・タイムライン・適用法条を抽出し、各専門家に個別の資料を配布し、完全な対抗式審議を実行して、判決書と司法担当者向けの実行可能なフォローアップリストを生成します。

## ✨ VerdictAI の違い

| | 従来の AI Q&A | **VerdictAI** |
|---|-## 📸 スクリーンショット

| | |
|---|---|
| ![事件受付とブランディング](docs/screenshots/landing.png) | ![リアルタイム法廷と人間の介入](docs/screenshots/trial-debate.png) |
| *事件受付 — PDFアップロード、専門家阵容、AI抽出* | *リアルタイム法廷 — 7専門家、人間の介入、使用統計* |
| ![判決と判決後ワークフロー](docs/screenshots/verdict-workflow.png) | ![ダークモード](docs/screenshots/dark-mode.png) |
| *判決書、質疑、実行可能なフォローアップリスト* | *ダークテーマ、完全な記録* |

--|---|
| 方式 | 単一モデル、単一回答 | **7人の専門エージェント**による多ラウンド討論 |
| 産出 | 一回限りのテキスト | **多ラウンド審議** + 矛盾検出 |
| 透明性 | ブラックボックス | **完全なイベントストリーム** — トークン・ツール呼び出し・エージェント状態の全て |
| 引用 | 幻覚・捏造 | **実際の法条と類案要旨** — ナレッジベース検索で一致したもののみ引用、一致しなければ決して捏造しない |
| 文書 | 非構造化データは処理不可 | **AI文書理解** — プレーンなPDFから人物・証拠・タイムライン・法条を自動抽出 |
| 判決 | "AIが言った" | **構造化判決** + 証拠チェーン + 疑問点 + 実行可能なフォローアップリスト |

## 🎯 機能

<details>
<summary><strong>🧠 7人の専門AI専門家（同ラウンド並行実行）</strong></summary>

| 専門家 | 職責 | 立場 |
|------|------|------|
| 🔍 現場検証専門家 | 空間論理、出入動線、痕跡分布 | 中立 |
| 🔬 法医学専門家 | 死因、死亡時間帯、傷害状況 | 科学優先 |
| 🧪 物証・痕跡専門家 | DNA、指紋、保管チェーン、監視カメラ | 物証主義 |
| 🧠 取調・心理専門家 | 供述の信憑性、動機、プロファイリング | 中立 |
| ⚖️ 証拠法専門家 | 証拠資格、排除、証明基準 | 手続的正義 |
| 👨‍⚖️ 検察官エージェント | 起訴論理チェーン、立証の欠落 | 側検察 |
| 🛡️ 弁護エージェント | 合理的疑い、代替説明 | 側弁護 |

</details>

<details>
<summary><strong>📄 実文書理解</strong></summary>

叙述形式のPDF報告書をアップロードすると、AI前処理が自動的に：

1. 全文抽出（PyMuPDF、50ページ／6万文字の安全上限付き）
2. **プレーンテキストから構造を抽出**——人物（役割付き）、証拠、タイムライン、適用法条、資金・保険の手掛かり
3. 各専門家への個別資料を生成し、事件記録チャートを描画
4. 中国語時間表現の正規化（「午前1時30分から2時30分」→ 標準死亡時間帯）、相互検証に供する

抽出された構造は事件パネルに **「✨ AI自動抽出」** バッジ付きで表示され、全て編集可能です。

</details>

<details>
<summary><strong>🛠️ ツール拡張推論</strong></summary>

専門家は話すだけでなく——**ツールを呼び出します**（結果は記録に直接描画）：

- `read_evidence` — 証拠番号で詳細を読み取る
- `timeline_check` — 事件タイムラインと時系列を照合
- `list_contradictions` — マーク済みの矛盾を確認
- `search_case_law` — 3層法条検索：事件記録 → カスタムナレッジベース → 内蔵法条ライブラリ
- `web_search` — 公開情報のライブ検索（Bing中国ソース、切替可能）
- `run_code` — サンドボックスPython（matplotlibチャートを記録に直接描画）

</details>

<details>
<summary><strong>📚 ナレッジベースと類案</strong></summary>

- **内蔵法条ライブラリ**：刑事訴訟法・刑法・民法典の番号が安定した実際の条文 + 証拠審査要旨（三性、保管チェーン、電子データ）
- **類案要旨**：間接証拠による認定、監視カメラ編集の影響、不可抗力弁護などの裁判ルール
- **カスタム項目**：「設定 → ナレッジベース」で自身の類案要旨や内部規範を追加可能、3層検索は一致した場合のみ引用
- **決して捏造しない**：検索で見つからない場合、専門家は明確にその旨を述べ、法条番号を捏造しません

</details>

<details>
<summary><strong>🔄 マルチラウンドディベートエンジン</strong></summary>

- ディベートラウンド数は設定可能、**メモリウィンドウ**も設定可能
- ウィンドウを超えた過去ラウンドは**ローリング圧縮で要約**され、単純に破棄されません
- AI批評官が毎ラウンド矛盾をスキャンし、次ラウンドの深化を促します
- 裁判長は合意形成（またはラウンド上限）で収束します

</details>

<details>
<summary><strong>📹 リアルタイムストリーミングと法廷 UX</strong></summary>

- トークン単位の専門家出力 + 発言インジケータ
- ツール呼び出しとサンドボックスチャートを記録に直接描画
- ラウンドステッパー、プログレスバー、専門家ステータス
- **途中介入**——いつでも発言でき、次ラウンドで全専門家が応答
- **判決質疑**——判決後も理由を問い詰める、推奨質問付き

</details>

<details>
<summary><strong>⚖️ デュアル判決モードと判決後ワークフロー</strong></summary>

- **AI裁判長**——自動収束して判決を下す
- **人間裁判官（HITL）**——法廷を一時停止して人間によるレビューを待機；タイムアウト時は下書きを自動採用してアーカイブ（設定可能）
- **判決後**：質疑応答、**フォローアップチェックリスト**の進捗追跡、ワンクリックコピー / Markdown出力 / PDF印刷
- 各法廷は自動アーカイブされ、**使用統計**（推論回数、入出力文字数）と完全なリプレイ付き

</details>

<details>
<summary><strong>🧩 エージェントエンジニアリング（設定 → Agent 工程化）</strong></summary>

Dify/Coze に匹敵するランタイム制御：

- **メモリウィンドウ**——各専門家のコンテキストに注入する過去ラウンド要約数
- **コンテキスト上限**——LLM呼び出しあたりの最大文字数（クラウドモデル保護）
- **並行上限**——同ラウンドの専門家並行数（レート制限対策）
- **呼び出しタイムアウト**——エンジン停止でも法廷が停止しない
- **専門家別モデル上書き**——書記は低コストモデル、裁判長は最強モデル
- **戦略テンプレート**——ワンクリックでパッケージ化された戦略を適用
- **設定インポート/エクスポート**——専門家陣容全体をJSONでバックアップ・移行

</details>

<details>
<summary><strong>🏛️ デプロイ準備完了</strong></summary>

- ワンコマンド起動/停止（`tools/start_all.py`）——ウィンドウなしデーモン、クラッシュ時自動再起動
- イントラネットデプロイ用アクセスパスワード（`.env` の `ACCESS_PASSWORD`）
- 内蔵ローカルエンジンで完全オフライン動作、OpenAI互換APIにも対応
- ライト/ダーク両テーマ、English / 中文 / 日本語 UI

</details>

## 🚀 クイックスタート（30秒）

```bash
# クローン
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend

# 環境構築
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/Mac

pip install -r requirements.txt

# ワンコマンド起動：バックエンド + ローカル推論エンジン（ウィンドウなし、自動再起動）
python tools/start_all.py
# 停止：python tools/start_all.py stop
```

**http://localhost:8787 を開く** → PDF事件記録をドラッグ（または案情を貼り付け/サンプル選択）→ AIが構造化記録を解析する様子を確認 → 「開庭審理」をクリック → 7人のAI専門家によるディベートをリアルタイムで視聴。

## 🔌 実際の大モデル接続

```env
# backend/.env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_ROUNDS=3
```

サーバー再起動で反映。DeepSeek、GLM、Qwen、Step、Ollama など任意の OpenAI 互換 API に対応。キーがない場合は内蔵**ローカルエンジン**（`backend/ai_engine/`）で完全オフライン実行可能です。

## 🏗️ アーキテクチャ

```
ブラウザ ──WebSocket──▶ FastAPI ──▶ LangGraph StateGraph
                                     │
                        ┌────────────┼────────────┐
                        ▼            ▼             ▼
                   7人の専門家    批評官        裁判長
                  （並行）     （毎ラウンド）  （判決）
                        │            │             │
                        └────────────┘  N回ループ   ▼ 完了
```

**主要な設計判断：**
- **LangGraph StateGraph**——場当調的なループではなく決定論的ステートマシン
- **asyncio.gather + 並行上限**——専門家は同ラウンドで並行実行、レート制限に配慮
- **ツール耐障害性**——ツール呼び出しの失敗でディベートが崩れることはない
- **階層メモリ**——ウィンドウ内は全文、ウィンドウ外はローリング圧縮
- **引用規律**——法条・類案は検索ヒットから取得、モデルの想像からは決して生成しない

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照。

## 📖 ドキュメント

| ドキュメント | 説明 |
|------|------|
| [アーキテクチャ](docs/ARCHITECTURE.md) | システム設計、ステートマシン、イベントタイプ |
| [API リファレンス](docs/API.md) | RESTエンドポイントとWebSocketプロトコル |
| [デプロイガイド](docs/DEPLOYMENT.md) | Docker、systemd、Nginx、パフォーマンスチューニング |
| [コントリビューション](CONTRIBUTING.md) | 開発環境構築と規約 |

## 🤝 コントリビューション

コントリビューションを歓迎します！開発環境構築、コード規約、PRプロセスの詳細は [CONTRIBUTING.md](CONTRIBUTING.md) をご覧ください。

## ⚠️ 免責事項

本システムは**研究とデモ目的**でのみご利用ください。AIが生成する結論は意思決定支援であり、法的助言や判決を構成するものではありません。最終的な法的責任は常に人間の裁判官と法律専門家にあります。

## 📜 ライセンス

[MIT License](LICENSE) — 自由にご利用ください。

---

<p align="center">
  <strong>VerdictAI が役に立ったら、ぜひ ⭐ をお願いします</strong>
</p>

<p align="center">
  <sub>Built with LangGraph • FastAPI • WebSocket</sub>
</p>
