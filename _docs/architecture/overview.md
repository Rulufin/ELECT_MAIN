# アーキテクチャ概要

## ディレクトリ構成

```
ELECT_MAIN/
├── main.py                   Bot エントリーポイント
├── configs/
│   ├── google_setup.py       Google / Firestore クライアント シングルトン
│   └── logger_setup.py       ロギング設定（コンソール・ファイル・Discord 転送）
├── cogs/
│   ├── events/               Discord イベントリスナー
│   └── commands/             スラッシュコマンド
├── services/                 ドメインロジック（機能ごとにサブディレクトリ）
├── firestores/               Firestore データアクセス層（fs_*.py）
├── utils/                    共通ヘルパー（IDs・色・絵文字・型変換）
├── queuemanager/             Firestore 同時実行制御キュー
├── assets/                   画像・フォント・認証 JSON
└── tools/                    内部スクリプト
```

---

## 起動フロー

```
main.py
  └─ MyBot(commands.Bot)
       └─ setup_hook()
            ├─ client.initialize()      # Firestore AsyncClient 初期化
            ├─ load cogs/events/*       # イベント Cog ロード（順序固定）
            └─ load cogs/commands/*     # コマンド Cog ロード
```

**Cog ロード順:**

```python
# events
('on_ready', 'on_channel', 'on_message', 'on_reaction', 'on_voice_state')

# commands
('judging', 'judging_temp', 'list_manager', 'profile',
 'secret_recruit', 'points', 'vc_create', 'rank')
```

`on_ready` イベントで **全 Persistent View の再登録** と **VCRankService の seed_guild** を実行し、Bot 再起動後もセッション整合性を保つ。

---

## レイヤー設計

```
Discord Event / Slash Command
        │
    cogs/  (薄いルーター)
        │  ContextObject を生成して委譲
        ▼
   services/  (ドメインロジック)
        │  ID だけを渡して書き込みを委譲
        ▼
  firestores/  (データアクセス層)
        │  全操作をキュー経由で実行
        ▼
  QueueManager  →  Firestore (AsyncClient)
```

- **Cog は薄いルーター**: イベントの振り分けと `Context` 生成のみを担う。
- **Service がロジックを持つ**: 状態管理・判定・計算はすべて `services/` に閉じる。
- **Firestore アクセスは必ずキュー経由**: 直接 `doc.update()` を呼ばず、`FirestoreBase._run()` を通す。

---

## 共通設計パターン

### 1. Firestore キュー（全書き込みの中央集権）

全 `fs_*.py` は `FirestoreBase` を継承し、`QueueManager_FireStore` シングルトンを通してのみ Firestore を操作する。  
→ Firestore クォータ超過・レートリミットの自動リトライ・指数バックオフを一箇所で管理。

```python
# FirestoreBase
async def _save(self, doc_ref, data, *, merge=True):
    async def _op():
        return await doc_ref.set(data, merge=merge)
    return await self._run(_op)   # キュー経由
```

詳細 → [infrastructure/queue.md](../infrastructure/queue.md)

---

### 2. VoiceStateContext（VC イベントの事前計算）

`on_voice_state_update` で毎回 before/after を比較する代わりに、  
`build_context(member, before, after, now)` が遷移フラグを一括計算した `VoiceStateContext` を返す。  
下流の全サービスは同じオブジェクトを受け取る。

```python
@dataclass
class VoiceStateContext:
    transition: TransitionKind       # "JOIN" | "LEAVE" | "MOVE" | "NONE"
    before_ch:  Optional[VoiceChannel]
    after_ch:   Optional[VoiceChannel]
    before_excluded: bool            # 待機チャンネルかどうか
    after_excluded:  bool
    to_knock_waiting: bool
    from_knock_category: bool
    left_knock_vc: bool
```

---

### 3. Cooldown-before-await（二重付与防止）

`async` 関数で await をまたいで状態を更新すると、同時実行による二重付与が起きる。  
本プロジェクトでは「**await の前に状態を確定させる**」ルールを徹底している。

```python
# TCRankService.handle_message
self._cooldowns[member.id] = now        # ← await の前に確定
await self.fs_rank.add_tc_points(...)

# VCRankService.tick
session.credited_points += to_grant     # ← await の前に確定
await self.fs_rank.add_vc_points(...)
```

---

### 4. Rule テーブル分離（_rank_config.py パターン）

どのチャンネル・カテゴリでランクポイントを付与するかは、ロジックコードから完全に切り離された  
`_rank_config.py` のルールテーブルで管理する。  
新チャンネルの追加はテーブル編集だけで済み、サービスコードに触れない。

```python
VC_CATEGORY_RULES: dict[int, RankRule] = {
    MAIN_CATEGORIES.PUBLIC_PLAY: RankRule(enabled=True, multiplier=5.0, mic_mute=False),
    MAIN_CATEGORIES.WELCOMEs:   RankRule(enabled=False),
    ...
}
```

---

### 5. Persistent View の再登録

discord.py では Bot 再起動後にボタンなどの `View` が失われる。  
`on_ready` で `bot.add_view(ViewClass())` を全 View に対して実行することで、  
再起動後もインタラクションを継続受付できる。

---

### 6. 二分探索によるレベル計算

ランクレベルの逆算（ポイント → レベル）は lookup table を持たず、  
32 イテレーションの二分探索で行う。これにより曲線パラメータを変えても  
テーブルの再生成が不要で、上限なしのレベルにも対応できる。

```python
for _ in range(32):
    mid = (lo + hi) / 2.0
    if total_points_for_level(mid, params=params) <= p:
        lo = mid
    else:
        hi = mid
```

---

## 依存関係の方向

```
cogs → services → firestores → QueueManager → Firestore
cogs → utils
services → utils
services → firestores (直接インスタンス化して注入)
```

循環インポートは発生しない設計になっている。  
`services/` 内のサブモジュール間の依存も最小限に保たれており、  
各 Service は独立してテスト・差し替えが可能。
