from datetime import datetime, timezone, timedelta
from firebase_store import FirebaseStore

TPE = timezone(timedelta(hours=8))
GROUP_PATH = "line_groups"

def register_group(group_id: str):
    if not group_id:
        return
    FirebaseStore().root.child(GROUP_PATH).child(group_id).set({
        "active": True,
        "updated_at": datetime.now(TPE).isoformat(timespec="seconds"),
    })

def get_active_groups():
    data = FirebaseStore().root.child(GROUP_PATH).get() or {}
    if not isinstance(data, dict):
        return []
    return [
        gid for gid, value in data.items()
        if isinstance(value, dict) and value.get("active", True)
    ]

def disable_group(group_id: str):
    if group_id:
        FirebaseStore().root.child(GROUP_PATH).child(group_id).update({
            "active": False
        })
