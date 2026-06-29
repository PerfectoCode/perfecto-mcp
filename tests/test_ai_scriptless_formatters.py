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
    command_selection_policy_info,
    format_ai_scriptless_tests,
    format_ai_scriptless_tests_filter_values,
    format_command_catalog,
    format_command_definitions,
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


def _tree_api_payload() -> dict:
    script = new_empty_script()
    tap = build_flow_element("ai_user-action", {"action": "Tap login"})
    tap["uuid"] = "ignored-in-formatter"
    group = build_logical_step("Setup")
    group["flowElements"] = [build_flow_element("comment", {"text": "inside group"})]
    condition = build_if_statement("x == 1", "Check x")
    condition["branches"][0]["flowElements"] = [
        build_flow_element("ai_validation", {"validation": "OK"}),
    ]
    script["flowElements"] = [tap, group, condition]
    return {
        "script": script,
        "commandDefinitions": [
            {
                "commandId": "comment",
                "name": "Comment",
                "data": {"display": {"name": "Comment step"}},
            },
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
        assert structure.flow_elements[2].name == "Condition (x == 1)"
        then_branch = structure.flow_elements[2].children[0]
        assert then_branch.type == "Branch"
        assert then_branch.step_path == "2.b0"
        assert then_branch.children[0].step_path == "2.b0.0"

    def test_uses_definition_display_name_for_non_ai_commands(self):
        structure = format_test_structure(_tree_api_payload())
        comment_step = structure.flow_elements[1].children[0]
        assert comment_step.name == "Comment step"


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
