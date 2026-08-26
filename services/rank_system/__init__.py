'''
/root
├─ cogs/
│  ├─ events/
│  │  ├─ on_message.py      # TCRankService.handle_message() を呼ぶ
│  │  └─ on_voice_state.py  # VCRankService.handle_voice_state() + 5分tick
│  └─ commands/
│     └─ rank.py            # /rank コマンド
│
├─ services/rank_system/
│  ├─ service.py            # VCRankService / TCRankService（ロジック本体）
│  ├─ level_math.py         # points -> level / next / progress
│  ├─ voice_points.py       # 秒 -> vc_points 変換
│  ├─ elect_rank_image.py   # ランクカード画像生成
│  ├─ _rank_config.py       # VC/TCカテゴリ・チャンネルルール定義
│  └─ notifier.py           # VC削除時の通知

│
└─ firestores/
   ├─ fs_rank.py            # Rank/{user_id} total_tc/total_vc (increment/get)
   └─ fs_voice_log.py       # VCログ永続 (append/query/flush)

'''
