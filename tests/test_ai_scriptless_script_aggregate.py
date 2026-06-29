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

from tools.ai_scriptless.elements import build_flow_element, build_logical_step
from tools.ai_scriptless.script import Script


def _sample_script() -> Script:
    tap = build_flow_element("ai_user-action", {"action": "Tap login"})
    wait = build_flow_element("wait", {"duration": "2"})
    group = build_logical_step("Setup")
    group["flowElements"] = [build_flow_element("comment", {"text": "inside group"})]
    script = Script.empty()
    script.flow_elements.extend([tap, group, wait])
    script.to_dict()["numOfFlowElements"] = 3
    return script


class TestScriptFactory:
    def test_empty_matches_new_empty_script_shape(self):
        script = Script.empty()
        payload = script.to_dict()
        assert payload["@type"] == "Script"
        assert payload["flowElements"] == []
        assert payload["variables"] == []
        assert payload["parameters"][0]["data"]["name"] == "DUT"

    def test_from_dict_copies_payload(self):
        original = Script.empty().to_dict()
        original["variables"].append({"name": "x"})
        wrapped = Script.from_dict(original)
        wrapped.variables.clear()
        assert len(original["variables"]) == 1

    def test_wrap_mutates_shared_dict(self):
        payload = Script.empty().to_dict()
        wrapped = Script.wrap(payload)
        wrapped.add_variable("count", "number", 1)
        assert len(payload["variables"]) == 1


class TestScriptTreeOperations:
    def test_insert_and_find_step_path(self):
        script = _sample_script()
        element = build_flow_element("comment", {"text": "new"})
        script.insert_flow_element(element, after_path="0")
        assert script.find_step_path_for_element(element) == "1"
        assert script.flow_element_count == 4

    def test_delete_element_by_path(self):
        script = _sample_script()
        script.delete_element_by_path("2")
        assert script.flow_element_count == 2
        assert script.find_element_by_path("2") is None

    def test_set_element_enabled(self):
        script = _sample_script()
        script.set_element_enabled("0", False)
        located = script.find_element_by_path("0")
        assert located is not None
        assert located[2]["active"] is False


class TestScriptVariables:
    def test_add_list_modify_delete_variable(self):
        script = Script.empty()
        script.add_variable("token", "string", "abc")
        assert len(script.list_variables()) == 1
        script.modify_variable("token", value="xyz")
        assert script.find_variable("token")[1]["data"]["value"] == "xyz"
        script.delete_variable("token")
        assert script.find_variable("token") is None


class TestScriptPersistPrep:
    def test_prepare_for_persist_strips_uuid_and_updates_counts(self):
        script = _sample_script()
        script.flow_elements[0]["uuid"] = "client-only"
        script.prepare_for_persist()
        assert "uuid" not in script.flow_elements[0]
        assert script.to_dict()["numOfFlowElements"] == script.flow_element_count

    def test_copy_is_independent(self):
        script = _sample_script()
        clone = script.copy()
        clone.delete_element_by_path("0")
        assert script.flow_element_count == 3
        assert clone.flow_element_count == 2
