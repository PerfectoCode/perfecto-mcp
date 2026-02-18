from typing import List, Any, Optional

from models.user import User


def format_users(users: dict[str, Any], params: Optional[dict] = None) -> List[User]:
    first_name = users.get('firstName') or ''
    last_name = users.get('lastName') or ''
    display_name = f"{first_name} {last_name}".strip() or users.get("username", "Unknown")
    
    formatted_users = [
        User(
            username=users.get("username") or "unknown",
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
        )
    ]
    return formatted_users
