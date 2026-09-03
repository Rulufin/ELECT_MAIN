# ポイント経済システム

サーバー内の活動に応じてポイントを付与・管理するシステムです。  
ランクシステムとは別の独立した経済システムです。

---

## ファイル構成

```
services/points/
├── service.py             コアロジック（公開プレイ・交換）
├── post/service.py        PostPointService（メディア投稿ポイント）
├── voice/calculator.py    VoicePointCalculator（VC 閉鎖時ポイント計算）
├── enums.py               Points_Type / Genre_Type StrEnum
├── constants.py           交換オプション・ポイント金額定義
└── ui/                    View・Embed 群

firestores/fs_points.py    Points/{user_id} データアクセス
```

---

## ポイント種別（Points_Type）

| 種別 | 説明 |
|---|---|
| `NORMAL_VC_CONNECT` | 通常 VC 参加ポイント |
| `NORMAL_VC_OWNER` | 通常 VC オーナーボーナス |
| `PUBLIC_VC_CONNECT` | 公開 VC 参加ポイント |
| `PUBLIC_VC_OWNER` | 公開 VC オーナーボーナス |
| `PUBLIC_PLAY` | 公開プレイポイント |
| `PHOTO` | 画像・メディア投稿ポイント |
| `ADJUST` | 管理者による手動調整 |
| `PENALTY` | ペナルティ減点 |
| `USE_ICON_EMOJI` / `USE_PRIVATE` / `USE_ROLE` / `USE_OTHER` | 各種消費ポイント |

---

## PostPointService（メディア投稿ポイント）

`services/points/post/service.py`

画像・動画等のメディアを含む投稿にポイントを付与します。

### 付与フロー

```
on_message
  └─ grant_post_points(message)
       ├─ チャンネルが POST_POINT_RULES に含まれるか確認
       ├─ 添付ファイル・embed の有無を確認
       ├─ メッセージ ID で重複チェック
       └─ fs_points.record_event(Points_Type.PHOTO, ...)
```

### 取り消しフロー

```
on_raw_message_delete
  └─ revoke_post_points_raw(guild_id, channel_id, message_id)
       └─ fs_points.delete_event(message_id に紐づくイベント)
```

---

## VoicePointCalculator（VC 閉鎖時ポイント）

`services/points/voice/calculator.py`

VC が削除された際に在室履歴からポイントを計算し付与します。

```
on_guild_channel_delete（VC 削除）
  └─ process_vc_closed(vc_id)
       ├─ VC_LOG から全メンバーのJOIN/LEAVEイベントを取得
       ├─ 各ユーザーのアクティブ在室秒数を計算
       ├─ points_calculated フラグで二重付与防止
       └─ fs_points.record_event(Points_Type.NORMAL_VC_CONNECT, ...)
```

---

## ポイント管理 UI

`/ポイントパネル` コマンドで送信されるパネルから以下の操作が可能です：

| 操作 | View |
|---|---|
| ポイント残高確認 | `Point_Manage_Panel_View` |
| 公開プレイ申請 | `Point_Request_Public_View` → スレッド作成 |
| ポイント交換 | `Point_Exchange_View` → 確認スレッド |

---

## Firestore スキーマ（fs_points.py）

**コレクション:** `Points/{user_id}`

```
Points/{user_id}            ヘッダードキュメント
  ├─ total_points: int
  ├─ totals_by_event: dict   {Points_Type: int}
  ├─ totals_by_genre: dict   {Genre_Type: int}
  ├─ last_updated_at: datetime
  └─ Events/{event_id}       イベント台帳（サブコレクション）
       ├─ type: Points_Type
       ├─ genre: Genre_Type
       ├─ delta: int          付与/消費量（正負）
       ├─ reason: str
       ├─ created_at: datetime
       └─ metadata: dict      追加情報（channel_id, message_id 等）
```

### 主要メソッド

| メソッド | 説明 |
|---|---|
| `record_event()` | ヘッダーの total を Increment しつつイベントを追記 |
| `get_summary()` | 合計・種別内訳を返す |
| `list_all_user_totals()` | 全ユーザー（最大 5,000 人）の合計一覧 |
| `check_totals_by_period()` | 期間指定での集計 |
| `migrate_fix_dotted_fields()` | ドット含みフィールド名の修正・合計再計算 |
