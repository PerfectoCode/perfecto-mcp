"""
Copyright 2025 Perforce Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from config.auth import PERFECTO_USER_CONFIG_STATE_ATTR
from config.token import PerfectoToken


@pytest.fixture
def perfecto_token() -> PerfectoToken:
    return PerfectoToken("test-token", "demo")


def make_ctx(token: Optional[PerfectoToken] = None, **user_config: Any) -> SimpleNamespace:
    """
    Minimal Context stand-in carrying the per-session user config.

    Mirrors what AppRuntime.configure_context hydrates at runtime, so managers
    resolve their token from the context in tests the same way they do in
    production.
    """
    config: dict[str, Any] = dict(user_config)
    if token is not None:
        config["token"] = token
        config.setdefault("cloud_name", token.cloud_name)

    request_context = SimpleNamespace(request=None)
    setattr(request_context, PERFECTO_USER_CONFIG_STATE_ATTR, config)
    return SimpleNamespace(request_context=request_context)


@pytest.fixture
def perfecto_ctx(perfecto_token: PerfectoToken) -> SimpleNamespace:
    return make_ctx(perfecto_token)
