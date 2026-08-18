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

import pytest

from config.token import PerfectoToken
from models.result import BaseResult
from tools.ai_scriptless import definitions


@pytest.fixture
def perfecto_token() -> PerfectoToken:
    return PerfectoToken("test-token", "demo")


@pytest.fixture(autouse=True)
def offline_command_definitions(monkeypatch):
    """Keep cmd_arguments validation offline.

    Validation resolves declared parameters over HTTP and memoizes them, so the
    request is stubbed out (no declared parameters = validation fails open) and the
    cache is reset on both ends. Use declare_command_parameters to opt into validation.
    """
    definitions.reset_declared_parameters_cache()

    async def offline_api_request(*_args, **_kwargs):
        return BaseResult(error="command definitions are not fetched in tests")

    monkeypatch.setattr(definitions, "api_request", offline_api_request)
    yield
    definitions.reset_declared_parameters_cache()


@pytest.fixture
def declare_command_parameters(monkeypatch, offline_command_definitions):
    """Declare parameters per command_id: {command_id: (mandatory, optional)}."""

    def declare(declarations: dict[str, tuple[list[str], list[str]]]) -> None:
        async def fake_fetch(_token, command_id):
            declaration = declarations.get(command_id)
            if declaration is None:
                return None
            mandatory, optional = declaration
            return frozenset(mandatory), frozenset(optional)

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "_fetch_declared_parameters", fake_fetch)

    return declare
