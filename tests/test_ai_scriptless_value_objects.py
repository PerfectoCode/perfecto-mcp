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

from tools.ai_scriptless.item_key import ItemKey, build_item_key, split_item_key
from tools.ai_scriptless.step_path import StepPath
from tools.ai_scriptless.tree import find_element_by_path
from tools.ai_scriptless.elements import build_flow_element, new_empty_script


class TestItemKey:
    def test_build_and_parse_round_trip(self):
        key = ItemKey.build("PRIVATE", "My Folder", "Login")
        assert str(key) == "PRIVATE:My Folder/Login.xml"
        assert key.visibility == "PRIVATE"
        assert key.path == "My Folder/Login.xml"
        assert key.file_name == "Login.xml"
        assert key.folder_path == "My Folder"
        assert key.folder_type == "PRIVATE"

    def test_with_folder_preserves_file_name(self):
        source = ItemKey.parse("PRIVATE:Old/Login.xml")
        target = source.with_folder("Archive", "PUBLIC")
        assert str(target) == "PUBLIC:Archive/Login.xml"

    def test_legacy_helpers_match_item_key(self):
        built = build_item_key("GROUP", "Team", "Smoke")
        assert built == str(ItemKey.build("GROUP", "Team", "Smoke"))
        assert split_item_key(built) == ("GROUP", "Team/Smoke.xml")


class TestStepPath:
    def test_parse_and_str_round_trip(self):
        path = StepPath.parse("5.b0.1")
        assert path.parts == ("5", "b0", "1")
        assert str(path) == "5.b0.1"

    def test_build_nested_paths(self):
        root = StepPath.root_index(2)
        branch = root.branch(0)
        child = branch.child_index(1)
        assert str(child) == "2.b0.1"

    @pytest.mark.parametrize("invalid", ["", "1. 2", "a.b"])
    def test_parse_rejects_invalid_paths(self, invalid: str):
        with pytest.raises(ValueError):
            StepPath.parse(invalid)

    def test_find_element_by_path_accepts_step_path_object(self):
        script = new_empty_script()
        script["flowElements"] = [build_flow_element("wait")]
        located = find_element_by_path(script, StepPath.root_index(0))
        assert located is not None
        _, index, element = located
        assert index == 0
        assert element["command"] == "wait"
