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

from formatters.ai_scriptless import PRIMARY_AI_COMMAND_IDS
from tools.ai_scriptless.commands import COMMAND_SPECS, get_command_spec


class TestCommandSpecRegistry:
    def test_known_commands_are_registered(self):
        for command_id in (
            *PRIMARY_AI_COMMAND_IDS,
            "comment",
            "wait",
            "handset_ready",
            "touch_tap",
            "checkpoint_text",
            "checkpoint_image",
        ):
            assert command_id in COMMAND_SPECS

    def test_validation_commands_use_ignore_error_policy(self):
        for command_id in ("ai_validation", "checkpoint_text", "checkpoint_image"):
            assert get_command_spec(command_id).error_policy == "IGNORE"

    def test_unknown_command_falls_back_to_handset_dut(self):
        spec = get_command_spec("custom_unknown_step")
        assert spec.element_type == "Action"
        assert spec.default_arguments_merged() == {"handsetId": ("VARIABLE", "DUT")}

    def test_wait_spec_normalizes_duration_alias(self):
        spec = get_command_spec("wait")
        normalized = spec.normalize_argument_names({"waitDuration": "5"})
        assert normalized == {"duration": "5"}
