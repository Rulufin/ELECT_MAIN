# 審査・裏募集システム

---

## 審査システム（Judging）

`services/judging/` に実装されたプロフィール審査ワークフローです。  
管理者のリアクションを起点に審査フォーラムスレッドを生成し、  
複数ステップの UI で審査結果を記録します。

### ファイル構成

```
services/judging/
├── profile/
│   ├── service.py         ProfileJudgingService
│   └── ui/
│       ├── views.py       審査 UI View 群（Persistent）
│       └── embeds.py      審査フロー各段階の Embed
├── temp/                  仮メンバー審査パイプライン（独立系統）
└── helper/                共通ヘルパー
```

### 審査フロー

```
① プロフィール仮チャンネルにプロフィールが投稿
  └─ 管理者がリアクション（絵文字）を付与
       └─ on_reaction_add → ProfileJudgingService.start_from_reaction()

② 審査フォーラムにスレッド作成
       ├─ プロフィール内容を embed で表示
       └─ Judging_Panel_View（ボタン UI）を添付

③ 審査パネルで操作
       ├─ 合格 → Judging_Result_View（結果記録 UI）
       ├─ ロール付与・サーバー案内送信
       └─ FS_Judging に結果を保存

④ Persistent View 再登録（on_ready）
       └─ 再起動後もボタンが機能し続ける
```

### 仮メンバー審査（judging_temp）

メインの審査フローとは独立した、仮免許メンバー向けの簡易審査パイプラインです。  
`cogs/commands/judging_temp.py` と `services/judging/temp/` で管理されます。

### Firestore スキーマ（fs_judging.py）

```
Judging/{thread_id}
  ├─ user_id: int
  ├─ message_id: int          プロフィールメッセージ
  ├─ status: str              "pending" | "pass" | "fail"
  ├─ judged_by: int           審査担当者 user_id
  ├─ judged_at: datetime
  └─ tags: list[int]          フォーラムタグ ID
```

---

## 裏募集システム（Secret Recruit）

`services/recruit/` に実装された匿名マッチングリクエスト機能です。  
ユーザーが希望条件を設定してリクエストを投稿し、  
相手が「受け取る」ことでマッチングが成立します。

### ファイル構成

```
services/recruit/
└── ui/
    ├── views.py   View 群（Panel・Setting・Filter・Post・Check・Receive 等）
    └── embeds.py  各段階の Embed

firestores/fs_recruitments.py   Recruitments データアクセス
```

### 募集フロー

```
① /裏募集作成確認 → 募集パネルを送信

② ユーザーがパネルから操作
       ├─ 基本設定（Recruit_Main_Setting_View）
       ├─ フィルター設定（Recruit_Filter_Panel_View）
       └─ 投稿確認（Recruit_Check_View）→ 投稿

③ 募集投稿が裏募集チャンネルに表示
       └─ 別ユーザーが「受け取る」ボタンを押下
            └─ Receive_View → マッチング成立
```

### 匿名性

- 投稿者の ID は Firestore にのみ保存され、Discord 上には表示されない
- マッチング成立後のみ双方に通知

### Firestore スキーマ（fs_recruitments.py）

```
Recruitments/{recruit_id}
  ├─ owner_id: int
  ├─ status: str             "open" | "matched" | "closed"
  ├─ settings: dict          マッチング条件（性別・年代・スタイル等）
  ├─ filters: dict           フィルター設定
  ├─ created_at: datetime
  └─ matched_user_id: int    マッチング後に設定
```

---

## ブラックリスト管理（ListManager）

`services/list_manager/` に実装されたユーザーブロック機能です。

```
/ブラックリスト管理
  └─ Blacklist_Manage_View を送信
       ├─ ユーザー追加（Blacklist_Add_View）
       ├─ ユーザー確認・削除
       └─ 一覧表示
```

### Firestore スキーマ（fs_list_manager.py）

```
ListManager/{entry_id}
  ├─ target_user_id: int
  ├─ added_by: int
  ├─ reason: str
  └─ created_at: datetime
```
