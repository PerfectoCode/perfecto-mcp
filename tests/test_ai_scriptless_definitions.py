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
import pytest

from models.result import BaseResult
from tools.ai_scriptless import definitions
from tools.ai_scriptless.commands import get_command_spec
from tools.ai_scriptless.elements import new_empty_script
from tools.ai_scriptless.variables import add_script_variable
from tools.ai_scriptless.definitions import (
    ParameterContract,
    coerce_argument_value,
    restriction_allowed_values,
    restriction_range,
    validate_argument_values,
    validate_variable_bindings,
    CommandContract,
    command_contract,
    empty_mandatory_note,
    validate_argument_names,
)

USER_ACTION = CommandContract(
    command_id="ai_user-action",
    mandatory=frozenset({"handsetId", "action"}),
    optional=frozenset({"reasoning"}),
    element_type="Action",
    error_policy="ABORT",
)


def _definition(command_id: str, data: dict) -> dict:
    return {"definitions": [{"commandId": command_id, "data": data}]}


class TestValidateArgumentNames:
    def test_accepts_declared_names(self):
        assert validate_argument_names(
            "ai_user-action", {"action": "Tap", "handsetId": "DUT"}, USER_ACTION
        ) is None

    def test_rejects_undeclared_name_with_suggestion(self):
        error = validate_argument_names("ai_user-action", {"actions": "Tap"}, USER_ACTION)
        assert "'actions' (did you mean 'action'?)" in error
        assert "Declared parameter names: action, handsetId, reasoning" in error
        assert "mandatory: action, handsetId" in error

    def test_reports_undeclared_name_without_close_match(self):
        error = validate_argument_names("ai_user-action", {"xyz": "Tap"}, USER_ACTION)
        assert "'xyz'" in error
        assert "did you mean" not in error

    def test_accepts_alias_in_either_direction(self):
        # The spec canonicalizes waitDuration to duration; either name may be declared.
        declared_alias = CommandContract("wait", mandatory=frozenset({"waitDuration"}))
        declared_canonical = CommandContract("wait", mandatory=frozenset({"duration"}))
        assert validate_argument_names("wait", {"duration": "3"}, declared_alias) is None
        assert validate_argument_names("wait", {"waitDuration": "3"}, declared_canonical) is None

    def test_fails_open_without_contract(self):
        assert validate_argument_names("ai_user-action", {"anything": "value"}, None) is None

    def test_fails_open_when_contract_declares_no_parameter(self):
        contract = CommandContract("comment", element_type="Action")
        assert validate_argument_names("comment", {"anything": "value"}, contract) is None

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
        # handsetId is bound to the DUT variable by the spec, so it is not empty.
        assert "handsetId" not in note

    def test_notes_mandatory_the_spec_does_not_seed(self):
        # checkpoint_text declares content as mandatory; the spec only injects handsetId.
        contract = CommandContract(
            "checkpoint_text",
            mandatory=frozenset({"handsetId", "content"}),
            element_type="Validation",
        )
        note = empty_mandatory_note("checkpoint_text", None, contract)
        assert "content" in note

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

    def test_no_note_without_contract(self):
        assert empty_mandatory_note("ai_user-action", None, None) is None


class TestCommandContractParsing:
    @staticmethod
    def _stub_api(monkeypatch, payload: dict, calls: list | None = None):
        async def fake_api_request(_token, _method, endpoint=None, result_formatter=None, **kwargs):
            if calls is not None:
                calls.append(kwargs.get("json"))
            return BaseResult(result=result_formatter(payload, None))

        definitions.reset_command_contract_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

    def test_parses_parameters_type_and_error_policy(self, perfecto_token, monkeypatch):
        self._stub_api(monkeypatch, _definition("ai_validation", {
            "display": {"name": "AI Validation"},
            "type": "VALIDATION",
            "errorPolicy": "IGNORE",
            "mandatoryParameters": [{"name": "handsetId"}, {"name": "validation"}],
            "optionalParameters": [{"name": "reasoning"}],
        }))

        contract = asyncio.run(command_contract(perfecto_token, "ai_validation"))

        assert contract.element_type == "Validation"
        assert contract.error_policy == "IGNORE"
        assert contract.mandatory == frozenset({"handsetId", "validation"})
        assert contract.optional == frozenset({"reasoning"})
        assert contract.declared_names == frozenset({"handsetId", "validation", "reasoning"})

    def test_maps_action_type(self, perfecto_token, monkeypatch):
        self._stub_api(monkeypatch, _definition("ai_user-action", {
            "type": "ACTION",
            "errorPolicy": "ABORT",
            "mandatoryParameters": [{"name": "action"}],
        }))

        contract = asyncio.run(command_contract(perfecto_token, "ai_user-action"))

        assert contract.element_type == "Action"
        assert contract.error_policy == "ABORT"

    def test_null_error_policy_is_left_undeclared(self, perfecto_token, monkeypatch):
        # wait declares errorPolicy null: the local default has to fill in.
        self._stub_api(monkeypatch, _definition("wait", {
            "type": "ACTION",
            "errorPolicy": None,
            "mandatoryParameters": [{"name": "duration"}],
        }))

        contract = asyncio.run(command_contract(perfecto_token, "wait"))

        assert contract.element_type == "Action"
        assert contract.error_policy is None

    def test_unknown_type_and_policy_are_left_undeclared(self, perfecto_token, monkeypatch):
        self._stub_api(monkeypatch, _definition("odd", {
            "type": "SOMETHING_NEW",
            "errorPolicy": "RETRY",
            "mandatoryParameters": [{"name": "x"}],
        }))

        contract = asyncio.run(command_contract(perfecto_token, "odd"))

        assert contract.element_type is None
        assert contract.error_policy is None

    def test_contract_without_parameters_still_carries_type(self, perfecto_token, monkeypatch):
        self._stub_api(monkeypatch, _definition("wait", {
            "type": "ACTION",
            "mandatoryParameters": [],
            "optionalParameters": [],
        }))

        contract = asyncio.run(command_contract(perfecto_token, "wait"))

        assert contract.declared_names == frozenset()
        assert contract.element_type == "Action"

    def test_memoizes_per_command(self, perfecto_token, monkeypatch):
        calls: list = []
        self._stub_api(monkeypatch, _definition("wait", {
            "type": "ACTION",
            "mandatoryParameters": [{"name": "duration"}],
        }), calls)

        first = asyncio.run(command_contract(perfecto_token, "wait"))
        second = asyncio.run(command_contract(perfecto_token, "wait"))

        assert first == second
        assert calls == [{"commandIds": ["wait"]}]

    def test_ignores_definitions_for_other_commands(self, perfecto_token, monkeypatch):
        self._stub_api(monkeypatch, _definition("other", {"type": "ACTION"}))

        assert asyncio.run(command_contract(perfecto_token, "wait")) is None


class TestCommandContractFailsOpen:
    def test_fails_open_on_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="Invalid credentials")

        definitions.reset_command_contract_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        assert asyncio.run(command_contract(perfecto_token, "ai_validation")) is None

    def test_fails_open_on_http_exception(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            request = httpx.Request("POST", "https://demo.perfectomobile.com/definitions")
            raise httpx.HTTPStatusError(
                "not found", request=request, response=httpx.Response(404, request=request)
            )

        definitions.reset_command_contract_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)

        assert asyncio.run(command_contract(perfecto_token, "ai_validation")) is None

    def test_no_token_returns_none(self):
        assert asyncio.run(command_contract(None, "ai_validation")) is None

    def test_no_command_id_returns_none(self, perfecto_token):
        assert asyncio.run(command_contract(perfecto_token, "")) is None


class TestDataTableBindingCountsAsValue:
    def test_bound_datatable_column_is_not_empty(self):
        contract = CommandContract(
            "checkpoint_text",
            mandatory=frozenset({"content"}),
            element_type="Validation",
        )
        assert empty_mandatory_note(
            "checkpoint_text",
            {"content": {"data_source": "DATATABLE", "table_name": "T", "column": "c"}},
            contract,
        ) is None

    def test_unbound_datatable_is_empty(self):
        contract = CommandContract(
            "checkpoint_text",
            mandatory=frozenset({"content"}),
            element_type="Validation",
        )
        note = empty_mandatory_note(
            "checkpoint_text", {"content": {"data_source": "DATATABLE"}}, contract
        )
        assert "content" in note


WAIT_DURATION = ParameterContract(
    name="duration", data_type="INTEGER", data_sources=frozenset({"CONSTANT", "VARIABLE", "DATATABLE"}),
    mandatory=True, minimum=0.0, maximum=3600.0,
)
CHECKPOINT_CONTEXT = ParameterContract(
    name="context", data_type="STRING", data_sources=frozenset({"CONSTANT", "VARIABLE", "DATATABLE"}),
    default_value="all", allowed_values=("all", "body", "lowerPanel", "upperPanel"),
)
AI_ACTION = ParameterContract(
    name="action", data_type="STRING", data_sources=frozenset({"CONSTANT", "VARIABLE"}), mandatory=True,
)
AI_REASONING = ParameterContract(
    name="reasoning", data_type="BOOLEAN", data_sources=frozenset({"CONSTANT", "VARIABLE"}),
    default_value=False,
)

WAIT = CommandContract(
    "wait", mandatory=frozenset({"duration"}), element_type="Action",
    parameters={"duration": WAIT_DURATION},
)
USER_ACTION_TYPED = CommandContract(
    "ai_user-action",
    mandatory=frozenset({"action"}),
    optional=frozenset({"reasoning"}),
    element_type="Action",
    parameters={"action": AI_ACTION, "reasoning": AI_REASONING},
)
CHECKPOINT = CommandContract(
    "checkpoint_text", optional=frozenset({"context"}), element_type="Validation",
    parameters={"context": CHECKPOINT_CONTEXT},
)


class TestRestrictionParsing:
    def test_parses_enumeration_values(self):
        param = {"restriction": {"type": "ENUMERATION", "value": "primary,native,camera"}}
        assert restriction_allowed_values(param) == ("primary", "native", "camera")

    def test_prefers_value_over_label(self):
        # The label can be truncated ("all,body,,"); value carries the real list.
        param = {"restriction": {"type": "COMBO", "value": "all,body,link", "label": "all,body,,"}}
        assert restriction_allowed_values(param) == ("all", "body", "link")

    def test_ignores_non_enumeration_restrictions(self):
        assert restriction_allowed_values({"restriction": {"type": "RANGE"}}) == ()


FAIL_CRITERIA_PARAM = {
    "name": "failCriteria",
    "dataType": "STRING",
    "maxOccurrences": 10,
    "dataSources": ["CONSTANT"],
    "restriction": {
        "type": "ENUMERATION",
        "source": "LITERAL",
        "value": "style,missing,addition,error,device,value,pixel_difference,uncategorized",
        "label": "STYLE,MISSING,ADDITION,ERROR,Device,VALUE,Pixel difference,Uncategorized",
    },
}


class TestRenamedParameterLabel:
    """The editor labels ai_user-action's `action` "Prompt" (D5)."""

    def test_reports_the_label_the_editor_shows(self):
        assert definitions.parameter_label("ai_user-action", "action", "Action") == "Prompt"

    def test_other_parameters_keep_the_declared_label(self):
        assert definitions.parameter_label("ai_validation", "validation", "Validation") == "Validation"
        assert definitions.parameter_label("ai_user-action", "handsetId", "Device ID") == "Device ID"
        assert definitions.parameter_label(None, None, None) is None

    def test_the_editor_label_resolves_to_the_parameter(self):
        # Typing into "Prompt" stores `action`, so the name read on screen is accepted as a key.
        spec = get_command_spec("ai_user-action")
        assert spec.normalize_argument_names({"Prompt": "Open Settings"}) == {"action": "Open Settings"}
        assert spec.normalize_argument_names({"prompt": "Open Settings"}) == {"action": "Open Settings"}

    def test_the_alias_passes_name_validation(self):
        contract = CommandContract("ai_user-action", mandatory=frozenset({"action"}))
        assert validate_argument_names("ai_user-action", {"Prompt": "x"}, contract) is None


class TestUIPersistedEnumeration:
    """failCriteria's stored values drifted from the declaration in two places (D12)."""

    def test_reports_the_spelling_the_ui_stores(self):
        assert restriction_allowed_values(FAIL_CRITERIA_PARAM, "ai_visual-comparison") == (
            "device", "style", "value", "missing", "moved",
            "addition", "error", "uncategorized", "pixelDifference",
        )

    def test_declared_values_stand_for_other_commands(self):
        # The override is keyed by command and parameter: nothing else changes.
        assert "pixel_difference" in restriction_allowed_values(FAIL_CRITERIA_PARAM, "checkpoint_text")
        assert "pixel_difference" in restriction_allowed_values(FAIL_CRITERIA_PARAM)

    def test_only_two_options_differ_from_the_declaration(self):
        # Why this is a constant and not a transformation: pixel_difference is stored
        # camelCased, and moved is offered by the editor but declared nowhere.
        declared = set(restriction_allowed_values(FAIL_CRITERIA_PARAM))
        stored = set(restriction_allowed_values(FAIL_CRITERIA_PARAM, "ai_visual-comparison"))
        assert stored - declared == {"pixelDifference", "moved"}
        assert declared - stored == {"pixel_difference"}

    @pytest.mark.parametrize("supplied, persisted", [
        ("pixel_difference", "pixelDifference"),    # the declared value
        ("Pixel difference", "pixelDifference"),    # the declared label
        ("pixelDifference", "pixelDifference"),     # what the editor itself stores
        ("PIXEL_DIFFERENCE", "pixelDifference"),
        ("style", "style"),
        ("STYLE", "style"),                         # the declared label's casing
        ("Moved", "moved"),                         # UI-only, absent from the declaration
    ])
    def test_every_spelling_coerces_to_what_the_ui_stores(self, supplied, persisted):
        parameter = definitions._parse_parameter_contract(
            FAIL_CRITERIA_PARAM, mandatory=True, command_id="ai_visual-comparison",
        )
        assert coerce_argument_value(supplied, parameter) == persisted
        assert validate_argument_values(
            "ai_visual-comparison",
            {"failCriteria": supplied},
            CommandContract("ai_visual-comparison", parameters={"failCriteria": parameter}),
        ) is None

    def test_still_rejects_a_value_in_neither_vocabulary(self):
        parameter = definitions._parse_parameter_contract(
            FAIL_CRITERIA_PARAM, mandatory=True, command_id="ai_visual-comparison",
        )
        error = validate_argument_values(
            "ai_visual-comparison",
            {"failCriteria": "pixel_diff"},
            CommandContract("ai_visual-comparison", parameters={"failCriteria": parameter}),
        )
        assert error is not None and "pixel_diff" in error

    def test_relaxed_match_does_not_merge_declared_values(self):
        # report declares all,all-on-error: dropping punctuation must not make them collide.
        param = {"name": "report", "restriction": {
            "type": "ENUMERATION", "value": "all,all-on-error,screenshot",
        }}
        parameter = definitions._parse_parameter_contract(param, mandatory=False)
        assert coerce_argument_value("all", parameter) == "all"
        assert coerce_argument_value("all on error", parameter) == "all-on-error"
        assert coerce_argument_value("allonerror", parameter) == "all-on-error"

    def test_parses_range_bounds(self):
        param = {"restriction": {"type": "RANGE", "range": {"minValue": 0.0, "maxValue": 3600.0}}}
        assert restriction_range(param) == (0.0, 3600.0)

    def test_ignores_range_of_non_range_restriction(self):
        param = {"restriction": {"type": "NONE", "range": {"minValue": -2147483648, "maxValue": 2147483647}}}
        assert restriction_range(param) == (None, None)


class TestCoerceArgumentValue:
    def test_stringifies_integer(self):
        # UI-authored scripts persist INTEGER constants as strings ("2", not 2).
        assert coerce_argument_value(2, WAIT_DURATION) == "2"
        assert coerce_argument_value(2.0, WAIT_DURATION) == "2"

    def test_keeps_string_integer_as_is(self):
        assert coerce_argument_value("2", WAIT_DURATION) == "2"

    def test_stringifies_boolean(self):
        assert coerce_argument_value(True, AI_REASONING) == "true"
        assert coerce_argument_value(False, AI_REASONING) == "false"

    def test_snaps_enumeration_to_declared_casing(self):
        assert coerce_argument_value("BODY", CHECKPOINT_CONTEXT) == "body"

    def test_leaves_unknown_enumeration_value_untouched(self):
        # Validation reports it; coercion does not silently rewrite it.
        assert coerce_argument_value("sidebar", CHECKPOINT_CONTEXT) == "sidebar"

    def test_no_op_without_parameter(self):
        assert coerce_argument_value(2, None) == 2


class TestValidateArgumentValues:
    def test_accepts_valid_values(self):
        assert validate_argument_values("wait", {"duration": "30"}, WAIT) is None
        assert validate_argument_values("checkpoint_text", {"context": "body"}, CHECKPOINT) is None

    def test_rejects_non_numeric_integer(self):
        error = validate_argument_values("wait", {"duration": "soon"}, WAIT)
        assert "'duration' expects a number (INTEGER)" in error

    def test_rejects_value_above_range(self):
        error = validate_argument_values("wait", {"duration": 5000}, WAIT)
        assert "'duration' must be within 0..3600" in error

    def test_rejects_value_below_range(self):
        error = validate_argument_values("wait", {"duration": -1}, WAIT)
        assert "must be within 0..3600" in error

    def test_accepts_range_bounds(self):
        assert validate_argument_values("wait", {"duration": 0}, WAIT) is None
        assert validate_argument_values("wait", {"duration": 3600}, WAIT) is None

    def test_rejects_undeclared_enumeration_value(self):
        error = validate_argument_values("checkpoint_text", {"context": "sidebar"}, CHECKPOINT)
        assert "must be one of all, body, lowerPanel, upperPanel" in error

    def test_accepts_enumeration_value_in_any_casing(self):
        assert validate_argument_values("checkpoint_text", {"context": "BODY"}, CHECKPOINT) is None

    def test_rejects_non_boolean(self):
        error = validate_argument_values("ai_user-action", {"reasoning": "maybe"}, USER_ACTION_TYPED)
        assert "'reasoning' expects a boolean" in error

    def test_accepts_boolean_spellings(self):
        for value in (True, False, "true", "FALSE", "1", "no"):
            assert validate_argument_values(
                "ai_user-action", {"reasoning": value}, USER_ACTION_TYPED
            ) is None

    def test_rejects_data_source_the_parameter_does_not_accept(self):
        # ai_user-action's action declares CONSTANT and VARIABLE only.
        error = validate_argument_values(
            "ai_user-action",
            {"action": {"data_source": "DATATABLE", "table_name": "T", "column": "c"}},
            USER_ACTION_TYPED,
        )
        assert "does not accept data_source DATATABLE" in error
        assert "accepted: CONSTANT, VARIABLE" in error

    def test_accepts_declared_data_source(self):
        assert validate_argument_values(
            "wait",
            {"duration": {"data_source": "DATATABLE", "table_name": "T", "column": "c"}},
            WAIT,
        ) is None

    def test_does_not_check_values_behind_a_binding(self):
        # A variable's value is only known at execution time.
        assert validate_argument_values(
            "wait", {"duration": {"data_source": "VARIABLE", "value": "secs"}}, WAIT
        ) is None

    def test_reports_every_offending_argument(self):
        error = validate_argument_values(
            "checkpoint_text", {"context": "sidebar"}, CHECKPOINT
        )
        assert error.startswith("Invalid cmd_arguments for command 'checkpoint_text':")
        assert "get_command_definitions" in error

    def test_fails_open_without_parameter_contracts(self):
        contract = CommandContract("wait", mandatory=frozenset({"duration"}))
        assert validate_argument_values("wait", {"duration": "nonsense"}, contract) is None

    def test_ignores_alias_names(self):
        assert validate_argument_values("wait", {"waitDuration": 5000}, WAIT) is not None


def _script_with_variables() -> dict:
    script = new_empty_script()
    add_script_variable(script, "waitSecs", "string", "3")
    add_script_variable(script, "waitSecsNum", "number", 3)
    return script


class TestValidateVariableBindings:
    def test_accepts_variable_of_matching_type(self):
        assert validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "VARIABLE", "value": "waitSecsNum"}},
            WAIT,
            _script_with_variables(),
        ) is None

    def test_rejects_variable_of_another_type(self):
        # The case the UI refuses: a string variable on a Number parameter.
        error = validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "VARIABLE", "value": "waitSecs"}},
            WAIT,
            _script_with_variables(),
        )
        assert "'duration' is declared INTEGER but variable 'waitSecs' is a string" in error
        assert "only binds a variable of the matching type" in error
        assert "waitSecsNum (number)" in error

    def test_rejects_undefined_variable(self):
        error = validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "VARIABLE", "value": "nope"}},
            WAIT,
            _script_with_variables(),
        )
        assert "variable 'nope', which this test does not define" in error
        assert "add_test_variable" in error

    def test_lists_defined_values_with_their_types(self):
        error = validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "VARIABLE", "value": "nope"}},
            WAIT,
            _script_with_variables(),
        )
        assert "DUT (device)" in error
        assert "waitSecs (string)" in error
        assert "waitSecsNum (number)" in error

    def test_rejects_missing_variable_name(self):
        error = validate_variable_bindings(
            "wait", {"duration": {"data_source": "VARIABLE"}}, WAIT, _script_with_variables()
        )
        assert "no variable name was given" in error

    def test_accepts_dut_for_a_handset_parameter(self):
        # DUT lives in script.parameters[], not variables[].
        contract = CommandContract(
            "touch_tap",
            mandatory=frozenset({"handsetId"}),
            parameters={"handsetId": ParameterContract(
                name="handsetId", data_type="HANDSET",
                data_sources=frozenset({"CONSTANT", "VARIABLE", "DATATABLE"}), mandatory=True,
            )},
        )
        assert validate_variable_bindings(
            "touch_tap",
            {"handsetId": {"data_source": "VARIABLE", "value": "DUT"}},
            contract,
            _script_with_variables(),
        ) is None

    def test_rejects_string_variable_on_a_handset_parameter(self):
        contract = CommandContract(
            "touch_tap",
            mandatory=frozenset({"handsetId"}),
            parameters={"handsetId": ParameterContract(
                name="handsetId", data_type="HANDSET", mandatory=True,
            )},
        )
        error = validate_variable_bindings(
            "touch_tap",
            {"handsetId": {"data_source": "VARIABLE", "value": "waitSecs"}},
            contract,
            _script_with_variables(),
        )
        assert "declared HANDSET but variable 'waitSecs' is a string" in error

    def test_only_checks_existence_for_unmapped_parameter_types(self):
        # checkpoint_text declares an 'ocr' parameter of type PROPERTY.
        contract = CommandContract(
            "checkpoint_text",
            optional=frozenset({"ocr"}),
            parameters={"ocr": ParameterContract(name="ocr", data_type="PROPERTY")},
        )
        assert validate_variable_bindings(
            "checkpoint_text",
            {"ocr": {"data_source": "VARIABLE", "value": "waitSecs"}},
            contract,
            _script_with_variables(),
        ) is None

    def test_ignores_constant_and_datatable_arguments(self):
        script = _script_with_variables()
        assert validate_variable_bindings("wait", {"duration": "3"}, WAIT, script) is None
        assert validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "DATATABLE", "table_name": "T", "column": "c"}},
            WAIT,
            script,
        ) is None

    def test_fails_open_without_parameter_contracts(self):
        contract = CommandContract("wait", mandatory=frozenset({"duration"}))
        assert validate_variable_bindings(
            "wait",
            {"duration": {"data_source": "VARIABLE", "value": "nope"}},
            contract,
            _script_with_variables(),
        ) is None

    def test_normalizes_alias_before_checking(self):
        error = validate_variable_bindings(
            "wait",
            {"waitDuration": {"data_source": "VARIABLE", "value": "waitSecs"}},
            WAIT,
            _script_with_variables(),
        )
        assert "'duration' is declared INTEGER" in error


class TestErrorPolicyCoverage:
    """The legacy IDE documents five policies; all of them must survive parsing."""

    @staticmethod
    def _contract(monkeypatch, perfecto_token, policy):
        async def fake_api_request(_token, _method, endpoint=None, result_formatter=None, **kwargs):
            return BaseResult(result=result_formatter(_definition("cmd", {
                "type": "ACTION",
                "errorPolicy": policy,
                "mandatoryParameters": [{"name": "x"}],
            }), None))

        definitions.reset_command_contract_cache()
        monkeypatch.setattr(definitions, "api_request", fake_api_request)
        return asyncio.run(command_contract(perfecto_token, "cmd"))

    def test_keeps_every_documented_policy(self, perfecto_token, monkeypatch):
        for policy in ("ABORT", "IGNORE", "BREAK", "CONTINUE", "CATCH"):
            contract = self._contract(monkeypatch, perfecto_token, policy)
            assert contract.error_policy == policy

    def test_still_drops_an_unknown_policy(self, perfecto_token, monkeypatch):
        assert self._contract(monkeypatch, perfecto_token, "RETRY").error_policy is None


CONCAT_VALUE = ParameterContract(
    name="value", data_type="STRING", data_sources=frozenset({"CONSTANT", "VARIABLE", "DATATABLE"}),
    mandatory=True, min_occurrences=2, max_occurrences=99,
)
CONCAT = CommandContract(
    "text_concat", mandatory=frozenset({"value"}), element_type="Action",
    parameters={"value": CONCAT_VALUE},
)


class TestOccurrenceValidation:
    def test_accepts_a_list_within_bounds(self):
        assert validate_argument_values("text_concat", {"value": ["a", "b", "c"]}, CONCAT) is None

    def test_rejects_fewer_values_than_required(self):
        error = validate_argument_values("text_concat", {"value": "a"}, CONCAT)
        assert "'value' needs at least 2 values" in error

    def test_rejects_more_values_than_allowed(self):
        capped = CommandContract(
            "cmd", parameters={"x": ParameterContract(name="x", max_occurrences=2)}
        )
        error = validate_argument_values("cmd", {"x": ["a", "b", "c"]}, capped)
        assert "'x' accepts at most 2 value(s), got 3" in error

    def test_validates_every_occurrence(self):
        numbers = CommandContract("cmd", parameters={"n": ParameterContract(
            name="n", data_type="INTEGER", minimum=0.0, maximum=10.0, max_occurrences=5,
        )})
        error = validate_argument_values("cmd", {"n": [1, 99]}, numbers)
        assert "must be within 0..10" in error

    def test_single_value_parameter_is_unaffected(self):
        assert validate_argument_values("wait", {"duration": 30}, WAIT) is None

    def test_is_multivalued_reflects_max_occurrences(self):
        assert CONCAT_VALUE.is_multivalued is True
        assert WAIT_DURATION.is_multivalued is False
