from typing import List, Any, Optional

from config.perfecto import get_cloud_app_url
from models.user import User


def format_users(users: dict[str, Any], params: Optional[dict] = None) -> List[User]:
    first_name = users.get('firstName') or ''
    last_name = users.get('lastName') or ''
    display_name = f"{first_name} {last_name}".strip() or users.get("username", "Unknown")
    cloud_name = (params or {}).get("cloud_name") or ""
    cloud_url = get_cloud_app_url(cloud_name) if cloud_name else ""

    formatted_users = [
        User(
            username=users.get("username") or "unknown",
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            cloud_name=cloud_name,
            cloud_url=cloud_url,
        )
    ]
    return formatted_users
