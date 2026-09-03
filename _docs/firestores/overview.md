# Firestore データ層

## 設計方針

すべての Firestore アクセスは `FirestoreBase` を継承した `fs_*.py` クラスを通して行います。  
直接 `doc.update()` や `doc.set()` を呼ぶコードは存在しません。

```
FirestoreBase._run(async_fn)
  └─ QueueManager_FireStore.enqueue(async_fn)
       └─ Firestore AsyncClient
```

詳細 → [infrastructure/queue.md](../infrastructure/queue.md)

---

## コレクション一覧

### Rank（fs_rank.py）

**ランクシステムのポイント管理**

```
Rank/{user_id}
  ├─ total_tc: int    TC 累計ランクポイント
  └─ total_vc: int    VC 累計ランクポイント
```

| メソッド | 説明 |
|---|---|
| `get_state()` | `RankState(user_id, total_tc, total_vc)` を返す |
| `add_tc_points(add)` | Increment で原子加算（set+merge でドキュメント自動作成） |
| `add_vc_points(add)` | 同上 |
| `set_points(total_tc, total_vc)` | 管理者用絶対値上書き |
| `ensure_exists()` | 未作成の場合のみ初期化 |

---

### Points（fs_points.py）

**経済ポイントの台帳管理**

```
Points/{user_id}                   ヘッダードキュメント
  ├─ total_points: int
  ├─ totals_by_event: dict          {Points_Type: int}
  ├─ totals_by_genre: dict          {Genre_Type: int}
  ├─ last_updated_at: datetime
  └─ Events/{event_id}             イベント台帳（サブコレクション）
       ├─ type: str                 Points_Type
       ├─ genre: str                Genre_Type
       ├─ delta: int                付与/消費量（正負）
       ├─ reason: str
       ├─ created_at: datetime
       └─ metadata: dict
```

---

### VC_LOG（fs_voice_log.py）

**VC の入退室・ミュートイベントログ**

```
VC_LOG/{vc_id}
  ├─ created_at: datetime
  ├─ guild_id: int
  ├─ vc_id: int
  ├─ deleted_at: datetime          (削除時に設定)
  ├─ owner_user_id: int
  ├─ points_calculated: bool       経済ポイント計算済みフラグ
  ├─ points_calculated_at: datetime
  └─ members/{user_id}/events/{event_id}
       ├─ event: "JOIN"|"LEAVE"|"MUTE_ON"|"MUTE_OFF"
       ├─ ts: datetime
       └─ extra: {guild_id, category_id, channel_id, self_mute, mute, ...}
```

---

### Users / Messages（fs_user_info.py）

**プロフィールとメッセージの紐付け**

```
Users/{user_id}/Profile/main
  ├─ user_id: int
  ├─ display_name: str
  └─ message_ids: list[int]

Messages/{message_id}
  └─ user_id: int
```

---

### Judging（fs_judging.py）

**プロフィール審査フォーラムのスレッド管理**

```
Judging/{thread_id}
  ├─ user_id: int
  ├─ message_id: int
  ├─ status: "pending"|"pass"|"fail"
  ├─ judged_by: int
  ├─ judged_at: datetime
  └─ tags: list[int]
```

---

### JudgingTemp（fs_judging_temp.py）

仮メンバー審査の状態管理。Judging と独立したコレクション。

---

### Recruitments（fs_recruitments.py）

**匿名募集リクエスト管理**

```
Recruitments/{recruit_id}
  ├─ owner_id: int
  ├─ status: "open"|"matched"|"closed"
  ├─ settings: dict
  ├─ filters: dict
  ├─ created_at: datetime
  └─ matched_user_id: int
```

---

### Talk_History（fs_talk_history.py）

**VC 共在セッション記録**

```
Talk_History/{session_id}
  ├─ user_ids: list[int]
  ├─ vc_id: int
  ├─ start_at: datetime
  ├─ end_at: datetime
  └─ duration_seconds: int
```

最小共在時間 `qualify_seconds=300`（5 分）未満のセッションは保存されない。

---

### VcTcSync（fs_vc_tc_sync.py）

**ノックルームの VC ↔ TC ID マッピング**

```
VcTcSync/{vc_id}
  └─ tc_id: int
```

| メソッド | 説明 |
|---|---|
| `add_ids(vc_id, tc_id)` | マッピング作成 |
| `get_ids(vc_id)` | TC ID 取得 |
| `delete_ids(vc_id)` | ルーム削除時にクリーンアップ |

---

### ListManager（fs_list_manager.py）

**ブラックリスト管理**

---

### Message_Log（fs_message_log.py）

**メッセージ監査ログ**

---

## FirestoreBase メソッド一覧

全 `fs_*.py` クラスが継承する基底クラスのメソッドです。

| メソッド | Firestore 操作 | 用途 |
|---|---|---|
| `_fetch(doc_ref)` | `doc.get()` | 読み取り |
| `_save(doc_ref, data, merge=True)` | `doc.set()` | 作成・マージ |
| `_update(doc_ref, data)` | `doc.update()` | 既存ドキュメント更新（注意: ドキュメント未作成で 404） |
| `_delete(doc_ref)` | `doc.delete()` | 削除 |
| `_add(col_ref, data)` | `col.add()` | 自動 ID でドキュメント追加 |

> **注意:** `_update` は対象ドキュメントが存在しない場合 `404 NotFound` になる。  
> 新規ユーザーへの初回書き込みには `_save(merge=True)` を使用すること。

---

## Increment を使った原子加算

ポイントの加算には Firestore の `Increment` を使用します。  
`_save(merge=True)` との組み合わせで、ドキュメントが存在しない場合も自動作成されます。

```python
from google.cloud.firestore_v1 import Increment

await self._save(
    self._doc(user_id),
    {"total_tc": Increment(int(add))},
    merge=True
)
```
