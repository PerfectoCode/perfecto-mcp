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
import json

from models.result import BaseResult
from tools.ai_scriptless import persistence
from tools.ai_scriptless.elements import build_branch, build_flow_element, new_empty_script
from tools.ai_scriptless.persistence import load_and_mutate, persist_script
from tools.ai_scriptless.tree import insert_flow_element
from tools.ai_scriptless.script import Script


class TestPersistScript:
    def test_persist_calls_draft_then_script_save(self, perfecto_token, monkeypatch):
        calls: list[dict] = []

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            calls.append({"method": method, "endpoint": endpoint, "json": kwargs.get("json")})
            if endpoint and "draft-management" in endpoint:
                return BaseResult(result={"key": "draft-abc"})
            return BaseResult(result={"status": "saved"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        script = new_empty_script()
        script["flowElements"] = [build_flow_element("wait")]
        result = asyncio.run(
            persist_script(perfecto_token, "PRIVATE:Folder/Test.xml", script)
        )

        assert result.error is None
        assert result.result["draft_key"] == "draft-abc"
        assert result.result["flow_element_count"] == 1
        assert len(calls) == 2
        assert calls[0]["method"] == "POST"
        assert "draft-management" in calls[0]["endpoint"]
        assert calls[1]["method"] == "POST"
        assert calls[1]["endpoint"].endswith("/script")
        assert calls[1]["json"]["draftKey"] == "draft-abc"
        assert calls[1]["json"]["itemKey"] == "PRIVATE:Folder/Test.xml"

    def test_persist_strips_uuid_before_draft_payload(self, perfecto_token, monkeypatch):
        captured_draft: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "draft-management" in endpoint:
                captured_draft["data"] = json.loads(kwargs["json"]["data"])
                return BaseResult(result={"key": "draft-abc"})
            return BaseResult(result={"status": "saved"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        script = new_empty_script()
        element = build_flow_element("comment", {"text": "x"})
        element["uuid"] = "remove-me"
        script["flowElements"] = [element]

        asyncio.run(persist_script(perfecto_token, "PRIVATE:Folder/Test.xml", script))

        unsaved = captured_draft["data"]["unsavedScript"]
        assert "uuid" not in unsaved["flowElements"][0]

    def test_persist_accepts_script_aggregate(self, perfecto_token, monkeypatch):
        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "draft-management" in endpoint:
                return BaseResult(result={"key": "draft-abc"})
            return BaseResult(result={"status": "saved"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        script = Script.empty()
        script.flow_elements.append(build_flow_element("wait"))
        result = asyncio.run(
            persist_script(perfecto_token, "PRIVATE:Folder/Test.xml", script)
        )

        assert result.error is None
        assert result.result["flow_element_count"] == 1

    def test_persist_includes_snapshot_comment_on_save(self, perfecto_token, monkeypatch):
        save_payload: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "draft-management" in endpoint:
                return BaseResult(result={"key": "draft-abc"})
            save_payload["json"] = kwargs.get("json")
            return BaseResult(result={"status": "saved"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        asyncio.run(
            persist_script(
                perfecto_token,
                "PRIVATE:Folder/Test.xml",
                new_empty_script(),
                snapshot_comment="release candidate",
            )
        )

        assert save_payload["json"]["snapshotComment"] == "release candidate"

    def test_persist_fails_when_draft_key_missing(self, perfecto_token, monkeypatch):
        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            return BaseResult(result={})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        result = asyncio.run(
            persist_script(perfecto_token, "PRIVATE:Folder/Test.xml", new_empty_script())
        )

        assert result.error == "Draft creation failed: missing draft key in response"


class TestLoadAndMutate:
    def test_load_and_mutate_applies_mutator_and_persists(self, perfecto_token, monkeypatch):
        script = new_empty_script()
        persisted: dict = {}

        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": script})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None):
            persisted["item_key"] = item_key
            persisted["flow_count"] = len(mutated_script.get("flowElements", []))
            persisted["saved_count"] = len(saved_script.get("flowElements", []))
            return BaseResult(result={"status": "ok"})

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)
        monkeypatch.setattr(persistence, "_persist_script", fake_persist)

        def mutator(current_script: dict) -> None:
            current_script.setdefault("flowElements", []).append(build_flow_element("wait"))

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator)
        )

        assert result.error is None
        assert persisted["item_key"] == "PRIVATE:Folder/Test.xml"
        assert persisted["flow_count"] == 1
        assert persisted["saved_count"] == 0

    def test_load_and_mutate_normalizes_if_statement_aliases(self, perfecto_token, monkeypatch):
        then_branch = build_branch("THEN")
        else_branch = build_branch("ELSE")
        then_clause = build_branch("THEN")
        api_script = new_empty_script()
        api_script["flowElements"] = [{
            "@type": "IfStatement",
            "branches": [then_branch, else_branch],
            "thenClause": then_clause,
            "elseClause": build_branch("ELSE"),
            "label": "Probe",
            "active": True,
        }]
        persisted: dict = {}

        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": api_script})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None):
            persisted["mutated"] = mutated_script
            return BaseResult(result={"status": "ok"})

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)
        monkeypatch.setattr(persistence, "_persist_script", fake_persist)

        def mutator(script: dict) -> None:
            insert_flow_element(
                script,
                build_flow_element("comment", {"text": "then child"}),
                parent_path="0.b0",
            )

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator)
        )

        assert result.error is None
        condition = persisted["mutated"]["flowElements"][0]
        assert condition["thenClause"] is condition["branches"][0]
        assert len(condition["thenClause"]["flowElements"]) == 1

    def test_load_and_mutate_returns_validation_error(self, perfecto_token, monkeypatch):
        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": new_empty_script()})

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)

        def mutator(_script: dict) -> None:
            raise ValueError("step_path not found: 9")

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator)
        )

        assert result.error == "step_path not found: 9"

    def test_load_and_mutate_propagates_fetch_error(self, perfecto_token, monkeypatch):
        async def fake_fetch(_token, _test_id):
            return BaseResult(error="not found")

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", lambda _s: None)
        )

        assert result.error == "not found"
