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

from formatters.ai_scriptless import (
    _command_id,
    _command_step_display_name,
    _definitions_map,
    _step_display_name,
    command_selection_policy_info,
    format_ai_scriptless_tests,
    format_ai_scriptless_tests_filter_values,
    format_command_catalog,
    format_command_definitions,
    format_step_detail,
    format_snapshots_list,
    format_test_structure,
    format_test_variables,
)
from tools.ai_scriptless_script import (
    build_flow_element,
    build_if_statement,
    build_logical_step,
    new_empty_script,
)


def _ai_validation_command_definition() -> dict:
    return {
        "commandId": "ai_validation",
        "name": "AI Validation",
        "data": {
            "display": {"name": "AI Validation"},
            "mandatoryParameters": [
                {
                    "name": "validation",
                    "display": {
                        "name": "Validation",
                        "editorLevel": "PUBLIC",
                        "inReport": True,
                    },
                },
            ],
            "optionalParameters": [
                {
                    "name": "handsetId",
                    "display": {
                        "name": "Device ID",
                        "editorLevel": "PUBLIC",
                        "inReport": False,
                    },
                },
            ],
        },
    }


def _comment_command_definition() -> dict:
    return {
        "commandId": "comment",
        "name": "Comment",
        "data": {
            "display": {"name": "Comment"},
            "mandatoryParameters": [
                {
                    "name": "text",
                    "display": {
                        "name": "Text",
                        "editorLevel": "PUBLIC",
                        "inReport": True,
                    },
                },
            ],
        },
    }


def _tree_api_payload() -> dict:
    script = new_empty_script()
    tap = build_flow_element("ai_user-action", {"action": "Tap login"})
    tap["uuid"] = "ignored-in-formatter"
    group = build_logical_step("Setup")
    group["flowElements"] = [build_flow_element("comment", {"text": "inside group"})]
    condition = build_if_statement("Check x")
    condition["branches"][0]["flowElements"] = [
        build_flow_element("ai_validation", {"validation": "OK"}),
    ]
    script["flowElements"] = [tap, group, condition]
    return {
        "script": script,
        "commandDefinitions": [
            _comment_command_definition(),
        ],
    }


def _tests_tree_response() -> dict:
    return {
        "items": [
            {
                "visibility": "PRIVATE",
                "items": [
                    {
                        "type": "CONTAINER",
                        "items": [
                            {
                                "type": "SIMPLE",
                                "key": "PRIVATE:My Folder/Login.xml",
                                "name": "Login.xml",
                                "createdBy": "alice",
                                "modifiedBy": "bob",
                                "creationTime": {"formatted": "2024-01-01"},
                                "modificationTime": {"formatted": "2024-01-02"},
                            },
                        ],
                    },
                ],
            },
        ],
    }


class TestCommandSelectionPolicy:
    def test_includes_primary_ai_command_ids(self):
        lines = command_selection_policy_info()
        assert any("ai_user-action" in line for line in lines)
        assert any("ai_validation" in line for line in lines)
        assert any("ai_visual-comparison" in line for line in lines)


class TestFormatTestStructure:
    def test_formats_nested_flow_with_step_paths(self):
        structure = format_test_structure(
            _tree_api_payload(),
            params={"item_key": "PRIVATE:My Folder/Login.xml"},
        )
        assert structure.item_key == "PRIVATE:My Folder/Login.xml"
        assert structure.parameters[0].name == "DUT"
        assert structure.flow_elements[0].name == "Tap login"
        assert structure.flow_elements[0].step_path == "0"
        assert structure.flow_elements[1].name == "Setup"
        assert structure.flow_elements[1].children[0].step_path == "1.0"
        assert structure.flow_elements[2].name == "Condition (Check x)"
        then_branch = structure.flow_elements[2].children[0]
        assert then_branch.type == "Branch"
        assert then_branch.step_path == "2.b0"
        assert then_branch.children[0].step_path == "2.b0.0"
        assert then_branch.children[0].name == "OK"

    def test_uses_definition_display_name_for_non_ai_commands(self):
        structure = format_test_structure(_tree_api_payload())
        comment_step = structure.flow_elements[1].children[0]
        assert comment_step.name == "Comment (Text: inside group)"


class TestCommandStepDisplayName:
    def test_ai_validation_uses_validation_argument_as_display_name(self):
        element = build_flow_element("ai_validation", {"validation": "Screen visible"})
        assert _step_display_name(element, {}) == "Screen visible"

    def test_ai_validation_without_validation_text_uses_base_name_not_device_id(self):
        element = build_flow_element("ai_validation")
        definitions_map = _definitions_map([_ai_validation_command_definition()])
        assert _step_display_name(element, definitions_map) == "AI Validation"
        assert _command_step_display_name(element, "ai_validation", definitions_map) == "AI Validation"

    def test_ai_user_action_without_action_text_uses_base_name_not_device_id(self):
        element = build_flow_element("ai_user-action")
        definitions_map = _definitions_map([
            {
                "commandId": "ai_user-action",
                "name": "AI User Action",
                "data": {
                    "display": {"name": "AI User Action"},
                    "mandatoryParameters": [
                        {
                            "name": "action",
                            "display": {
                                "name": "Action",
                                "editorLevel": "PUBLIC",
                                "inReport": True,
                            },
                        },
                    ],
                    "optionalParameters": [
                        {
                            "name": "handsetId",
                            "display": {
                                "name": "Device ID",
                                "editorLevel": "PUBLIC",
                                "inReport": False,
                            },
                        },
                    ],
                },
            },
        ])
        assert _step_display_name(element, definitions_map) == "AI User Action"

    def test_serializes_public_parameters_like_perfecto_ui(self):
        element = build_flow_element("comment", {"text": "Hello Comment!"})
        definitions_map = _definitions_map([_comment_command_definition()])
        assert _command_step_display_name(element, "comment", definitions_map) == (
            "Comment (Text: Hello Comment!)"
        )

    def test_skips_non_public_parameters(self):
        element = build_flow_element("wait", {"duration": "5"})
        definitions_map = _definitions_map([
            {
                "commandId": "wait",
                "name": "Wait",
                "data": {
                    "display": {"name": "Wait"},
                    "mandatoryParameters": [
                        {
                            "name": "duration",
                            "display": {
                                "name": "Duration",
                                "editorLevel": "PUBLIC",
                                "inReport": True,
                            },
                        },
                    ],
                    "optionalParameters": [
                        {
                            "name": "handsetId",
                            "display": {
                                "name": "Device",
                                "editorLevel": "PRIVATE",
                                "inReport": False,
                            },
                        },
                    ],
                },
            },
        ])
        assert _command_step_display_name(element, "wait", definitions_map) == "Wait (Duration: 5)"

    def test_skips_public_parameters_when_in_report_is_false(self):
        element = build_flow_element("wait", {"duration": "5"})
        definitions_map = _definitions_map([
            {
                "commandId": "wait",
                "name": "Wait",
                "data": {
                    "display": {"name": "Wait"},
                    "mandatoryParameters": [
                        {
                            "name": "duration",
                            "display": {
                                "name": "Duration",
                                "editorLevel": "PUBLIC",
                                "inReport": False,
                            },
                        },
                    ],
                },
            },
        ])
        assert _command_step_display_name(element, "wait", definitions_map) == "Wait"

    def test_returns_base_name_when_public_parameter_has_no_value(self):
        element = build_flow_element("comment")
        definitions_map = _definitions_map([_comment_command_definition()])
        assert _command_step_display_name(element, "comment", definitions_map) == "Comment"

    def test_falls_back_to_base_name_without_definition(self):
        element = build_flow_element("comment", {"text": "orphan"})
        assert _command_step_display_name(element, "comment", {}) is None


class TestFormatCommandCatalog:
    def test_flattens_nested_catalog(self):
        catalog = {
            "name": "Root",
            "children": [
                {
                    "name": "AI",
                    "children": [
                        {
                            "commandId": "ai_user-action",
                            "name": "User action",
                            "path": "/ai/user-action",
                            "status": "GA",
                        },
                    ],
                },
            ],
        }
        entries = format_command_catalog(catalog)
        assert len(entries) == 1
        assert entries[0].command_id == "ai_user-action"
        assert entries[0].category == "AI"


class TestFormatTestVariables:
    def test_formats_secured_and_runtime_variables(self):
        variables = [
            {
                "@type": "Variable",
                "data": {
                    "@type": "StringData",
                    "name": "plain",
                    "value": "hello",
                    "secured": False,
                },
            },
            {
                "@type": "Parameter",
                "data": {
                    "@type": "StringData",
                    "name": "secret",
                    "value": "hidden",
                    "secured": True,
                },
            },
        ]
        formatted = format_test_variables(variables)
        assert formatted[0].name == "plain"
        assert formatted[0].value == "hello"
        assert formatted[0].set_at_runtime is False
        assert formatted[1].value == "<secured>"
        assert formatted[1].set_at_runtime is True

    def test_returns_empty_list_for_invalid_input(self):
        assert format_test_variables(None) == []
        assert format_test_variables("bad") == []


class TestFormatSnapshotsList:
    def test_marks_current_entry_and_sorts_first(self):
        result = format_snapshots_list(
            {
                "snapshots": [
                    {"key": "uuid-1", "createdBy": "alice"},
                    {"key": "<current>", "comment": "latest"},
                ],
            },
            params={"test_id": "PRIVATE:Folder/Test.xml"},
        )
        assert result.test_id == "PRIVATE:Folder/Test.xml"
        assert result.count == 2
        assert result.snapshots[0].is_current is True
        assert result.snapshots[0].key == "<current>"
        assert len(result.notes) >= 1


class TestFormatCommandDefinitions:
    def test_parses_definition_payload(self):
        definitions = format_command_definitions({
            "definitions": [
                {
                    "commandId": "ai_validation",
                    "data": {
                        "display": {"name": "AI validation", "helpText": "Assert with AI"},
                        "mandatoryParameters": [{"name": "validation"}],
                        "optionalParameters": [{"name": "handsetId"}],
                    },
                },
            ],
        })
        assert definitions[0].command_id == "ai_validation"
        assert definitions[0].name == "AI validation"
        assert definitions[0].mandatory_parameters == ["validation"]
        assert definitions[0].optional_parameters == ["handsetId"]


class TestFormatTestsTree:
    def test_extracts_filter_values(self):
        values = format_ai_scriptless_tests_filter_values(_tests_tree_response())
        assert "Login" in values["test_name"]
        assert "alice" in values["owner_list"]
        assert "bob" in values["owner_list"]

    def test_applies_pagination_and_visibility_filter(self):
        formatted = format_ai_scriptless_tests(
            _tests_tree_response(),
            params={"page_size": 10, "skip": 0, "filters": {"visibility": "PRIVATE"}},
        )
        assert len(formatted) == 1
        assert "PRIVATE:My Folder/Login.xml" in formatted[0]
        assert "name:Login" in formatted[0]


class TestFormatterCommandId:
    def test_replaces_slashes_in_subcommand(self):
        assert _command_id("webpage", "element/click") == "webpage_element_click"


def _checkpoint_text_definition() -> dict:
    """Shape observed in the real command repository payload."""
    return {
        "commandId": "checkpoint_text",
        "data": {
            "display": {"name": "Check text"},
            "type": "VALIDATION",
            "errorPolicy": "IGNORE",
            "mandatoryParameters": [
                {
                    "name": "handsetId",
                    "dataType": "HANDSET",
                    "dataSources": ["CONSTANT", "VARIABLE", "DATATABLE"],
                    "display": {"name": "Device ID", "editorLevel": "PUBLIC", "inReport": False},
                },
                {
                    "name": "content",
                    "dataType": "STRING",
                    "dataSources": ["CONSTANT", "VARIABLE", "DATATABLE"],
                    "display": {"name": "Text", "editorLevel": "PUBLIC", "inReport": True},
                },
            ],
            "optionalParameters": [
                {
                    "name": "context",
                    "dataType": "STRING",
                    "dataSources": ["CONSTANT", "VARIABLE", "DATATABLE"],
                    "defaultValue": "all",
                    "restriction": {"type": "COMBO", "value": "all,body,link", "label": "all,body,"},
                    "display": {"name": "Context", "editorLevel": "PUBLIC", "inReport": False},
                    "helpText": "Where to look for the text",
                },
                {
                    "name": "timeout",
                    "dataType": "INTEGER",
                    "dataSources": ["CONSTANT", "VARIABLE"],
                    "defaultValue": "0",
                    "restriction": {"type": "RANGE", "range": {"minValue": 0, "maxValue": 600}},
                    "display": {"name": "Timeout", "editorLevel": "PUBLIC", "inReport": False},
                },
            ],
        },
    }


class TestFormatStepDetail:
    @staticmethod
    def _element() -> dict:
        element = build_flow_element("checkpoint_text", {"content": "Welcome"})
        element["arguments"].append({
            "@type": "FunctionArgument",
            "name": "context",
            "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT", "value": "body"},
        })
        return element

    def _detail(self, element=None, step_path="2.0"):
        return format_step_detail(
            element if element is not None else self._element(),
            item_key="PRIVATE:Folder/Test.xml",
            step_path=step_path,
            command_definitions=[_checkpoint_text_definition()],
        )

    def test_reports_step_identity(self):
        detail = self._detail()
        assert detail.item_key == "PRIVATE:Folder/Test.xml"
        assert detail.step_path == "2.0"
        assert detail.command_id == "checkpoint_text"
        assert detail.type == "Validation"
        assert detail.error_policy == "IGNORE"
        assert detail.active is True

    def test_reports_argument_values_and_sources(self):
        detail = self._detail()
        arguments = {argument.name: argument for argument in detail.arguments}
        assert arguments["content"].value == "Welcome"
        assert arguments["content"].data_source == "CONSTANT"
        assert arguments["handsetId"].value == "DUT"
        assert arguments["handsetId"].data_source == "VARIABLE"

    def test_joins_declared_parameter_metadata(self):
        detail = self._detail()
        arguments = {argument.name: argument for argument in detail.arguments}
        assert arguments["content"].parameter_type == "STRING"
        assert arguments["content"].mandatory is True
        assert arguments["content"].label == "Text"
        assert arguments["context"].mandatory is False
        assert arguments["context"].allowed_values == ["all", "body", "link"]
        assert arguments["handsetId"].allowed_data_sources == ["CONSTANT", "VARIABLE", "DATATABLE"]

    def test_lists_unset_declared_parameters(self):
        detail = self._detail()
        unset = {parameter.name: parameter for parameter in detail.unset_parameters}
        assert "timeout" in unset
        assert unset["timeout"].parameter_type == "INTEGER"
        assert unset["timeout"].value_range == "0..600"
        assert unset["timeout"].default_value == "0"
        assert unset["timeout"].mandatory is False
        # Arguments already set are not repeated as unset.
        assert "content" not in unset and "context" not in unset

    def test_flags_undeclared_argument(self):
        element = self._element()
        element["arguments"].append({
            "@type": "FunctionArgument",
            "name": "typo",
            "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT", "value": "x"},
        })
        detail = self._detail(element)
        typo = next(argument for argument in detail.arguments if argument.name == "typo")
        assert typo.declared is False
        assert any("not declared by the command" in note for note in detail.notes)

    def test_masks_secured_values(self):
        element = self._element()
        element["arguments"].append({
            "@type": "FunctionArgument",
            "name": "password",
            "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT",
                     "value": "hunter2", "secured": True},
        })
        detail = self._detail(element)
        password = next(argument for argument in detail.arguments if argument.name == "password")
        assert password.value == "<secured>"

    def test_notes_excluded_step(self):
        element = self._element()
        element["active"] = False
        detail = self._detail(element)
        assert detail.active is False
        assert any("excluded from the run" in note for note in detail.notes)

    def test_reports_container_children_paths(self):
        group = build_logical_step("Setup")
        group["flowElements"] = [build_flow_element("wait"), build_flow_element("comment")]
        detail = format_step_detail(group, item_key="PRIVATE:F/T.xml", step_path="1")
        assert detail.type == "LogicalStep"
        assert detail.label == "Setup"
        assert detail.children == ["1.0", "1.1"]

    def test_reports_condition_branches_and_label(self):
        condition = build_if_statement("Check x")
        detail = format_step_detail(condition, item_key="PRIVATE:F/T.xml", step_path="5")
        assert detail.type == "IfStatement"
        assert detail.label == "Check x"
        assert detail.children == ["5.b0", "5.b1"]

    def test_works_without_definitions(self):
        detail = format_step_detail(
            build_flow_element("wait", {"duration": "3"}),
            item_key="PRIVATE:F/T.xml",
            step_path="0",
        )
        arguments = {argument.name: argument for argument in detail.arguments}
        assert arguments["duration"].value == "3"
        # Without a definition nothing can be called undeclared.
        assert all(argument.declared for argument in detail.arguments)
        assert detail.unset_parameters == []

    def test_renders_integral_float_range_as_integers(self):
        # The script payload serializes bounds as floats (0.0 / 600.0).
        definition = _checkpoint_text_definition()
        timeout = definition["data"]["optionalParameters"][1]
        timeout["restriction"]["range"] = {"minValue": 0.0, "maxValue": 600.0}
        detail = format_step_detail(
            self._element(),
            item_key="PRIVATE:Folder/Test.xml",
            step_path="0",
            command_definitions=[definition],
        )
        unset = {parameter.name: parameter for parameter in detail.unset_parameters}
        assert unset["timeout"].value_range == "0..600"

    def test_omits_help_text_for_optional_unset_parameters(self):
        detail = self._detail()
        unset = {parameter.name: parameter for parameter in detail.unset_parameters}
        assert unset["timeout"].mandatory is False
        assert unset["timeout"].help_text is None

    def test_keeps_help_text_for_mandatory_unset_parameters(self):
        definition = _checkpoint_text_definition()
        definition["data"]["mandatoryParameters"].append({
            "name": "extra",
            "dataType": "STRING",
            "helpText": "Needed for the step to run",
            "display": {"name": "Extra", "editorLevel": "PUBLIC", "inReport": False},
        })
        detail = format_step_detail(
            self._element(),
            item_key="PRIVATE:Folder/Test.xml",
            step_path="0",
            command_definitions=[definition],
        )
        unset = {parameter.name: parameter for parameter in detail.unset_parameters}
        assert unset["extra"].help_text == "Needed for the step to run"
        # Mandatory unset parameters come first.
        assert detail.unset_parameters[0].name == "extra"

    def test_notes_mandatory_argument_left_empty(self):
        element = build_flow_element("checkpoint_text")
        element["arguments"].append({
            "@type": "FunctionArgument",
            "name": "content",
            "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT", "value": ""},
        })
        detail = self._detail(element)
        assert any("Mandatory argument(s) with no value: content" in note for note in detail.notes)

    def test_exposes_datatable_binding(self):
        element = build_flow_element("checkpoint_text", {
            "content": {"data_source": "DATATABLE", "table_name": "ProbeTable", "column": "text"},
        })
        detail = self._detail(element)
        content = next(a for a in detail.arguments if a.name == "content")
        assert content.data_source == "DATATABLE"
        assert content.table_name == "ProbeTable"
        assert content.column == "text"
        assert content.value is None

    def test_datatable_binding_is_not_reported_as_empty_mandatory(self):
        element = build_flow_element("checkpoint_text", {
            "content": {"data_source": "DATATABLE", "table_name": "ProbeTable", "column": "text"},
        })
        detail = self._detail(element)
        assert not any("Mandatory argument(s) with no value" in note for note in detail.notes)

    def test_unbound_datatable_is_reported_as_empty_mandatory(self):
        element = build_flow_element("checkpoint_text", {"content": {"data_source": "DATATABLE"}})
        detail = self._detail(element)
        assert any("Mandatory argument(s) with no value: content" in note for note in detail.notes)

    def test_reads_group_name_written_by_the_ui(self):
        # Shape captured from a UI-authored group: the title lives in `name`.
        group = {"@type": "LogicalStep", "transaction": "", "name": "Setup", "flowElements": []}
        detail = format_step_detail(group, item_key="PRIVATE:F/T.xml", step_path="2")
        assert detail.name == "Setup"
        assert detail.label == "Setup"

    def test_still_reads_the_legacy_label(self):
        group = {"@type": "LogicalStep", "label": "Old", "flowElements": []}
        assert format_step_detail(group, item_key="PRIVATE:F/T.xml", step_path="2").name == "Old"

    def test_renders_integral_float_loop_count(self):
        loop = {"@type": "Loop", "iterator": {"@type": "RepeatIterator", "count": 2.0},
                "flowElements": []}
        detail = format_step_detail(loop, item_key="PRIVATE:F/T.xml", step_path="1")
        assert detail.name == "Loop (2)"
        assert detail.loop_count == 2

    def test_step_name_shows_the_last_occurrence_of_a_multivalued_parameter(self):
        # The UI labels the step with the last value in the list; match it.
        element = build_flow_element("text_concat", {"value": ["first", "last"]})
        from formatters.ai_scriptless import _format_argument_display_value
        assert _format_argument_display_value(element, "value") == "last"
