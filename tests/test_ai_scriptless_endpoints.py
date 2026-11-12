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
from tests.conftest import make_ctx
from tools import ai_scriptless_manager
from tools.ai_scriptless import endpoints, persistence
from tools.ai_scriptless.elements import build_flow_element, new_empty_script
from tools.ai_scriptless.endpoints import (
    SCRIPT_REPOSITORY_SETTING,
    SCRIPTLESS_ENGINE_SETTING,
    ScriptStoreUnknown,
    endpoints_for,
)
from tools.ai_scriptless_manager import AiScriptlessManager

# The real lookup, kept before the autouse offline_scriptless_settings fixture replaces it.
REAL_READ_SETTINGS = endpoints.read_scriptless_settings

TEST_ID = "PRIVATE:Folder/Test.xml"
NATIVE = "https://demo.app.perfectomobile.com/native-automation-webapp/rest/v1/native-automation"
NATIVE_DRAFT = "https://demo.app.perfectomobile.com/native-automation-webapp/rest/v1/draft-management/draft"
ASSET = "https://demo.perfectomobile.com/scriptless-mobile-engine/script-asset-manager/api"
SETTINGS_URL = "https://demo.app.perfectomobile.com/feature-settings-webapp/rest/v1/feature-settings"


def _setting(name: str, value) -> dict:
    return {"name": name, "value": value, "type": "BOOLEAN", "categories": ["ui"]}


def _answer_settings(monkeypatch, *answers) -> list:
    """Answer each settings read in turn; the last answer repeats."""
    calls = []
    monkeypatch.setattr(endpoints, "SETTINGS_RETRY_SECONDS", 0.0)

    async def fake_api_request(_token, method, endpoint=None, **kwargs):
        calls.append((method, endpoint, kwargs.get("params")))
        answer = answers[min(len(calls), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(endpoints, "api_request", fake_api_request)
    return calls


class TestReadScriptlessSettings:
    """The Perfecto UI's rule: a missing or false setting means the older store; an unreadable one stops."""

    @pytest.mark.parametrize("engine, repository, expected", [
        ("true", "true", (True, True)),
        ("true", "false", (True, False)),
        ("false", "true", (False, False)),
        (True, True, (True, True)),
        ("True", "true", (False, False)),
    ])
    def test_values_follow_the_ui(self, perfecto_token, monkeypatch, engine, repository, expected):
        _answer_settings(monkeypatch, BaseResult(result=[
            _setting("issue-tracking.enabled", "true"),
            _setting(SCRIPTLESS_ENGINE_SETTING, engine),
            _setting(SCRIPT_REPOSITORY_SETTING, repository),
        ]))

        assert asyncio.run(REAL_READ_SETTINGS(perfecto_token)) == expected

    def test_reads_the_ui_category_of_the_feature_settings(self, perfecto_token, monkeypatch):
        calls = _answer_settings(monkeypatch, BaseResult(result=[]))

        asyncio.run(REAL_READ_SETTINGS(perfecto_token))

        assert calls == [("GET", SETTINGS_URL, {"category": "ui"})]

    def test_settings_not_present_mean_the_older_store(self, perfecto_token, monkeypatch):
        _answer_settings(monkeypatch, BaseResult(result=[_setting("issue-tracking.enabled", "true")]))

        assert asyncio.run(REAL_READ_SETTINGS(perfecto_token)) == (False, False)

    @pytest.mark.parametrize("answer", [
        BaseResult(error="Invalid credentials"),
        BaseResult(result={"unexpected": "shape"}),
        BaseResult(result=None),
        httpx.ConnectError("no route"),
        RuntimeError("anything else"),
    ])
    def test_unreadable_settings_stop_after_one_retry(self, perfecto_token, monkeypatch, answer):
        # A failed read says nothing about the cloud; guessing the older store could
        # send a save to the store that does not hold the test.
        calls = _answer_settings(monkeypatch, answer)

        with pytest.raises(ScriptStoreUnknown, match="Nothing was read or changed"):
            asyncio.run(REAL_READ_SETTINGS(perfecto_token))

        assert len(calls) == 2

    def test_a_retry_that_reads_the_settings_is_used(self, perfecto_token, monkeypatch):
        calls = _answer_settings(monkeypatch, httpx.ReadTimeout("slow"), BaseResult(result=[
            _setting(SCRIPTLESS_ENGINE_SETTING, "true"),
            _setting(SCRIPT_REPOSITORY_SETTING, "true"),
        ]))

        assert asyncio.run(REAL_READ_SETTINGS(perfecto_token)) == (True, True)
        assert len(calls) == 2

    def test_the_error_names_the_cause(self, perfecto_token, monkeypatch):
        _answer_settings(monkeypatch, BaseResult(error="Invalid credentials"))

        with pytest.raises(ScriptStoreUnknown, match=r"failed 2 times \(Invalid credentials\)"):
            asyncio.run(REAL_READ_SETTINGS(perfecto_token))


class TestStoreUnknownReachesTheAgent:
    """An unreadable store stops the tool with its error, and nothing is read or written."""

    @pytest.mark.parametrize("action, args", [
        ("list_tests", {"page_index": 1}),
        ("view_test_structure", {"test_id": TEST_ID}),
    ])
    def test_tool_returns_the_error_without_touching_a_store(self, perfecto_token, monkeypatch, action, args):
        from tests.test_ai_scriptless_manager import _call_tool, _register_tool

        async def unknown(_token):
            raise ScriptStoreUnknown("Could not tell which AI Scriptless service this cloud uses: test")

        store_calls = []

        async def fake_api_request(*_args, **_kwargs):
            store_calls.append(1)
            return BaseResult(result=[])

        monkeypatch.setattr(endpoints, "read_scriptless_settings", unknown)
        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        result = asyncio.run(_call_tool(_register_tool(perfecto_token), action, args))

        assert result.error == "Could not tell which AI Scriptless service this cloud uses: test"
        assert store_calls == []

    def test_change_writes_nothing(self, perfecto_token, monkeypatch):
        async def unknown(_token):
            raise ScriptStoreUnknown("unknown")

        writes = []

        async def fake_api_request(*_args, **_kwargs):
            writes.append(1)
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(endpoints, "read_scriptless_settings", unknown)
        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        with pytest.raises(ScriptStoreUnknown):
            asyncio.run(persistence.load_and_mutate(perfecto_token, TEST_ID, lambda script: None))

        assert writes == []


class TestEndpointsFor:
    def test_older_store(self):
        found = endpoints_for("demo", False, False)

        assert found.tree_url == NATIVE + "/scripts/tree"
        assert found.draft_url == NATIVE_DRAFT
        assert found.script_url == NATIVE + "/script"
        assert found.delete_url == NATIVE + "/repositories"

    def test_newer_store(self):
        found = endpoints_for("demo", True, True)

        assert found.tree_url == ASSET + "/script-directory-repository/tree"
        assert found.draft_url == ASSET + "/script-draft-repository/draft"
        assert found.script_url == ASSET + "/script-repository/script"
        assert found.delete_url == ASSET + "/script-repository/script"

    def test_engine_without_script_repository_moves_only_the_tree_and_drafts(self):
        found = endpoints_for("demo", True, False)

        assert found.tree_url == ASSET + "/script-directory-repository/tree"
        assert found.draft_url == ASSET + "/script-draft-repository/draft"
        assert found.script_url == NATIVE + "/script"
        assert found.delete_url == NATIVE + "/repositories"

    def test_script_repository_without_engine_is_the_older_store(self):
        assert endpoints_for("demo", False, True) == endpoints_for("demo", False, False)


class TestOlderStoreEndToEnd:
    """With the settings off, every operation goes where it went before the newer store."""

    @staticmethod
    def _older(monkeypatch) -> list:
        reads = []

        async def both_off(_token):
            reads.append(1)
            return False, False

        monkeypatch.setattr(endpoints, "read_scriptless_settings", both_off)
        return reads

    @staticmethod
    def _record(monkeypatch, module) -> list:
        calls = []

        async def fake_api_request(_token, method, endpoint=None, result_formatter=None,
                                   result_formatter_params=None, **kwargs):
            calls.append((method, endpoint.split("?")[0]))
            if method == "GET" and endpoint.startswith(NATIVE + "/script?"):
                script = new_empty_script()
                script["flowElements"] = [build_flow_element("comment", {"text": "kept"})]
                return BaseResult(result={"script": script})
            if endpoint == NATIVE_DRAFT:
                return BaseResult(result={"key": "draft-1"})
            if endpoint.endswith("/tree"):
                return BaseResult(result=[])
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(module, "api_request", fake_api_request)
        return calls

    def test_tree_read_and_delete(self, perfecto_token, monkeypatch):
        self._older(monkeypatch)
        calls = self._record(monkeypatch, ai_scriptless_manager)
        manager = AiScriptlessManager(make_ctx(perfecto_token))

        asyncio.run(manager.list_tests({"page_index": 1}))
        asyncio.run(manager.view_test_structure(TEST_ID))
        asyncio.run(manager.delete_test(TEST_ID))

        assert calls == [
            ("GET", NATIVE + "/scripts/tree"),
            ("GET", NATIVE + "/script"),
            ("DELETE", NATIVE + "/repositories"),
        ]

    def test_change_reads_drafts_saves_and_reads_back_on_the_older_store(self, perfecto_token, monkeypatch):
        reads = self._older(monkeypatch)
        calls = self._record(monkeypatch, persistence)

        def adding(script):
            script["flowElements"].append(build_flow_element("comment", {"text": "new"}))

        result = asyncio.run(persistence.load_and_mutate(perfecto_token, TEST_ID, adding))

        assert result.error is None
        assert calls[:3] == [
            ("GET", NATIVE + "/script"),
            ("POST", NATIVE_DRAFT),
            ("POST", NATIVE + "/script"),
        ]
        assert set(calls[3:]) == {("GET", NATIVE + "/script")}  # the read-back
        assert reads == [1]  # the settings are read once for the whole change

    def test_new_test_is_saved_on_the_older_store(self, perfecto_token, monkeypatch):
        self._older(monkeypatch)
        calls = self._record(monkeypatch, persistence)

        result = asyncio.run(persistence.persist_script(perfecto_token, TEST_ID, new_empty_script()))

        assert result.error is None
        assert calls == [("POST", NATIVE_DRAFT), ("POST", NATIVE + "/script"), ("GET", NATIVE + "/script")]
