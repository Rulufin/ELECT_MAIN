# VC ドメインサービス

`services/voice/` 以下に配置されたサービス群です。  
全サービスは `on_voice_state.py` から `VoiceStateContext` を受け取ります。

---

## VoiceStateContext

`services/voice/state/event.py` の `build_context()` で生成され、全サービスに共有されます。

```python
@dataclass
class VoiceStateContext:
    member:           discord.Member
    before:           discord.VoiceState
    after:            discord.VoiceState
    now:              datetime
    transition:       TransitionKind       # "JOIN" | "LEAVE" | "MOVE" | "NONE"
    before_ch:        Optional[VoiceChannel]
    after_ch:         Optional[VoiceChannel]
    before_excluded:  bool     # before_ch が待機チャンネルかどうか
    after_excluded:   bool
    to_knock_waiting: bool     # ノック待機チャンネルへの移動
    from_knock_category: bool  # ノックカテゴリからの退室
    left_knock_vc:    bool     # ノック VC からの退室
```

**待機チャンネル（`NOT_CONNECT_VC_IDS`）:**  
PUBLIC、FREE_ROOM、QM、ROOM、KNOCK_ROOM、SLEEP_VC  
→ これらのチャンネルは「作成口」であり、実際の在室は個人VC（作成後）で行う。

---

## KnockService（ノックルーム）

`services/voice/knock/service.py`

プライベートな 1:1 または少人数通話ルームを自動生成するシステムです。

### ノックフロー

```
ユーザーがノックカテゴリの VC に参加
  ├─ 個別許可なし → 即座にディスコネクト + 警告 embed 送信
  │
  └─ 個別許可あり → ペア TC の読み書き権限を付与
       └─ ルームオーナーがノック VC を操作
            └─ create_knock_room_vc_and_tc()
                 ├─ VC 作成: 🚪{display_name}の部屋
                 ├─ TC 作成: 💬チャット  (VC ↔ TC の権限連動)
                 ├─ FS_VC_TC_SYNC に VC→TC マッピング保存
                 ├─ VC_Menu_Embed + Group_Knock_Menu_View 送信
                 └─ オーナーを新 VC に移動
```

### クリーンアップ

```
ノック VC 退室
  └─ _cleanup_knock_room_if_empty()
       ├─ 残存する人間メンバーを確認
       ├─ 全員退室 → ペア TC を削除
       ├─             VC を削除
       └─             Firestore マッピングを削除
```

---

## QM_Service（クイックマッチ）

`services/voice/quick_match/service.py`

SECRET_QM カテゴリで 2 人が揃った瞬間にルームを自動クローズします。

```
SECRET_QM カテゴリ VC に 2 人目が参加
  └─ _is_already_closed() チェック（冪等性）
       └─ 未クローズ → パーミッション上書き
            ├─ @everyone / MEMBER / 性別ロール → deny view/connect
            └─ 在室メンバー全員 → allow view/connect
            └─ マッチ確定メッセージ送信（メンション付き）
```

失敗時は 3 秒待機で最大 3 回リトライ。

---

## VoiceLogService（VC ログ）

`services/voice/voice_log/service.py`

全 VC イベントを Firestore `VC_LOG` に記録します。

### ログされるイベント

| イベント | タイミング |
|---|---|
| `JOIN` | 非待機 VC に参加 |
| `LEAVE` | 非待機 VC から退室 |
| `MUTE_ON` | マイクミュートが ON になった |
| `MUTE_OFF` | マイクミュートが OFF になった |

待機チャンネル（PUBLIC、QM 等）への出入りはログしない。  
MOVE（移動）は LEAVE + JOIN の 2 イベントとして記録。

---

## TalkHistoryService（通話履歴）

`services/voice/talk_history/service.py`

誰と誰が何分間同じ VC にいたかを記録するサービスです。

### 動作設定

| パラメータ | 値 | 説明 |
|---|---|---|
| `qualify_seconds` | 300 秒 | 保存対象となる最小共在時間 |
| `flush_seconds` | 30 秒 | 定期フラッシュ間隔 |
| `recent_write_ttl` | 15 秒 | 重複書き込み防止 TTL |

### フラッシュタイミング

- VC 削除時 → `flush_vc(vc_id)`
- Bot 再起動時 → `flush_all()`
- 定期タイマー → `flush_seconds` 間隔

---

## JoinNoticeService（参加通知）

`services/voice/join_notice/service.py`

VC に参加したメンバーに対して設定された通知を送るサービスです。

### 通知の種類（handlers）

| ハンドラ | 通知内容 |
|---|---|
| `ProfileJoinNoticeHandler` | メンバーのプロフィールリンクを通知 |
| `TempJudgeJoinNoticeHandler` | 仮メンバー参加時の通知 |

### 抑制条件

| 条件 | 動作 |
|---|---|
| 同一ハンドラ・チャンネルで 5 分以内 | 通知スキップ |
| 60 秒以内の再参加（同チャンネル） | 全通知スキップ |
| 待機チャンネル・除外カテゴリ | 通知しない |

---

## Delete_Service（空 VC 削除）

`services/voice/delete/service.py`

全メンバーが退室した VC を自動削除します。  
`NOT_CONNECT_VC_IDS`（待機チャンネル）は対象外。

---

## UserLimitService（ユーザー制限）

`services/voice/user_limit/service.py`

Bot が VC に参加・退室した際に `user_limit` を調整します。  
Bot の存在がルームの定員に食い込まないよう自動補正します。

---

## Firestore スキーマ（VC 関連）

### VC_LOG（fs_voice_log.py）

```
VC_LOG/{vc_id}
  ├─ created_at, guild_id, vc_id
  ├─ deleted_at              (削除時刻)
  ├─ owner_user_id           (ルームオーナー)
  ├─ points_calculated       (経済ポイント計算済みフラグ)
  └─ members/{user_id}/events/{event_id}
       ├─ event: "JOIN" | "LEAVE" | "MUTE_ON" | "MUTE_OFF"
       ├─ ts: datetime
       └─ extra: {guild_id, category_id, channel_id, self_mute, ...}
```

### VC_TC_SYNC（fs_vc_tc_sync.py）

ノックルームの VC ID ↔ TC ID マッピング。

```
VcTcSync/{vc_id}
  └─ tc_id: int
```

### Talk_History（fs_talk_history.py）

```
Talk_History/{session_id}
  ├─ user_ids: list[int]
  ├─ vc_id: int
  ├─ start_at, end_at: datetime
  └─ duration_seconds: int
```
