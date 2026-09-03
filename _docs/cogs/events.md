# イベント Cog

`cogs/events/` 以下の各ファイルは Discord のイベントを受け取る薄いルーターです。  
ビジネスロジックは持たず、`services/` への委譲のみを行います。

---

## on_ready.py — `On_Ready_Cog`

**リスナー:** `on_ready`

Bot が Discord に接続した直後に 1 度だけ実行されます。

| 処理 | 詳細 |
|---|---|
| ステータス設定 | `discord.CustomActivity` でカスタムステータスを設定 |
| Persistent View 再登録 | 再起動後もボタン等のインタラクションを継続受付するため、全 View を `bot.add_view()` で登録 |
| TalkHistory 復元 | 起動時点で VC に在室中のメンバーを `TalkHistoryService` に登録（再起動でのセッション断絶防止） |
| コマンド同期 | スラッシュコマンドを Discord に同期（最大 3 リトライ、5 秒間隔） |

再登録する View の種別:
- 審査系 (`Judging_Panel_View`, `Judging_Result_View`, `Interview_Panel_View` 等)
- 募集系 (`Recruit_Panel_View` 等)
- VC 系 (`Group_Knock_Menu_View`, `VC_Create_QM_Panel_View` 等)
- ポイント系 (`Point_Manage_Panel_View` 等)

---

## on_channel.py — `on_guild_channel_main_cog`

**リスナー:** `on_guild_channel_delete`

VC・ステージチャンネル削除時に後処理を行います。

```
チャンネル削除
  ├─ FS_Voice_Log.set_vc_deleted()      削除タイムスタンプを記録
  ├─ TalkHistoryService.flush_vc()      在室セッションを確定・保存
  └─ VoicePointCalculator.process_vc_closed()   VC 経済ポイントを付与
```

---

## on_message.py — `On_Message_Main_Cog`

**リスナー:** `on_message`, `on_raw_message_delete`

### on_message

```
メッセージ受信
  ├─ Bot / DM → スキップ
  ├─ SLEEP_MENTION チャンネル → SleepService.handle_sleep_mention()  (早期 return)
  ├─ プロフィールチャンネル → FS_Profile.add_profile_data()
  ├─ PostPointService.grant_post_points()    メディア投稿ポイント付与
  └─ TCRankService.handle_message()          テキストランクポイント付与
```

### on_raw_message_delete

```
メッセージ削除
  └─ PostPointService.revoke_post_points_raw()   付与済みポイントの取り消し
```

---

## on_reaction.py — `On_Reaction_Main_Cog`

**リスナー:** `on_raw_reaction_add`

プロフィール仮チャンネルへのリアクションを起点に審査フローを開始します。

**実行条件:**
- 対象チャンネル: `MAIN_CHANNELS.PROFILE_PROVISIONAL`
- リアクター: 管理者ロール所持
- リアクション総数: 1（重複処理防止）

```
管理者がプロフィールメッセージにリアクション
  └─ ProfileJudgingService.start_from_reaction()
       ├─ プロフィール取得
       ├─ 審査フォーラムにスレッド作成
       └─ Judging_Panel_View を添付
```

---

## on_voice_state.py — `On_Voice_State_Main_Cog`

**リスナー:** `on_voice_state_update`  
**バックグラウンドタスク:** `_vc_rank_tick` (5 分間隔)

最も複雑なイベント Cog。全 VC ドメインサービスを統合します。

### インスタンス化するサービス

| サービス | 役割 |
|---|---|
| `KnockService` | ノックルーム生成・権限管理 |
| `QM_Service` | クイックマッチルームのクローズ |
| `VoiceLogService` | JOIN/LEAVE/MUTE イベントの Firestore 記録 |
| `UserLimitService` | Bot 入退室時のユーザー制限調整 |
| `Delete_Service` | 空 VC の自動削除 |
| `TalkHistoryService` | VC 共在セッション追跡 |
| `JoinNoticeService` | VC 参加通知送信 |
| `VCRankService` | VC ランクポイント管理 |

### イベント処理フロー

```
on_voice_state_update
  │
  ├─ build_context()               VoiceStateContext を生成
  │
  ├─ [チャンネル変更 & 全メンバー]
  │    └─ UserLimitService         ユーザー制限調整
  │
  ├─ [Bot → スキップ]
  │
  ├─ [チャンネル変更 & 人間]
  │    ├─ VCRankService            セッション開始・終了（←knock より前に必ず実行）
  │    ├─ KnockService             ノックフロー（handled=True なら以降スキップ）
  │    ├─ QM_Service               クイックマッチ処理
  │    ├─ Delete_Service           空VC削除
  │    ├─ VoiceLogService          チャンネル変更ログ
  │    └─ JoinNoticeService        参加通知
  │
  ├─ TalkHistoryService            常に実行（チャンネル変更有無問わず）
  └─ VoiceLogService               ミュート変更ログ（常に実行）
```

> **設計上の注意点:**  
> `VCRankService` は `KnockService` の早期 return より**前**に呼ぶ。  
> これにより、ノックフローで処理が完結した場合もセッションの整合性が保たれる。

### _vc_rank_tick バックグラウンドタスク

```python
@tasks.loop(minutes=5)
async def _vc_rank_tick(self):
    await self.vc_rank_service.tick(self.bot)
```

- Bot 起動後 `wait_until_ready()` を待ってから開始
- 開始前に `seed_guild()` で既在室メンバーのセッションを初期化
- tick 内でエラーが発生してもタスクが停止しないよう `try/except` で保護
