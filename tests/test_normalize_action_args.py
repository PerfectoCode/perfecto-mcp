"""
Copyright 2025 Perforce Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

    10|Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from tools.utils import normalize_action_args


class TestNormalizeActionArgs:
    def test_none_returns_empty_action_and_args(self):
        action, args = normalize_action_args(None)
        assert action == ""
        assert args == {}

    def test_empty_dict_returns_empty_action_and_args(self):
        action, args = normalize_action_args({})
        assert action == ""
        assert args == {}

    def test_nested_action_and_args(self):
        action, args = normalize_action_args({
            "action": "add_command",
            "args": {"test_id": "PRIVATE:Folder/Test.xml", "command_id": "wait"},
        })
        assert action == "add_command"
        assert args == {"test_id": "PRIVATE:Folder/Test.xml", "command_id": "wait"}

    def test_flattened_top_level_params_merge_into_args(self):
        action, args = normalize_action_args({
            "action": "add_command",
            "test_id": "PRIVATE:Folder/Test.xml",
            "command_id": "wait",
            "cmd_arguments": {"duration": "1"},
        })
        assert action == "add_command"
        assert args == {
            "test_id": "PRIVATE:Folder/Test.xml",
            "command_id": "wait",
            "cmd_arguments": {"duration": "1"},
        }

    def test_unwraps_double_wrapped_arguments(self):
        action, args = normalize_action_args({
            "arguments": {
                "action": "add_command",
                "args": {"test_id": "PRIVATE:Folder/Test.xml"},
            }
        })
        assert action == "add_command"
        assert args == {"test_id": "PRIVATE:Folder/Test.xml"}

    def test_does_not_unwrap_arguments_when_other_keys_present(self):
        action, args = normalize_action_args({
            "action": "add_command",
            "args": {"test_id": "PRIVATE:Folder/Test.xml", "command_id": "wait"},
            "arguments": {"duration": "3"},
        })
        assert action == "add_command"
        assert args["test_id"] == "PRIVATE:Folder/Test.xml"
        assert args["command_id"] == "wait"
        assert args["arguments"] == {"duration": "3"}

    def test_strips_action_whitespace(self):
        action, args = normalize_action_args({"action": "  list_tests  ", "args": {}})
        assert action == "list_tests"
        assert args == {}

    def test_none_args_value_becomes_empty_dict(self):
        action, args = normalize_action_args({"action": "list_tests", "args": None})
        assert action == "list_tests"
        assert args == {}

    def test_args_is_never_none(self):
        _, args = normalize_action_args(None)
        assert args is not None
        _, args = normalize_action_args({"action": "x"})
        assert args is not None

    def test_top_level_keys_overlay_nested_args(self):
        action, args = normalize_action_args({
            "action": "add_command",
            "args": {"test_id": "nested", "command_id": "wait"},
            "test_id": "top-level",
        })
        assert action == "add_command"
        assert args["test_id"] == "top-level"
        assert args["command_id"] == "wait"
