"""LAN API route handlers.

Each module owns a group of related HTTP endpoints. The parent ``api.py``
imports every handler and registers them in ``setup_routes()``.
"""
from AssetsManager.lan.routes.auth import (
    handle_login,
    handle_register,
    handle_verify_key,
    handle_logout,
    handle_me,
)
from AssetsManager.lan.routes.downloads import (
    handle_download,
    handle_batch_download,
)
from AssetsManager.lan.routes.files import handle_directory_summaries, handle_files
from AssetsManager.lan.routes.metadata import (
    handle_meta,
    handle_search,
    handle_home,
    handle_tree,
    handle_projects,
    handle_project_detail,
)
from AssetsManager.lan.routes.pages import (
    handle_index,
    handle_detail_page,
    handle_login_page,
    handle_browse_page,
)
from AssetsManager.lan.routes.shares import (
    handle_create_share,
    handle_list_shares,
    handle_delete_share,
    handle_share_page,
    handle_verify_share_password,
    handle_share_download,
    handle_share_preview,
    handle_share_info,
)
from AssetsManager.lan.routes.system import (
    handle_info,
    handle_tunnel_status,
    handle_stats,
)
from AssetsManager.lan.routes.tags import (
    handle_tags,
    handle_create_tag,
    handle_rename_tag,
    handle_delete_tag,
)
from AssetsManager.lan.routes.thumbnails import (
    handle_thumbnail,
    handle_thumbnail_batch,
)
from AssetsManager.lan.routes.users import (
    handle_users,
    handle_toggle_user,
    handle_invites,
    handle_create_invite,
    handle_revoke_invite,
    handle_activity,
    handle_online_users,
)
from AssetsManager.lan.routes.websocket import handle_websocket

__all__ = [
    "handle_index",
    "handle_detail_page",
    "handle_login_page",
    "handle_browse_page",
    "handle_files",
    "handle_directory_summaries",
    "handle_thumbnail",
    "handle_thumbnail_batch",
    "handle_download",
    "handle_batch_download",
    "handle_projects",
    "handle_project_detail",
    "handle_tree",
    "handle_home",
    "handle_tags",
    "handle_create_tag",
    "handle_rename_tag",
    "handle_delete_tag",
    "handle_search",
    "handle_meta",
    "handle_info",
    "handle_login",
    "handle_register",
    "handle_verify_key",
    "handle_logout",
    "handle_me",
    "handle_users",
    "handle_toggle_user",
    "handle_invites",
    "handle_create_invite",
    "handle_revoke_invite",
    "handle_activity",
    "handle_online_users",
    "handle_tunnel_status",
    "handle_stats",
    "handle_create_share",
    "handle_list_shares",
    "handle_delete_share",
    "handle_share_page",
    "handle_verify_share_password",
    "handle_share_download",
    "handle_share_preview",
    "handle_share_info",
    "handle_websocket",
]
