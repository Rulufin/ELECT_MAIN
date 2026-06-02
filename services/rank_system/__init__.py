'''
/root
├─ cogs/
│  ├─ events/on_message.py
│  ├─ events/on_voice_state.py
│  └─ events/on_channel.py       # on_guild_channel_delete でもOK
│
├─ services/
│  └─ rank/
│     ├─ __init__.py
│     ├─ level_math.py           # points -> level / next / progress
│     ├─ text_points.py          # message -> gained tc_points
│     └─ voice_points.py         # voice logs -> gained vc_points（集計）
│
└─ firestore/
   ├─ FS_Rank.py                 # tc/vc points 永続（increment/get）
   └─ FS_Voice_Log.py            # VCログ永続（append/query/close）

'''