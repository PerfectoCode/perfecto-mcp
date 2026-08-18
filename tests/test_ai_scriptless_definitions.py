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

import asyncio

import httpx

from models.result import BaseResult
from tools.ai_scriptless import definitions
from tools.ai_scriptless.definitions import (
    declared_parameters,
    empty_mandatory_note,
    validate_argument_names,
)

USER_ACTION = (frozenset({"action"}), frozenset({"handsetId"}))


class TestValidateArgumentNames:
    def test_accepts_declared_names(self):
        assert validate_argument_names(
            "ai_user-action", {"action": "Tap", "handsetId": "DUT"}, USER_ACTION
        ) is None

    def test_rejects_undeclared_name_with_suggestion(self):
        error = validate_argument_names("ai_user-action", {"actions": "Tap"}, USER_ACTION)
        assert "'actions' (did you mean 'action'?)" in error
        assert "Declared parameter names: action, handsetId" in error
        assert "mandatory: action" in error

    def test_reports_undeclared_name_without_close_match(self):
        error = validate_argument_names("ai_user-action", {"xyz": "Tap"}, USER_ACTION)
        assert "'xyz'" in error
        assert "did you mean" not in error

    def test_accepts_alias_in_either_direction(self):
        # The spec canonicalizes waitDuration to duration; either name may be declared.
        assert validate_argument_names("wait", {"duration": "3"}, (frozenset({"waitDuration"}), frozenset())) is None
        assert validate_argument_names("wait", {"waitDuration": "3"}, (frozenset({"duration"}), frozenset())) is None

    def test_fails_open_without_declared_parameters(self):
        assert validate_argument_names("ai_user-action", {"anything": "value"}, None) is None

    def test_accepts_variable_data_source_form(self):
        assert validate_argument_names(
            "ai_user-action",
            {"action": {"data_source": "VARIABLE", "value": "loginStep"}},
            USER_ACTION,
        ) is None


class TestEmptyMandatoryNote:
    def test_notes_mandatory_left_empty_by_spec_default(self):
        note = empty_mandatory_note("ai_user-action", None, USER_ACTION)
        assert "Mandatory parameter(s) left empty on 'ai_user-action': action" in note

    def test_no_note_when_mandatory_is_provided(self):
        assert empty_mandatory_note("ai_user-action", {"action": "Tap"}, USER_ACTION) is None

    def test_blank_string_counts_as_empty(self):
        note = empty_mandatory_note("ai_user-action", {"action": "   "}, USER_ACTION)
        assert "action" in note

    def test_variable_binding_counts_as_provided(self):
        assert empty_mandatory_note(
            "ai_user-action",
            {"action": {"data_source": "VARIABLE", "value": "loginStep"}},
            USER_ACTION,
        ) is None

    def test_no_note_without_declared_parameters(self):
        assert empty_mandatory_note("ai_user-action", None, None) is None


class TestDeclaredParameters:
    def test_parses_and_memoizes_definitions(self, perfecto_token, monkeypatch):
        calls: list = []

        async def fake_api_request(_token, _method, endpoint=None, result_formatter=None, **kwargs):
            calls.append(kwargs.get("json"))
            return BaseResult(result=result_formatter({
                "definitions": [{
                    "commandId": "ai_validation",
                    "data": {
                        "display": {"name": "AI Validation"},
                        "mandatoryParameters": [{"name": "validation"}],
                        "optionalParameters": [{"name": "handsetId"}],
                    },
                }],
            }, None))

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        first = asyncio.run(declared_parameters(perfecto_token, "ai_validation"))
        second = asyncio.run(declared_parameters(perfecto_token, "ai_validation"))

        assert first == (frozenset({"validation"}), frozenset({"handsetId"}))
        assert second == first
        assert calls == [{"commandIds": ["ai_validation"]}]

    def test_definition_without_parameters_is_treated_as_unknown(self, perfecto_token, monkeypatch):
        async def fake_api_request(_token, _method, endpoint=None, result_formatter=None, **kwargs):
            return BaseResult(result=result_formatter({
                "definitions": [{
                    "commandId": "wait",
                    "data": {"display": {"name": "Wait"}, "mandatoryParameters": [], "optionalParameters": []},
                }],
            }, None))

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        assert asyncio.run(declared_parameters(perfecto_token, "wait")) is None

    def test_fails_open_on_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="Invalid credentials")

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        assert asyncio.run(declared_parameters(perfecto_token, "ai_validation")) is None

    def test_fails_open_on_http_exception(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            request = httpx.Request("POST", "https://demo.perfectomobile.com/definitions")
            raise httpx.HTTPStatusError(
                "not found", request=request, response=httpx.Response(404, request=request)
            )

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        assert asyncio.run(declared_parameters(perfecto_token, "ai_validation")) is None

    def test_no_token_returns_none(self):
        assert asyncio.run(declared_parameters(None, "ai_validation")) is None
