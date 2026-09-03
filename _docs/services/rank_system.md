# ランクシステム

VC 接続時間とテキスト投稿に応じてランクポイントを付与し、  
レベルカード画像をリアルタイム生成する機能です。

---

## ファイル構成

```
services/rank_system/
├── service.py            VCRankService / TCRankService（ロジック本体）
├── level_math.py         ポイント → レベル 変換数学
├── voice_points.py       秒数 → VCポイント 変換
├── text_points.py        テキストポイント 計算
├── _rank_config.py       チャンネル・カテゴリ別ルール定義
├── elect_rank_image.py   ランクカード画像生成
└── notifier.py           ポイント付与ログ通知

firestores/fs_rank.py     Rank/{user_id} データアクセス
cogs/commands/rank.py     /rank・/rank-set・/rank-add コマンド
cogs/events/on_voice_state.py   VCRankService をホスト
cogs/events/on_message.py       TCRankService をホスト
```

---

## VC ランクシステム（VCRankService）

### セッション管理

VC に参加しているメンバーの状態をインメモリで管理します。

```python
@dataclass
class _VCSession:
    join_time:        datetime    # 参加時刻（UTC）
    guild_id:         int
    channel_id:       int
    multiplier:       float       # 実効倍率（チャンネル倍率 × ロール倍率）
    mic_mute_ok:      bool        # True = ミュート中でも加算対象
    credited_points:  int = 0     # 今セッションで付与済みのポイント
```

### ポイント付与フロー

**①  tick（5 分間隔）**

```
tasks.loop(minutes=5)
  └─ VCRankService.tick(bot)
       ├─ 各セッションの経過秒 × 倍率 → due_points を計算
       ├─ mic_mute_ok=False かつミュート中 → スキップ
       ├─ session.credited_points += to_grant   ← await の前に確定（二重付与防止）
       └─ fs_rank.add_vc_points(user_id, to_grant)
```

**② flush（退室時）**

```
on_voice_state_update（退室検知）
  └─ VCRankService.flush_session(user_id)
       ├─ due_points - credited_points = 残ポイント計算
       ├─ _sessions.pop(user_id)                ← セッション削除
       └─ fs_rank.add_vc_points(残ポイント)
```

**③ seed_guild（Bot 起動時）**

```
_before_vc_rank_tick()
  └─ seed_guild(guild)
       └─ 在室メンバー全員の start_session() を実行
```

### ポイント計算式

```
秒数 → ポイント変換:
  SECONDS_PER_POINT = 12   (12秒で1ポイント = 5ポイント/分)

実効ポイント:
  due = floor((経過秒 × multiplier) / SECONDS_PER_POINT)
```

### チャンネル倍率設定（`_rank_config.py`）

| カテゴリ | 倍率 | ミュート可 |
|---|---|---|
| FREE / KNOCK / QM / ROOM 系 | × 1.0 | ✓ |
| PUBLIC_PLAY | × 5.0 | ✗ (ミュート中は0) |
| WELCOMEs | 無効 | — |

---

## TC ランクシステム（TCRankService）

### ポイント付与フロー

```
on_message
  └─ TCRankService.handle_message(message)
       ├─ Member 確認・GuildChannel 確認
       ├─ resolve_tc_rule() でルール解決
       ├─ is_eligible() で対象チェック
       ├─ クールダウンチェック（30秒）
       ├─ calc_text_points() → 15〜25 pt（3文字未満は0）
       ├─ _cooldowns[member.id] = now   ← await の前に確定（二重付与防止）
       └─ fs_rank.add_tc_points(member.id, points × 倍率)
```

### TC チャンネル倍率設定

| カテゴリ | 倍率 |
|---|---|
| PUBLIC_PLAY | × 2.0 |
| MANAGEMENTs / WELCOMEs / INFORMATIONs | 無効 |

---

## レベル数学（level_math.py）

### 曲線モデル

```
TotalPoints(L) = A × L² × (1 + B × (L / SCALE_LEVEL)⁴)
```

後半レベルほど指数的に必要ポイントが増加します。

### パラメータ

| パラメータ | TEXT | VOICE |
|---|---|---|
| A | 30 | 64 |
| B | 0.36 | 0.83 |
| SCALE_LEVEL | 100 | 100 |
| 最大レベル | 100 | 100 |

### VC ポイントのレベル感（VOICE_PARAMS）

| レベル | 累計ポイント | 連続接続換算 |
|---|---|---|
| Lv 33 | 約 70,000 pt | 約 12 日 |
| Lv 87 | 約 714,000 pt | 約 124 日 |
| Lv 100 | 約 1,171,000 pt | 約 203 日 |

> 参考: ProBot の Lv33 ≈ 70,000 pt・Lv87 ≈ 710,000 pt に合わせたパラメータ設定

### レベル逆算（binary search）

lookup table を持たず、32 イテレーションの二分探索でポイント→レベルを算出。  
パラメータ変更後の再計算不要・上限なしレベルにも対応。

---

## ランクカード画像生成（elect_rank_image.py）

`/rank` コマンドで Pillow + NumPy により生成されるカード画像の仕様です。

### レイアウト（940 × 400 px RGBA）

```
┌─────────────────────────────────────────────┐
│  [TC] Lv42        85300/90000               │ ← NotoSerif wght=700
│  ══════════════════░░░░░░░░   next 4700      │ ← 白→青のグラデバー
│                                             │
│  [VC] Lv33        70375/85305              🟣│ ← アバター 180×180px 円形
│  ══════════════░░░░░░░░░░░░   next 14930    │ ← 白→マゼンタのグラデバー
│                                  [名前]     │
└─────────────────────────────────────────────┘
```

### フォント

| 用途 | フォント | サイズ |
|---|---|---|
| レベル番号 | NotoSerif (wght=700) | 28 px |
| ポイント統計 (`XXXXX/YYYYY`) | NotoSerif (wght=700) | 17 px |
| next ポイント | NotoSerif (wght=700) | 15 px |
| 表示名 | UDデジタル教科書体 N-R | 10〜20 px（自動縮小） |

### グラデーションバー実装

```python
# NumPy で白→色のグラデーション行列を生成
t = np.linspace(0, 1, bar_w)
r = (255 * (1-t) + color[0] * t).astype(np.uint8)
# ...
# 角丸マスクを適用して alpha_composite
```

### 処理フロー

```
ElectRankCardImager.build(user, data)
  ├─ progress_from_points_kind(tc_points, kind="text")
  ├─ progress_from_points_kind(vc_points, kind="voice")
  ├─ グラデーションバー描画（TC: 青 / VC: マゼンタ）
  ├─ レベル番号・統計テキスト描画
  ├─ user.display_avatar.read() → 円形マスクで合成
  ├─ Pilmoji でユーザー名描画（絵文字対応）
  └─ BytesIO に PNG 出力 → discord.File として返却
```

---

## Firestore スキーマ（fs_rank.py）

**コレクション:** `Rank/{user_id}`

| フィールド | 型 | 説明 |
|---|---|---|
| `total_tc` | int | TC 累計ランクポイント |
| `total_vc` | int | VC 累計ランクポイント |

**主要メソッド:**

| メソッド | 処理 |
|---|---|
| `get_state(user_id)` | `RankState` を返す（存在しない場合 None） |
| `add_tc_points(user_id, add)` | `Increment(add)` で原子加算（set+merge でドキュメント自動作成） |
| `add_vc_points(user_id, add)` | 同上 |
| `set_points(user_id, total_tc, total_vc)` | 管理者用絶対値上書き |

> **重要:** `add_*_points` は `_update`（既存ドキュメント必須）ではなく  
> `_save(merge=True)` を使用する。これにより新規ユーザーの初回付与時も  
> 404 エラーなくドキュメントが自動作成される。
