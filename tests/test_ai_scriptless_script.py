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

import copy

import pytest

from formatters.ai_scriptless import PRIMARY_AI_COMMAND_IDS
from tools.ai_scriptless.elements import build_branch
from tools.ai_scriptless_script import (
    add_script_variable,
    build_flow_element,
    build_if_statement,
    build_item_key,
    build_logical_step,
    build_loop,
    build_move_test_body,
    build_snapshot_search_body,
    command_id_from_element,
    delete_element_by_path,
    delete_script_variable,
    find_element_by_path,
    find_step_path_for_element,
    format_test_ui_location,
    folder_type,
    insert_flow_element,
    modify_script_variable,
    move_element_by_path,
    new_empty_script,
    parse_command_id,
    set_condition_expression,
    set_element_enabled,
    split_item_key,
    item_key_file_name,
    strip_non_api_script_fields,
    update_element_arguments,
    validate_step_path,
)


def _sample_script() -> dict:
    """Script with root steps, a logical group, and an if/else branch for tree tests."""
    tap = build_flow_element("ai_user-action", {"action": "Tap login"})
    wait = build_flow_element("wait", {"duration": "2"})
    group = build_logical_step("Setup")
    group["flowElements"] = [build_flow_element("comment", {"text": "inside group"})]
    condition = build_if_statement("x == 1", "Check x")
    then_branch = condition["branches"][0]
    then_branch["flowElements"] = [build_flow_element("ai_validation", {"validation": "OK"})]
    script = new_empty_script()
    script["flowElements"] = [tap, group, wait, condition]
    script["numOfFlowElements"] = 4
    return script


class TestItemKey:
    def test_build_item_key_adds_xml_extension(self):
        assert build_item_key("PRIVATE", "My Folder", "Login") == "PRIVATE:My Folder/Login.xml"

    def test_build_item_key_preserves_existing_xml_extension(self):
        assert build_item_key("PUBLIC", "Shared", "Login.xml") == "PUBLIC:Shared/Login.xml"

    def test_build_item_key_strips_slashes_from_folder(self):
        assert build_item_key("PRIVATE", "/My Folder/", "Test") == "PRIVATE:My Folder/Test.xml"

    def test_split_item_key_round_trip(self):
        item_key = "GROUP:Team/Regression/Smoke.xml"
        visibility, path = split_item_key(item_key)
        assert visibility == "GROUP"
        assert path == "Team/Regression/Smoke.xml"

    def test_split_item_key_rejects_missing_visibility(self):
        with pytest.raises(ValueError, match="Invalid itemKey format"):
            split_item_key("NoVisibilityPrefix")

    def test_folder_type_maps_public_and_group(self):
        assert folder_type("PRIVATE") == "PRIVATE"
        assert folder_type("GROUP") == "GROUP"
        assert folder_type("PUBLIC") == "PUBLIC"
        assert folder_type("UNKNOWN") == "PUBLIC"

    def test_item_key_file_name(self):
        assert item_key_file_name("PRIVATE:Folder/My Test.xml") == "My Test.xml"

    def test_format_test_ui_location_with_folder(self):
        item_key = "PRIVATE:My Folder/Login.xml"
        assert format_test_ui_location(item_key) == (
            '"My Tests" → folder "My Folder" → test "Login"'
        )

    def test_format_test_ui_location_without_folder(self):
        item_key = "PUBLIC:RootTest.xml"
        assert format_test_ui_location(item_key) == '"Public Tests" → test "RootTest"'


class TestRepositoryApiBodies:
    def test_build_snapshot_search_body(self):
        body = build_snapshot_search_body("PRIVATE:My Folder/Login.xml")
        assert body == {
            "repositoryType": "SCRIPTS",
            "keyDetails": {"artifactId": "My Folder/Login.xml", "version": "v0"},
            "folderType": "PRIVATE",
        }

    def test_build_move_test_body(self):
        body = build_move_test_body("PRIVATE:Old/Login.xml", "Archive", "PUBLIC")
        assert body["repositoryType"] == "SCRIPTS"
        assert body["keyDetails"] == {"artifactId": "Old/Login.xml", "version": "v0"}
        assert body["folderType"] == "PRIVATE"
        assert body["targetKeyDetails"] == {"artifactId": "Archive/Login.xml", "version": "v0"}
        assert body["targetFolderType"] == "PUBLIC"
        assert body["copy"] is False


class TestCommandBuilding:
    def test_parse_command_id_ai_prefix(self):
        assert parse_command_id("ai_user-action") == ("ai", "user-action")
        assert parse_command_id("ai_validation") == ("ai", "validation")

    def test_parse_command_id_legacy_format(self):
        assert parse_command_id("touch_tap") == ("touch", "tap")
        assert parse_command_id("wait") == ("wait", "")

    def test_build_flow_element_ai_action(self):
        element = build_flow_element("ai_user-action", {"action": "Open app"})
        assert element["@type"] == "Action"
        assert element["command"] == "ai"
        assert element["subcommand"] == "user-action"
        assert element["errorPolicy"] == "ABORT"
        assert element["active"] is True

    def test_build_flow_element_ai_validation(self):
        element = build_flow_element("ai_validation", {"validation": "Screen visible"})
        assert element["@type"] == "Validation"
        assert element["errorPolicy"] == "IGNORE"

    def test_build_flow_element_default_handset_argument(self):
        element = build_flow_element("touch_tap")
        handset_args = [arg for arg in element["arguments"] if arg["name"] == "handsetId"]
        assert len(handset_args) == 1
        assert handset_args[0]["data"]["dataSource"] == "VARIABLE"
        assert handset_args[0]["data"]["value"] == "DUT"

    def test_build_arguments_normalizes_wait_alias(self):
        element = build_flow_element("wait", {"waitDuration": "5"})
        duration_args = [arg for arg in element["arguments"] if arg["name"] == "duration"]
        assert len(duration_args) == 1
        assert duration_args[0]["data"]["value"] == "5"
        assert all(arg["name"] != "waitDuration" for arg in element["arguments"])

    def test_command_id_from_element(self):
        element = build_flow_element("ai_user-action", {"action": "Tap"})
        assert command_id_from_element(element) == "ai_user-action"

    def test_update_element_arguments_merges_values(self):
        element = build_flow_element("ai_user-action", {"action": "Old"})
        update_element_arguments(element, {"action": "New"})
        action_args = [arg for arg in element["arguments"] if arg["name"] == "action"]
        assert action_args[0]["data"]["value"] == "New"


LEGACY_COMMAND_IDS = (
    "comment",
    "wait",
    "handset_ready",
    "touch_tap",
    "checkpoint_text",
    "checkpoint_image",
)


def _assert_command_id_round_trip(command_id: str) -> None:
    element = build_flow_element(command_id)
    assert command_id_from_element(element) == command_id
    command, subcommand = parse_command_id(command_id)
    assert element["command"] == command
    assert (element.get("subcommand") or "") == subcommand


class TestCommandIdRoundTrip:
    """Catalog command_id must survive build_flow_element and command_id_from_element."""

    @pytest.mark.parametrize("command_id", PRIMARY_AI_COMMAND_IDS)
    def test_primary_ai_command_ids(self, command_id: str) -> None:
        _assert_command_id_round_trip(command_id)

    @pytest.mark.parametrize("command_id", LEGACY_COMMAND_IDS)
    def test_legacy_and_structural_command_ids(self, command_id: str) -> None:
        _assert_command_id_round_trip(command_id)

    def test_round_trip_with_explicit_arguments(self) -> None:
        command_id = "ai_user-action"
        element = build_flow_element(command_id, {"action": "Tap login"})
        assert command_id_from_element(element) == command_id
        assert element["command"] == "ai"
        assert element["subcommand"] == "user-action"

    def test_parse_and_build_agree_on_wire_fields(self) -> None:
        for command_id in (*PRIMARY_AI_COMMAND_IDS, *LEGACY_COMMAND_IDS):
            command, subcommand = parse_command_id(command_id)
            element = build_flow_element(command_id)
            assert element["command"] == command
            assert (element.get("subcommand") or "") == subcommand


class TestStructureBuilders:
    def test_new_empty_script_has_dut_parameter(self):
        script = new_empty_script()
        assert script["@type"] == "Script"
        assert script["flowElements"] == []
        assert script["numOfFlowElements"] == 0
        dut = script["parameters"][0]["data"]
        assert dut["name"] == "DUT"
        assert dut["@type"] == "HandsetData"

    def test_build_logical_step(self):
        step = build_logical_step("Group A")
        assert step["@type"] == "LogicalStep"
        assert step["label"] == "Group A"
        assert step["flowElements"] == []

    def test_build_loop(self):
        loop = build_loop(3)
        assert loop["@type"] == "Loop"
        assert loop["iterator"]["count"] == 3

    def test_build_if_statement_has_branches(self):
        condition = build_if_statement("flag", "Flag check")
        assert condition["@type"] == "IfStatement"
        assert condition["expression"] == "flag"
        assert len(condition["branches"]) == 2
        assert condition["branches"][0]["clause"] == "THEN"
        assert condition["branches"][1]["clause"] == "ELSE"

    def test_build_if_statement_clauses_alias_branches(self):
        condition = build_if_statement("flag", "Flag check")
        assert condition["thenClause"] is condition["branches"][0]
        assert condition["elseClause"] is condition["branches"][1]
        child = build_flow_element("comment", {"text": "in then"})
        condition["branches"][0]["flowElements"].append(child)
        assert len(condition["thenClause"]["flowElements"]) == 1

    def test_normalize_if_statement_aliases_api_payload(self):
        from tools.ai_scriptless.elements import normalize_if_statement_aliases

        then_branch = build_branch("THEN")
        else_branch = build_branch("ELSE")
        then_clause = build_branch("THEN")
        then_clause["flowElements"] = [build_flow_element("comment", {"text": "from clause"})]
        script = {
            "flowElements": [{
                "@type": "IfStatement",
                "branches": [then_branch, else_branch],
                "thenClause": then_clause,
                "elseClause": build_branch("ELSE"),
            }],
        }
        normalize_if_statement_aliases(script)
        condition = script["flowElements"][0]
        assert condition["thenClause"] is condition["branches"][0]
        assert condition["elseClause"] is condition["branches"][1]
        assert len(condition["branches"][0]["flowElements"]) == 1
        assert condition["branches"][0]["flowElements"][0]["command"] == "comment"

    def test_normalize_if_statement_aliases_nested(self):
        from tools.ai_scriptless.elements import normalize_if_statement_aliases

        inner = build_if_statement()
        inner["branches"] = [build_branch("THEN"), build_branch("ELSE")]
        inner["thenClause"] = build_branch("THEN")
        inner["elseClause"] = build_branch("ELSE")
        group = build_logical_step("group")
        group["flowElements"] = [inner]
        script = {"flowElements": [group]}
        normalize_if_statement_aliases(script)
        nested = group["flowElements"][0]
        assert nested["thenClause"] is nested["branches"][0]


class TestScriptVariables:
    def test_add_and_find_variable(self):
        script = new_empty_script()
        entry = add_script_variable(script, "counter", "number", 0)
        assert entry["@type"] == "Variable"
        assert entry["data"]["name"] == "counter"
        assert entry["data"]["value"] == 0
        assert len(script["variables"]) == 1

    def test_add_variable_rejects_duplicate(self):
        script = new_empty_script()
        add_script_variable(script, "token", "string", "abc")
        with pytest.raises(ValueError, match="variable already exists"):
            add_script_variable(script, "token", "string", "xyz")

    def test_add_variable_rejects_dut_name(self):
        script = new_empty_script()
        with pytest.raises(ValueError, match="DUT is a test parameter"):
            add_script_variable(script, "DUT", "string", "x")

    def test_add_variable_rejects_invalid_name(self):
        script = new_empty_script()
        with pytest.raises(ValueError, match="cannot begin with a number"):
            add_script_variable(script, "1bad", "string", "x")

    def test_modify_script_variable(self):
        script = new_empty_script()
        add_script_variable(script, "flag", "boolean", True)
        modify_script_variable(script, "flag", value=False)
        assert script["variables"][0]["data"]["value"] is False

    def test_modify_script_variable_set_at_runtime(self):
        script = new_empty_script()
        add_script_variable(script, "env", "string", "dev")
        modify_script_variable(script, "env", set_at_runtime=True)
        assert script["variables"][0]["@type"] == "Parameter"

    def test_delete_script_variable(self):
        script = new_empty_script()
        add_script_variable(script, "temp", "string", "x")
        delete_script_variable(script, "temp")
        assert script["variables"] == []

    def test_coerce_boolean_and_number_types(self):
        script = new_empty_script()
        add_script_variable(script, "enabled", "boolean", "true")
        add_script_variable(script, "retries", "number", "3")
        assert script["variables"][0]["data"]["value"] is True
        assert script["variables"][1]["data"]["value"] == 3


class TestStepPathValidation:
    def test_accepts_valid_paths(self):
        for path in ("0", "2.0", "5.b0", "5.b0.1", "1.b1.2"):
            validate_step_path(path)

    def test_rejects_empty_or_spaced_paths(self):
        with pytest.raises(ValueError, match="step_path must be"):
            validate_step_path("")
        with pytest.raises(ValueError, match="step_path must be"):
            validate_step_path("1. 2")

    def test_rejects_invalid_segments(self):
        with pytest.raises(ValueError, match="invalid step_path"):
            validate_step_path("a.b")


class TestScriptTreeNavigation:
    def test_find_element_by_path_root_and_nested(self):
        script = _sample_script()
        root = find_element_by_path(script, "0")
        assert root is not None
        _, index, element = root
        assert index == 0
        assert element["command"] == "ai"

        nested = find_element_by_path(script, "1.0")
        assert nested is not None
        _, _, element = nested
        assert element["command"] == "comment"

    def test_find_element_by_path_if_branch(self):
        script = _sample_script()
        branch = find_element_by_path(script, "3.b0")
        assert branch is not None
        _, _, element = branch
        assert element["@type"] == "Branch"
        assert element["clause"] == "THEN"

        branch_child = find_element_by_path(script, "3.b0.0")
        assert branch_child is not None
        _, _, element = branch_child
        assert element["subcommand"] == "validation"

    def test_find_element_by_path_returns_none_for_missing(self):
        script = _sample_script()
        assert find_element_by_path(script, "99") is None
        assert find_element_by_path(script, "3.b9") is None

    def test_find_step_path_for_element_round_trip(self):
        script = _sample_script()
        for expected_path in ("0", "1", "1.0", "3.b0", "3.b0.0"):
            located = find_element_by_path(script, expected_path)
            assert located is not None
            _, _, element = located
            assert find_step_path_for_element(script, element) == expected_path

    def test_find_element_by_path_returns_parent_list_and_index(self):
        script = _sample_script()
        parent_list, index, element = find_element_by_path(script, "0")
        assert parent_list is script["flowElements"]
        assert index == 0
        assert element is script["flowElements"][0]

        group = script["flowElements"][1]
        parent_list, index, element = find_element_by_path(script, "1.0")
        assert parent_list is group["flowElements"]
        assert index == 0
        assert element is group["flowElements"][0]

        condition = script["flowElements"][3]
        parent_list, index, branch = find_element_by_path(script, "3.b0")
        assert parent_list is condition["branches"]
        assert index == 0
        assert branch is condition["branches"][0]


class TestScriptTreeMutations:
    def test_insert_flow_element_at_root_end(self):
        script = new_empty_script()
        element = build_flow_element("wait")
        insert_flow_element(script, element)
        assert script["numOfFlowElements"] == 1
        assert script["flowElements"][0]["command"] == "wait"

    def test_insert_flow_element_after_path(self):
        script = _sample_script()
        new_step = build_flow_element("comment", {"text": "inserted"})
        insert_flow_element(script, new_step, after_path="0")
        assert find_element_by_path(script, "1") is not None
        _, _, element = find_element_by_path(script, "1")
        assert element["command"] == "comment"
        assert find_step_path_for_element(script, script["flowElements"][0]) == "0"

    def test_insert_flow_element_inside_container(self):
        script = _sample_script()
        new_step = build_flow_element("comment", {"text": "in group"})
        insert_flow_element(script, new_step, parent_path="1")
        located = find_element_by_path(script, "1.1")
        assert located is not None
        _, _, element = located
        assert element["command"] == "comment"

    def test_insert_rejects_non_container_parent(self):
        script = _sample_script()
        new_step = build_flow_element("wait")
        with pytest.raises(ValueError, match="must reference a container"):
            insert_flow_element(script, new_step, parent_path="0")

    def test_delete_element_by_path(self):
        script = _sample_script()
        delete_element_by_path(script, "2")
        assert script["numOfFlowElements"] == 3
        assert find_element_by_path(script, "2") is not None
        _, _, element = find_element_by_path(script, "2")
        assert element["@type"] == "IfStatement"

    def test_set_element_enabled(self):
        script = _sample_script()
        set_element_enabled(script, "0", False)
        _, _, element = find_element_by_path(script, "0")
        assert element["active"] is False

    def test_set_condition_expression(self):
        script = _sample_script()
        set_condition_expression(script, "3", "y > 0")
        _, _, element = find_element_by_path(script, "3")
        assert element["expression"] == "y > 0"

    def test_set_condition_expression_rejects_non_if(self):
        script = _sample_script()
        with pytest.raises(ValueError, match="must reference an IfStatement"):
            set_condition_expression(script, "0", "x")

    def test_move_element_within_root(self):
        script = _sample_script()
        move_element_by_path(script, "0", after_path="2")
        _, _, first = find_element_by_path(script, "0")
        _, _, moved = find_element_by_path(script, "2")
        assert first["@type"] == "LogicalStep"
        assert moved["command"] == "ai"
        assert moved["subcommand"] == "user-action"

    def test_move_element_into_container(self):
        script = _sample_script()
        move_element_by_path(script, "2", parent_path="1")
        located = find_element_by_path(script, "1.1")
        assert located is not None
        _, _, element = located
        assert element["command"] == "wait"
        _, _, root_condition = find_element_by_path(script, "2")
        assert root_condition["@type"] == "IfStatement"


class TestStripNonApiScriptFields:
    def test_removes_uuid_from_tree(self):
        script = _sample_script()
        script["flowElements"][0]["uuid"] = "step-uuid-1"
        script["flowElements"][3]["branches"][0]["uuid"] = "branch-uuid"
        strip_non_api_script_fields(script)
        assert "uuid" not in script["flowElements"][0]
        assert "uuid" not in script["flowElements"][3]["branches"][0]

    def test_strip_does_not_mutate_unrelated_fields(self):
        script = _sample_script()
        original = copy.deepcopy(script)
        script["flowElements"][0]["uuid"] = "temp"
        strip_non_api_script_fields(script)
        script["flowElements"][0].pop("uuid", None)
        assert script["flowElements"][0] == original["flowElements"][0]
