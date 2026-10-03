# ELECT Bot — ドキュメント

ELECT は Discord コミュニティサーバー向けに構築された多機能 Bot です。  
Python 3.13 + discord.py 2.6 + Google Cloud Firestore で動作し、Railway にデプロイされています。

---

## 機能概要

| 機能 | 概要 |
|---|---|
| **ランクシステム** | VC 接続時間・テキスト投稿に応じてランクポイントを付与し、カード画像を生成 |
| **VC 管理** | ノックルーム自動作成・クイックマッチルーム・自動削除・ユーザー制限 |
| **審査システム** | プロフィール審査ワークフロー（フォーラムスレッド連動） |
| **ポイント経済** | 複数種別のポイント付与・交換・集計 |
| **裏募集** | 匿名マッチングリクエスト機能 |
| **通話履歴** | VC 共在セッションのログ記録・永続化 |

---

## ドキュメント構成

```
_docs/                  
├── architecture/
│   └── overview.md              アーキテクチャ設計方針・共通パターン
├── cogs/
│   ├── events.md                イベントリスナー Cog 一覧
│   └── commands.md              スラッシュコマンド一覧
├── services/
│   ├── rank_system.md           ランクシステム詳細
│   ├── voice.md                 VC ドメインサービス群
│   ├── points.md                ポイント経済システム
│   └── judging_recruit.md       審査・裏募集システム
├── firestores/
│   └── overview.md              Firestore データ層・コレクション設計
└── infrastructure/
    └── queue.md                 Firestore キューマネージャー
```

---

## 技術スタック

| レイヤー | 使用技術 |
|---|---|
| 言語 | Python 3.13 |
| Bot フレームワーク | discord.py 2.6.4 |
| データベース | Google Cloud Firestore (AsyncClient) |
| 画像生成 | Pillow 11 + NumPy + Pilmoji |
| デプロイ | Railway |
| 認証 | Google Service Account (JSON キー) |

---

## クイックリンク

- [アーキテクチャ概要](architecture/overview.md)
- [イベント Cog](cogs/events.md)
- [スラッシュコマンド](cogs/commands.md)
- [ランクシステム](services/rank_system.md)
- [VC サービス](services/voice.md)
- [Firestore 設計](firestores/overview.md)
- [キューシステム](infrastructure/queue.md)
