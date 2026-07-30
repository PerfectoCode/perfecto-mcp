from functools import lru_cache
from pathlib import Path
from typing import Union

from config.perfecto import SECURITY_TOKEN_NOT_SET_MESSAGE, PERFECTO_CLOUD_NAME_NOT_SET_MESSAGE


class PerfectoTokenError(Exception):
    """General error with PerfectoToken."""
    pass


# This method it's used as annotation method for tools calls
def token_verify(func):
    def wrapper(self, *args, **kwargs):
        if self.token is None:
            raise PerfectoTokenError(SECURITY_TOKEN_NOT_SET_MESSAGE)
        elif self.token.cloud_name is None:
            raise PerfectoTokenError(PERFECTO_CLOUD_NAME_NOT_SET_MESSAGE)
        return func(self, *args, **kwargs)

    return wrapper


class PerfectoToken:
    __slots__ = ("token", "cloud_name")

    def __init__(self, token: str, cloud_name: str):
        if not token or not isinstance(token, str):
            raise PerfectoTokenError("Invalid security token format: expected non-empty string")
        if cloud_name is not None and (not isinstance(cloud_name, str) or not cloud_name):
            raise PerfectoTokenError("Invalid cloud name format: expected non-empty string")

        self.token = token
        self.cloud_name = cloud_name

    @classmethod
    @lru_cache(maxsize=1)
    def from_file(cls, path: Union[str, Path], cloud_name: str) -> "PerfectoToken":
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise PerfectoTokenError("Token file does not exist or is not a file")

        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            raise PerfectoTokenError(f"Error reading token file: {type(e).__name__}") from e

        token_val = raw.strip()
        if not token_val:
            raise PerfectoTokenError("Token file is empty")

        return cls(token=token_val, cloud_name=cloud_name)

    def __repr__(self):
        return "<PerfectoToken cloud_name=******** token=********>"
