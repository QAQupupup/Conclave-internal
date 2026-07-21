"""DAO 聚合层：统一 re-export 各子模块的全部公开函数。

保证 `from app.dao import save_meeting` 等顶层 import 可用。
私有辅助函数（下划线前缀）不在本模块 re-export。
"""

from __future__ import annotations

from app.dao.agent_role_dao import (
    delete_agent_role,
    get_agent_role,
    get_agent_roles_by_ids,
    list_agent_roles,
    save_agent_role,
)
from app.dao.db_init import close_db_pool, init_db
from app.dao.event_dao import last_event_seq, load_events, save_event
from app.dao.meeting_aux_dao import (
    get_meeting_aux,
    save_meeting_aux,
    strip_aux_from_payload,
)
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
from app.dao.message_dao import list_messages, save_message
from app.dao.preference_dao import (
    delete_preference,
    get_all_preferences,
    get_preference,
    set_preference,
)
from app.dao.tag_dao import (
    add_meeting_tag,
    get_meeting_tags,
    list_all_tags,
    remove_meeting_tag,
)

__all__ = [
    "add_meeting_tag",
    "batch_delete_meetings",
    "close_db_pool",
    "delete_agent_role",
    "delete_preference",
    "get_agent_role",
    "get_agent_roles_by_ids",
    "get_all_preferences",
    "get_meeting",
    "get_meeting_aux",
    "get_meeting_tags",
    "get_meetings_by_ids",
    "get_preference",
    "hard_delete_meeting",
    "init_db",
    "last_event_seq",
    "list_agent_roles",
    "list_all_tags",
    "list_meetings",
    "list_messages",
    "load_events",
    "query_meetings",
    "recover_running_meetings",
    "remove_meeting_tag",
    "restore_meeting",
    "save_agent_role",
    "save_event",
    "save_meeting",
    "save_meeting_aux",
    "save_message",
    "set_preference",
    "soft_delete_meeting",
    "strip_aux_from_payload",
]
