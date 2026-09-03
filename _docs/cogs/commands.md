# スラッシュコマンド

`cogs/commands/` 以下の各 Cog が提供するスラッシュコマンドの一覧です。  
管理者専用コマンドには `default_permissions(administrator=True)` が付いています。

---

## rank.py — `Rank_Cog`

ランクカードの表示・管理コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/rank` | 自分または指定ユーザーのランクカード画像を表示 | 全員 |
| `/rank-set` | ユーザーの TC / VC ポイントを絶対値で設定 | 管理者 |
| `/rank-add` | ユーザーの TC / VC ポイントを加算 | 管理者 |

### ユーザー指定の解決ロジック

`/rank`・`/rank-set`・`/rank-add` の対象ユーザーは **メンション・生 ID 両方**に対応しています。

```python
# utils/discord/helpers/user_ids.py
coerce_user_ids_or_raw_id(str)  →  set[int]
```

`/rank` では ID 解決後に `guild.get_member()` → `bot.fetch_user()` の順にフォールバックし、  
ギルド外ユーザーのランクカードも表示できます。

---

## points.py — `Points_Main_Cog`

ポイント経済システムの管理コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/vcログ確認` | 指定 VC の全イベントを Firestore から取得・表示 | 管理者 |
| `/ポイントパネル` | ポイント管理パネル View を送信 | 管理者 |
| `/add-point` | ユーザーへのポイント加算・減算（メンション or ID） | 管理者 |
| `/check-userlists` | 全ユーザーのポイント総計をランキング形式で表示（最大 5,000 人） | 管理者 |
| `/delete_pic_point` | 画像投稿ポイントの一括削除（誤付与修正用） | 管理者 |
| `/migrate_point_fields` | Firestore のフィールド名修正・合計再計算 | 管理者 |
| `/set_pic_point` | 画像投稿チャンネルを遡及スキャンしてポイントを付与（最大 10,000 件） | 管理者 |

---

## judging.py — `Judging_Main_Cog`

審査パネルの UI 管理コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/プロフ審査パネル修正` | 既存メッセージに `Judging_Panel_View` を再適用 | 管理者 |
| `/審査内容パネル修正` | 既存メッセージに `Judging_Result_View` を再適用 | 管理者 |
| `/サーバー案内パネル修正` | 特定ユーザー向けサーバー案内 embed + View を既存メッセージに適用 | 管理者 |
| `/案内人用パネル` | 案内人用パネルを現在のチャンネルに送信 | 管理者 |

---

## profile.py — `Profile_Main_Cog`

プロフィールの Firestore 保存コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/プロフィール一括保存` | 男女プロフィールチャンネルの全メッセージを Firestore に保存（50 件ずつ・1.5 秒間隔） | 管理者 |
| `/プロフィール保存` | 特定メッセージ（ジャンプ URL 指定）のプロフィールを 1 件保存 | 全員 |

---

## secret_recruit.py — `Secret_Recruit_Main_Cog`

裏募集システムのパネル管理コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/裏募集作成確認` | 募集作成パネルと確認パネルを現在のチャンネルに送信 | 管理者 |

---

## vc_create.py — `VC_Create_Main_Cog`

VC 作成パネルの管理コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/vc作成パネル` | VC 作成パネルを送信（現在は `vc_type=qm` のみ対応） | 管理者 |

---

## list_manager.py — `List_Manager_Main_Cog`

ブラックリスト管理のパネル送信コマンドです。

| コマンド | 説明 | 権限 |
|---|---|---|
| `/ブラックリスト管理` | ブラックリスト管理パネルを送信 | 管理者 |

---

## 共通設計

### 個別権限 vs グループ権限

コマンドグループ (`app_commands.Group`) は使わず、コマンドを個別に定義しています。  
これにより各コマンドに `@app_commands.default_permissions(administrator=True)` を独立して設定できます。

### defer パターン

画像生成・Firestore アクセスなど処理が重いコマンドは必ず最初に `defer()` を呼びます。

```python
await interaction.response.defer()          # 公開
await interaction.response.defer(ephemeral=True)  # 管理者向けは ephemeral
```

### ユーザー指定の統一

ポイント・ランク系の管理コマンドは `str` 型パラメータを受け取り、  
`coerce_user_ids_or_raw_id()` でメンション・生 ID 両方を `set[int]` に変換します。
