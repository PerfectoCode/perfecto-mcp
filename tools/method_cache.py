"""TTL cache for manager methods. Hits skip another Perfecto API call."""
from __future__ import annotations

import contextlib
import functools
from typing import Any, Awaitable, Callable, Optional

from config.cache import CacheScope, StorePlan, build_cache_key, get_cache
from config.session_context import current_identity
from models.result import BaseResult
from tools.call_state import (
    _cache_bypass,
    _disable_dataframe_materialization,
    _result_format_context,
    _task_management_enabled,
)


def _accumulate_cache_debug(metric: str, value: int = 1) -> None:
    """Observer hook. Debug counters are optional and never fail a call."""
    return None


def resolve_cache_user_id(manager: Any) -> Optional[str]:
    """
    Verified user id that scopes USER cache entries.
    """
    if getattr(manager, "token", None) is None:
        return None
    identity = current_identity()
    user_id = getattr(identity, "user_id", None)
    if user_id is None or not str(user_id).strip():
        return None
    return str(user_id).strip()


def _cache_compact_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return repr(value)
    if isinstance(value, dict):
        keys = sorted(value.keys(), key=lambda x: str(x))
        return "{" + ",".join(f"{k}:{_cache_compact_value(value[k])}" for k in keys) + "}"
    if isinstance(value, (list, tuple, set)):
        items = sorted(value, key=repr) if isinstance(value, set) else value
        return "[" + ",".join(_cache_compact_value(v) for v in items) + "]"
    return repr(value)


def _strip_per_call_fields(value: Any) -> Any:
    """Drop timing/debug that describe one call, so cache hits do not replay them."""
    if isinstance(value, BaseResult):
        value.debug = None
        value.tool_call_started_at = None
        value.tool_call_finished_at = None
        value.tool_call_duration_ms = None
    return value


_RESULT_FORMATS = ("auto", "dataframe", "raw")


def _method_cache_key(
        scope: CacheScope,
        qualified_name: str,
        args: tuple,
        kwargs: dict,
        user_id: Optional[str],
        *,
        result_format: str,
        materialize: int,
        inline: int,
) -> str:
    return build_cache_key(
        scope,
        qualified_name,
        f"args={_cache_compact_value(args)}",
        f"kwargs={_cache_compact_value(kwargs)}",
        f"format={result_format}",
        f"materialize={materialize}",
        f"inline={inline}",
        user_id=user_id,
    )


@contextlib.contextmanager
def bypass_method_cache():
    """Cached methods called inside load fresh and store nothing (read-modify-write paths)."""
    token = _cache_bypass.set(True)
    try:
        yield
    finally:
        _cache_bypass.reset(token)


async def invalidate_cached_method(manager: Any, method: Any, *args, **kwargs) -> None:
    """
    Drop every cached variant of ``method(*args, **kwargs)`` for the caller, after a write.

    Pass the arguments exactly as callers do (same positional/keyword form): they are part of the key.
    """
    scope = method.cache_scope
    if scope is CacheScope.USER:
        user_id = resolve_cache_user_id(manager)
        if user_id is None:
            return  # nothing was cached for this caller
    else:
        user_id = None
    cache = get_cache()
    keys = [
        _method_cache_key(
            scope, method.cache_qualified_name, args, kwargs, user_id,
            result_format=result_format, materialize=materialize, inline=inline,
        )
        for result_format in _RESULT_FORMATS
        for materialize in (0, 1)
        for inline in (0, 1)
    ]
    # Best effort, like every cache write: a failed delete never fails the write it follows.
    await asyncio.gather(*(cache.delete(key) for key in keys), return_exceptions=True)


def ttl_cache_method(ttl_seconds: float = 30, scope: CacheScope = CacheScope.USER):
    """
    Async TTL cache for manager instance methods (bursts and internal re-reads).

    - USER scope keys on the user id from the request context; without one the
      cache is bypassed, so entries are never shared across users.
    - GLOBAL scope is for results that do not depend on the caller.
    - Errors are never cached. Concurrent misses share one call.
    - Place it above @run_as_task: a hit skips the task entirely. When the call
      returns a snapshot of a task that is still running, the snapshot is cached
      for this session only and dropped as soon as the task finishes; session
      dataframe references are never stored (the dataframe can be removed), only
      shared with concurrent calls of the same session.
    - Writes read their base state under ``bypass_method_cache()`` and call
      ``invalidate_cached_method`` once they succeed.
    """

    def decorator(func: Callable[..., Awaitable[Any]]):
        qualified_name = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if _cache_bypass.get():
                return await func(self, *args, **kwargs)
            if scope is CacheScope.USER:
                user_id = resolve_cache_user_id(self)
                if user_id is None:
                    return await func(self, *args, **kwargs)
            else:
                user_id = None

            cache = get_cache()
            # Inline calls (nested inside a running tool/task, e.g. bridge validations) always
            # get the domain result; top-level calls may get a task snapshot or a dataframe
            # reference. Separate keys keep one from ever being served to the other.
            key = _method_cache_key(
                scope, qualified_name, args, kwargs, user_id,
                result_format=_result_format_context.get(),
                materialize=int(not _disable_dataframe_materialization.get()),
                inline=int(_task_management_enabled.get()),
            )

            from config.session_context import SessionContextMissing
            from tools.async_task_manager import add_task_terminal_callback, session_scope_from_manager
            from tools.dataframe_manager import is_dataframe_reference

            try:
                session_scope = session_scope_from_manager(self)
            except SessionContextMissing:
                # Unit tests and calls outside a bound tool scope run uncached.
                return await func(self, *args, **kwargs)
            binding = f"{session_scope.user_id}/{session_scope.mcp_session_id}"

            def _store_policy(value: Any) -> Optional[StorePlan]:
                if not isinstance(value, BaseResult):
                    return StorePlan()
                if value.error:
                    return None
                if value.pending_task is not None:
                    task_id, task_scope = value.pending_task

                    async def _invalidate() -> None:
                        # Only our snapshot: another session may have stored a newer value since.
                        await cache.delete(key, if_tag=task_id)

                    async def _drop_when_task_finishes() -> None:
                        await add_task_terminal_callback(task_id, task_scope, _invalidate)

                    return StorePlan(
                        bound_to=binding,
                        tag=task_id,
                        transform=_strip_per_call_fields,
                        after_store=_drop_when_task_finishes,
                    )
                if is_dataframe_reference(value):
                    return StorePlan(bound_to=binding, store=False, transform=_strip_per_call_fields)
                return StorePlan(transform=_strip_per_call_fields)

            return await cache.get_or_load(
                key,
                lambda: func(self, *args, **kwargs),
                ttl_seconds,
                store_policy=_store_policy,
                binding=binding,
                observer=_accumulate_cache_debug,
            )

        wrapper.cache_scope = scope
        wrapper.cache_qualified_name = qualified_name
        return wrapper

    return decorator
