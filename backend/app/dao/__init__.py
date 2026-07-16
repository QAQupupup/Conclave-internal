"""DAO 聚合层：统一 re-export 各子模块的全部公开函数。

保证 `from app.dao import save_meeting` 等顶层 import 可用。
私有辅助函数（下划线前缀）不在本模块 re-export。
"""
from __future__ import annotations

from app.dao.db_init import close_db_pool, init_db
from app.dao.meeting_dao import (
    batch_delete_meetings,
    get_meeting,
    get_meetings_by_ids,
    hard_delete_meeting,
    list_meetings,
    query_meetings,
    recover_running_meetings,
    restore_meeting,
    save_meeting,
    soft_delete_meeting,
)
from app.dao.meeting_aux_dao import (
    get_meeting_aux,
    save_meeting_aux,
    strip_aux_from_payload,
)
from app.dao.message_dao import list_messages, save_message
from app.dao.event_dao import last_event_seq, load_events, save_event
from app.dao.tag_dao import (
    add_meeting_tag,
    get_meeting_tags,
    list_all_tags,
    remove_meeting_tag,
)
from app.dao.preference_dao import (
    delete_preference,
    get_all_preferences,
    get_preference,
    set_preference,
)
from app.dao.agent_role_dao import (
    delete_agent_role,
    get_agent_role,
    get_agent_roles_by_ids,
    list_agent_roles,
    save_agent_role,
)

__all__ = [
    "close_db_pool", "init_db",
    "save_meeting", "get_meeting", "list_meetings", "query_meetings",
    "get_meetings_by_ids", "recover_running_meetings",
    "soft_delete_meeting", "hard_delete_meeting", "restore_meeting",
    "batch_delete_meetings",
    "save_meeting_aux", "get_meeting_aux", "strip_aux_from_payload",
    "save_message", "list_messages",
    "save_event", "load_events", "last_event_seq",
    "list_all_tags", "get_meeting_tags", "add_meeting_tag", "remove_meeting_tag",
    "get_preference", "set_preference", "get_all_preferences", "delete_preference",
    "list_agent_roles", "get_agent_role", "save_agent_role",
    "delete_agent_role", "get_agent_roles_by_ids",
]
