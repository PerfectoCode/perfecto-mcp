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
    """Keep command contracts offline.

    Contracts are resolved over HTTP and memoized, so the request is stubbed out
    (no contract = element type, error policy and validation fall back to the local
    spec) and the cache is reset on both ends. Use declare_commands to opt in.
    """
    definitions.reset_command_contract_cache()

    async def offline_api_request(*_args, **_kwargs):
        return BaseResult(error="command definitions are not fetched in tests")

    monkeypatch.setattr(definitions, "api_request", offline_api_request)
    yield
    definitions.reset_command_contract_cache()


@pytest.fixture
def declare_commands(monkeypatch, offline_command_definitions):
    """Declare contracts per command_id.

    {command_id: {"mandatory": [...], "optional": [...], "element_type": ..., "error_policy": ...}}
    """

    def declare(declarations: dict[str, dict]) -> None:
        async def fake_fetch(_token, command_id):
            declaration = declarations.get(command_id)
            if declaration is None:
                return None
            mandatory = frozenset(declaration.get("mandatory", ()))
            parameters = {
                name: definitions.ParameterContract(
                    name=name,
                    data_type=spec.get("data_type"),
                    data_sources=frozenset(spec.get("data_sources", ("CONSTANT", "VARIABLE"))),
                    mandatory=name in mandatory,
                    default_value=spec.get("default_value"),
                    allowed_values=tuple(spec.get("allowed_values", ())),
                    minimum=spec.get("minimum"),
                    maximum=spec.get("maximum"),
                )
                for name, spec in (declaration.get("parameters") or {}).items()
            }
            return definitions.CommandContract(
                command_id=command_id,
                mandatory=mandatory,
                optional=frozenset(declaration.get("optional", ())),
                element_type=declaration.get("element_type"),
                error_policy=declaration.get("error_policy"),
                parameters=parameters,
            )

        definitions.reset_command_contract_cache()
        monkeypatch.setattr(definitions, "_fetch_command_contract", fake_fetch)

    return declare
