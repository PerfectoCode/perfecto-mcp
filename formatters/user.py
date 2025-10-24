from typing import List, Any, Optional

from models.user import User


def format_users(users: dict[str, Any], params: Optional[dict] = None) -> List[User]:
    formatted_users = [
        User(
            username=users.get("username"),
            display_name=users.get('firstName') + " " + users.get('lastName'),
            first_name=users.get('firstName'),
            last_name=users.get('lastName'),
        )
    ]
    return formatted_users
