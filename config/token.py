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
        self.token = token
        self.cloud_name = cloud_name

    @classmethod
    @lru_cache(maxsize=1)
    def from_file(cls, path: Union[str, Path], cloud_name: str) -> "PerfectoToken":
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise PerfectoTokenError(f"directory or file does not exist: {p!r}")

        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            raise PerfectoTokenError(f"Error reading/parsing file at {p!r}: {e}") from e

        try:
            token_val = raw
            cloud_name_val = cloud_name
        except KeyError as e:
            raise PerfectoTokenError(f"missing field {e.args[0]!r} at {p!r}") from e

        return cls(token=token_val, cloud_name=cloud_name_val)

    def __repr__(self):
        return f"<PerfectoToken cloud_name={self.cloud_name!r} token={'*' * 8}>"
