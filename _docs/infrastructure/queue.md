# Firestore キューマネージャー

`queuemanager/google/firestore.py` に実装された Firestore 同時実行制御レイヤーです。  
全 Firestore 書き込み・読み取りはこのキューを経由します。

---

## 設計目的

Discord Bot は短時間に大量のイベントを受信します（VC の一斉入退室など）。  
各イベントが直接 Firestore を叩くと：

- Firestore の同時実行クォータを超過する
- レートリミットエラーが多発する
- エラー処理が各 `fs_*.py` に散在する

**解決策:** 全操作を FIFO キューに積み、同時実行数を制限しながら順次処理する。

---

## アーキテクチャ

```
Discord Event × N
      │
      ▼ (即時 enqueue)
  asyncio.Queue
      │
      ▼ (FIFO 取り出し)
  worker_task()
      │
      ├─ asyncio.Semaphore(5)   最大 5 並列
      │
      ├─ Retry.retry(func)      最大 3 回リトライ・2 秒間隔
      │
      └─ Firestore AsyncClient
```

---

## 主要パラメータ

| パラメータ | 値 | 説明 |
|---|---|---|
| `concurrency` | 5 | 最大同時実行数（Semaphore） |
| リトライ回数 | 3 | 失敗時の最大再試行回数 |
| リトライ間隔 | 2 秒 | 試行間のウェイト |
| バックオフ上限 | 60 秒 | ResourceExhausted 時の最大待機時間 |

---

## 自動リトライ・バックオフ

`Retry.retry()` が以下のエラーを自動ハンドリングします：

| エラー | 処理 |
|---|---|
| `GoogleAPICallError` | リトライ（最大 3 回） |
| `RetryError` | リトライ |
| `aiohttp.ClientResponseError` | リトライ |
| `ResourceExhausted`（クォータ超過） | 指数バックオフ（base=1.0, max=60.0 秒）後リトライ |

成功時はバックオフをリセット。

---

## 使用方法

`FirestoreBase` を継承することで自動的にキューが使用されます。  
`fs_*.py` を書くときに `_run()` を直接意識する必要はありません。

```python
class FS_Rank(FirestoreBase):
    async def add_vc_points(self, user_id, add):
        async def _op():
            return await self._doc(user_id).set(
                {"total_vc": Increment(add)}, merge=True
            )
        return await self._run(_op)   # キュー経由で実行
```

または基底クラスの `_save` / `_update` 等を使えば `_run` も不要です：

```python
await self._save(self._doc(user_id), {"total_vc": Increment(add)}, merge=True)
```

---

## エラーログ

3 回リトライしてもなお失敗した場合、`FirestoreBase._run()` でキャッチされ  
`logger.error("[FS_XXX] queue error: ...")` としてログに記録されます。  
Bot のクラッシュは発生しません（戻り値は `None`）。

---

## シングルトン

`firestore_queue = QueueManager_FireStore(concurrency=5)` がモジュール起動時に 1 インスタンス作成され、  
全 `FirestoreBase` サブクラスが共有します。これにより同時実行数の制御が一元管理されます。

```python
# firestores/base.py
class FirestoreBase:
    def __init__(self, queue_manager=firestore_queue):
        self.queue = queue_manager   # シングルトンを参照
```
