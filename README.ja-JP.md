<p align="center">
  <img src="backend/data/cases/assets/evidence.png" alt="VerdictAI Logo" width="100" />
</p>

<h1 align="center">⚖️ VerdictAI</h1>

<p align="center">
  <em>マルチエージェント司法ディベート＆判決システム</em>
</p>

<p align="center">
  <a href="https://github.com/Morningstar202604/VerdictAI"><img src="https://img.shields.io/github/stars/Morningstar202604/VerdictAI?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/Morningstar202604/VerdictAI/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">中文</a> · <strong>日本語</strong>
</p>

---

> **7人のAI専門家が法廷に入ります。** 彼らは議論し、疑義を呈し、証拠を引用し、ツールを使用し、矛盾を発見し、判決に到達します。すべてリアルタイムでブラウザにストリーミング。

## VerdictAI の特徴

| 従来の AI Q&A | **VerdictAI** |
|---|---|
| 単一モデル、単一回答 | **7人のエージェント**が議論・挑戦 |
| 1回限りのテキスト | **マルチラウンド審議** + 矛盾検出 |
| ブラックボックス | **完全なイベントストリーム** — トークン、ツール呼び出し、Agent ステータス |
| 静的 | **リアルタイム WebSocket** — ディベートをリアルタイムで視聴 |
| "AI が言った" | **構造化された判決** — 証拠チェーン、未解決問題、提言 |

## 主な機能

- **7人の専門家**: 現場捜査 / 法医学 / 物証 / 心理学 / 証拠法 / 検察 / 弁護
- **マルチラウンド**: 2〜5ラウンドの設定が可能、専門家が互いの主張を审视して修正
- **矛盾検出**: AI批評官が各ラウンドの矛盾を検出し、次のラウンドを深化
- **リアルタイム配信**: WebSocketで各トークン、ツール呼び出し、Agentステータスをストリーミング
- **ツール拡張**: 証拠検索 / タイムライン確認 / 矛盾一覧 / 法令検索 / アノテーション
- **PDF事件処理**: PDFをドロップ → 自動的に事件ダイジェストに構造化
- **デュアル審判**: AI裁判長 / 人間裁判官（HITL）
- **ケースライブラリ**: 複数事件の保存 + 過去ディベートのリプレイ
- **ゼロコンフィグデモ**: MockモードでAPI Keyなしで動作

## クイックスタート（30秒）

```bash
git clone https://github.com/Morningstar202604/VerdictAI.git
cd VerdictAI/backend
python -m venv .venv
source .venv/bin/activate      # Linux/Mac
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

`http://localhost:8787` にアクセス → PDFをアップロード → 「開始辩论」をクリック → 7人のAI専門家がリアルタイムで議論する様子を視聴。

## リアルタイムLLMの接続

```env
# backend/.env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_ROUNDS=3
```

再起動するだけで使用可能。DeepSeek、GLM、Qwen、Step、Ollamaなど、すべてのOpenAI互換APIに対応。

## アーキテクチャ

```
ブラウザ ──WebSocket──▶ FastAPI ──▶ LangGraph StateGraph
                                        │
                           ┌────────────┼────────────┐
                           ▼            ▼             ▼
                      7人の専門家    批評官        裁判長
                     （並列）     （各ラウンド）   （判決）
                           │            │             │
                           └────────────┘  N回ループ  ▼ 完了
```

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照。

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [アーキテクチャ](docs/ARCHITECTURE.md) | システム設計、ステートマシン、イベントタイプ |
| [APIリファレンス](docs/API.md) | RESTエンドポイントとWebSocketプロトコル |
| [デプロイメントガイド](docs/DEPLOYMENT.md) | Docker、systemd、Nginx、パフォーマンスチューニング |
| [コントリビューションガイド](CONTRIBUTING.md) | 開発環境セットアップと規範 |

## コントリビューション

貢献を歓迎します！[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 免責事項

本システムは技術研究・デモ用です。AIが生成した判決は法的助言や裁判の効力を持ちません。最終的な法的責任は人間の裁判官にあります。

## ライセンス

[MIT License](LICENSE) — 自由に使用可能。

---

<p align="center">
  <strong>役に立った場合は ⭐ をお願いします</strong>
</p>

<p align="center">
  <sub>Built with LangGraph • FastAPI • WebSocket</sub>
</p>
