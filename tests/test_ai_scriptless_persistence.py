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
import copy
import hashlib
import json

import httpx
import pytest

from models.result import BaseResult
from config.token import PerfectoToken
from tools.ai_scriptless import persistence
from tools.ai_scriptless.elements import (
    build_branch,
    build_flow_element,
    build_logical_step,
    build_loop,
    new_empty_script,
)
from tools.ai_scriptless.persistence import load_and_mutate, persist_script
from tools.ai_scriptless.tree import insert_flow_element
from tools.ai_scriptless.script import Script

# The real lookup, kept before the autouse offline_lock_owner fixture replaces it.
REAL_LOCK_OWNER = persistence.script_lock_owner


class TestPersistScript:
    def test_persist_calls_draft_then_script_save(self, perfecto_token, monkeypatch):
        calls: list[dict] = []

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            calls.append({"method": method, "endpoint": endpoint, "json": kwargs.get("json")})
            if endpoint and "script-draft-repository" in endpoint:
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
        assert len(calls) == 3
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"].endswith("/script-draft-repository/draft")
        assert calls[1]["method"] == "POST"
        assert calls[1]["endpoint"].endswith("/script-repository/script")
        assert calls[1]["json"]["draftKey"] == "draft-abc"
        assert calls[1]["json"]["itemKey"] == "PRIVATE:Folder/Test.xml"
        assert calls[2]["method"] == "GET"  # the read-back

    def test_persist_strips_uuid_before_draft_payload(self, perfecto_token, monkeypatch):
        captured_draft: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "script-draft-repository" in endpoint:
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
            if endpoint and "script-draft-repository" in endpoint:
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
            if endpoint and "script-draft-repository" in endpoint:
                return BaseResult(result={"key": "draft-abc"})
            if method == "POST":
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

        async def fake_fetch(_token, _test_id, _endpoints=None):
            return BaseResult(result={"script": script})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None, _endpoints=None):
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

        async def fake_fetch(_token, _test_id, _endpoints=None):
            return BaseResult(result={"script": api_script})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None, _endpoints=None):
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
        async def fake_fetch(_token, _test_id, _endpoints=None):
            return BaseResult(result={"script": new_empty_script()})

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)

        def mutator(_script: dict) -> None:
            raise ValueError("step_path not found: 9")

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator)
        )

        assert result.error == "step_path not found: 9"

    def test_load_and_mutate_propagates_fetch_error(self, perfecto_token, monkeypatch):
        async def fake_fetch(_token, _test_id, _endpoints=None):
            return BaseResult(error="not found")

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)

        result = asyncio.run(
            load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", lambda _s: None)
        )

        assert result.error == "not found"


class TestLoadAndMutateAsyncMutator:
    """Mutators may be async when they need the API before mutating (command definitions)."""

    @staticmethod
    def _mock_script_io(monkeypatch, persisted: dict):
        async def fake_fetch(_token, _test_id, _endpoints=None):
            return BaseResult(result={"script": new_empty_script()})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None, _endpoints=None):
            persisted["item_key"] = item_key
            persisted["flow_count"] = len(mutated_script.get("flowElements", []))
            return BaseResult(result={"status": "ok"})

        monkeypatch.setattr(persistence, "fetch_script_payload", fake_fetch)
        monkeypatch.setattr(persistence, "_persist_script", fake_persist)

    def test_awaits_async_mutator_before_persisting(self, perfecto_token, monkeypatch):
        persisted: dict = {}
        self._mock_script_io(monkeypatch, persisted)

        async def mutator(current_script: dict) -> None:
            await asyncio.sleep(0)
            current_script.setdefault("flowElements", []).append(build_flow_element("wait"))

        result = asyncio.run(load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator))

        assert result.error is None
        assert persisted["flow_count"] == 1

    def test_async_mutator_validation_error_skips_persist(self, perfecto_token, monkeypatch):
        persisted: dict = {}
        self._mock_script_io(monkeypatch, persisted)

        async def mutator(_current_script: dict) -> None:
            await asyncio.sleep(0)
            raise ValueError("Unknown cmd_arguments for command 'wait'")

        result = asyncio.run(load_and_mutate(perfecto_token, "PRIVATE:Folder/Test.xml", mutator))

        assert result.error == "Unknown cmd_arguments for command 'wait'"
        assert persisted == {}


ITEM = "PRIVATE:Folder/Test.xml"


class _FakeStore:
    """Keeps every save as a version and serves one, misbehaving the ways the service was seen to."""

    def __init__(self):
        self.versions: list[dict] = [self._as_served(new_empty_script())]
        self.served = 0
        self.lag_reads = 0      # the next reads return the version before the served one
        self.lag_after_save = 0  # how many reads lag after each kept save
        self.drop_next = False  # the next save answers success and keeps nothing
        self.refuse = False     # saves answer HTTP 400
        self.rewrite = None     # applied to what is kept, the way the service drops or converts content
        self.failing_reads = 0  # the next reads raise, as a transport error would
        self.sent: list[dict] = []
        self.reads = 0

    @staticmethod
    def _as_served(script: dict) -> dict:
        served = copy.deepcopy(script)
        served["empty"] = not served.get("flowElements")
        for index, element in enumerate(served.get("flowElements", [])):
            element["uuid"] = f"server-{index}"
        return served

    def edit_elsewhere(self, script: dict) -> None:
        self.versions.append(self._as_served(script))
        self.served = len(self.versions) - 1

    async def api_request(self, _token, method, endpoint=None, **kwargs):
        if method == "GET":
            self.reads += 1
            if self.failing_reads:
                self.failing_reads -= 1
                raise httpx.ConnectError("connection reset")
            index = self.served
            if self.lag_reads:
                self.lag_reads -= 1
                index = max(index - 1, 0)
            return BaseResult(result={"script": copy.deepcopy(self.versions[index])})
        if "script-draft-repository" in endpoint:
            return BaseResult(result={"key": f"draft-{len(self.sent)}"})
        if self.refuse:
            return BaseResult(error="HTTP 400: Something went wrong.")
        self.sent.append(copy.deepcopy(kwargs["json"]["script"]))
        if self.drop_next:
            self.drop_next = False
        else:
            kept = copy.deepcopy(kwargs["json"]["script"])
            if self.rewrite:
                self.rewrite(kept)
            self.edit_elsewhere(kept)
            self.lag_reads = self.lag_after_save
        return BaseResult(result={"status": "success"})


def _adding(text: str):
    def mutator(script: dict) -> None:
        script.setdefault("flowElements", []).append(build_flow_element("comment", {"text": text}))
    return mutator


def _texts(script: dict) -> list[str]:
    return [
        argument["data"]["value"]
        for element in script.get("flowElements", [])
        for argument in element.get("arguments", [])
        if argument.get("name") == "text"
    ]


class TestReadBackAfterSave:
    """A read right after a save can return the version from before it (seen on the service)."""

    @staticmethod
    def _store(monkeypatch) -> _FakeStore:
        store = _FakeStore()
        monkeypatch.setattr(persistence, "api_request", store.api_request)
        return store

    @staticmethod
    def _change(token, text: str):
        return asyncio.run(load_and_mutate(token, ITEM, _adding(text)))

    def test_fresh_read_is_built_on_as_before(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)

        first = self._change(perfecto_token, "first")
        second = self._change(perfecto_token, "second")

        assert _texts(store.sent[-1]) == ["first", "second"]
        assert first.warning is None and second.warning is None

    def test_lagging_read_after_a_save_is_absorbed_by_the_read_back(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)
        store.lag_after_save = 1

        first = self._change(perfecto_token, "first")
        self._change(perfecto_token, "second")

        assert first.warning is None
        assert _texts(store.sent[-1]) == ["first", "second"]

    def test_read_back_waits_until_the_change_shows(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)
        store.lag_after_save = 2

        result = self._change(perfecto_token, "first")

        assert result.warning is None
        assert store.reads == 4  # one to build on, then three until the save showed

    def test_save_that_never_shows_warns_without_failing(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        store.drop_next = True

        result = self._change(perfecto_token, "first")

        assert result.error is None
        assert any("did not show the change" in line for line in result.warning)

    def test_dropped_save_is_reported_not_recovered(self, perfecto_token, monkeypatch):
        # Nothing is kept between requests, so a save the service dropped is only
        # reported; the next change builds on what the service returns.
        store = self._store(monkeypatch)
        store.drop_next = True

        self._change(perfecto_token, "first")
        self._change(perfecto_token, "second")

        assert _texts(store.sent[-1]) == ["second"]

    def test_change_made_elsewhere_is_built_on(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        self._change(perfecto_token, "first")
        elsewhere = new_empty_script()
        elsewhere["flowElements"] = [build_flow_element("comment", {"text": "from the UI"})]
        store.edit_elsewhere(elsewhere)

        self._change(perfecto_token, "second")

        assert _texts(store.sent[-1]) == ["from the UI", "second"]

    def test_refused_save_returns_the_error(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        store.refuse = True

        result = self._change(perfecto_token, "first")

        assert result.error == "HTTP 400: Something went wrong."

    def test_fingerprint_ignores_what_the_service_adds(self):
        # What the service added or changed on a save of a new test.
        sent = new_empty_script()
        sent["flowElements"] = [build_flow_element("comment", {"text": "x"})]
        served = _FakeStore._as_served(sent)
        served.update({"uuid": "server-script", "numOfFlowElements": 1, "active": True,
                       "comment": None, "status": None})
        changed = copy.deepcopy(sent)
        changed["flowElements"].append(build_flow_element("comment", {"text": "y"}))

        assert persistence.script_fingerprint(served) == persistence.script_fingerprint(sent)
        assert persistence.script_fingerprint(changed) != persistence.script_fingerprint(sent)

    def test_loop_count_read_back_as_a_float_is_the_same_count(self):
        # The older store gives a loop count of 2 back as 2.0.
        sent = new_empty_script()
        sent["flowElements"] = [build_loop(2)]
        stored = copy.deepcopy(sent)
        stored["flowElements"][0]["iterator"]["count"] = 2.0
        other = copy.deepcopy(sent)
        other["flowElements"][0]["iterator"]["count"] = 2.5

        assert persistence.script_fingerprint(stored) == persistence.script_fingerprint(sent)
        assert persistence.script_fingerprint(other) != persistence.script_fingerprint(sent)

    def test_loop_saved_on_a_store_that_returns_floats_is_confirmed(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)

        def as_floats(script):
            for element in script["flowElements"]:
                iterator = element.get("iterator") or {}
                if "count" in iterator:
                    iterator["count"] = float(iterator["count"])

        store.rewrite = as_floats

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, lambda s: s["flowElements"].append(build_loop(2))))

        assert result.error is None and result.warning is None
        assert store.reads == 2  # the read to build on, then one read-back

    def test_fingerprint_counts_the_test_settings(self):
        sent = new_empty_script()
        other_options, other_info = copy.deepcopy(sent), copy.deepcopy(sent)
        other_options["options"]["automaticAllocation"] = False
        other_info["info"]["description"] = "another"

        assert persistence.script_fingerprint(other_options) != persistence.script_fingerprint(sent)
        assert persistence.script_fingerprint(other_info) != persistence.script_fingerprint(sent)

    def test_copy_is_not_confirmed_by_a_target_still_showing_its_old_settings(self, perfecto_token, monkeypatch):
        # The target already holds the same steps with other settings; reads lag behind the copy.
        store = _FakeStore()
        monkeypatch.setattr(persistence, "api_request", store.api_request)
        source = _texts_script("same")
        source["options"]["automaticAllocation"] = False
        old_target = _texts_script("same")
        store.edit_elsewhere(old_target)
        store.lag_after_save = 99

        result = asyncio.run(persist_script(perfecto_token, ITEM, source))

        assert "did not show the change" in " ".join(result.warning)

    def test_settings_stored_differently_are_named(self):
        sent = new_empty_script()
        stored = copy.deepcopy(sent)
        stored["options"]["automaticAllocation"] = False

        lines = persistence.describe_stored_differences(sent, stored)

        assert lines == ['options: sent {"@type": "ScriptOptions", "automaticAllocation": true}, '
                         'stored {"@type": "ScriptOptions", "automaticAllocation": false}']

    def test_content_stored_differently_is_named_in_the_warning(self, perfecto_token, monkeypatch):
        # Measured on the service: a field it does not know is dropped, a number
        # where it expects text is converted, and the save still answers success.
        store = self._store(monkeypatch)

        def convert(script: dict) -> None:
            last = script["flowElements"][-1]
            last.pop("bogusField", None)
            for argument in last["arguments"]:
                argument["data"]["value"] = str(argument["data"]["value"])

        store.rewrite = convert

        def adding_malformed(script: dict) -> None:
            element = build_flow_element("comment", {"text": "first"})
            element["arguments"][0]["data"]["value"] = 12345
            element["bogusField"] = "x"
            script.setdefault("flowElements", []).append(element)

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, adding_malformed))

        assert result.error is None
        warning = " ".join(result.warning)
        assert "stored something different from what was sent" in warning
        assert "step 0 argument text" in warning and '"12345"' in warning
        assert 'step 0 bogusField: sent "x", stored null' in warning
        assert "did not show the change" not in warning

    def test_save_that_never_shows_is_not_called_stored_differently(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        store.drop_next = True

        result = self._change(perfecto_token, "first")

        warning = " ".join(result.warning)
        assert "did not show the change" in warning
        assert "stored something different" not in warning

    def test_version_caught_in_passing_is_not_reported(self, perfecto_token, monkeypatch):
        # The change is built on a read that lagged behind an edit made elsewhere, and
        # the read-back first returns that edit before the save shows.
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)
        elsewhere = new_empty_script()
        elsewhere["flowElements"] = [build_flow_element("comment", {"text": "from the UI"})]
        store.edit_elsewhere(elsewhere)
        store.lag_reads = 1
        store.lag_after_save = 1

        result = self._change(perfecto_token, "first")

        assert result.warning is None
        assert store.reads == 3  # the lagging read to build on, the UI edit, then the save

    def test_differences_reach_nested_steps_and_variables(self):
        sent = new_empty_script()
        group = build_logical_step("group")
        group["flowElements"] = [build_flow_element("comment", {"text": "inside"})]
        sent["flowElements"] = [group]
        sent["variables"] = [{"@type": "Variable", "data": {"@type": "StringData", "name": "v", "value": "x"}}]
        stored = copy.deepcopy(sent)
        stored["flowElements"][0]["flowElements"] = []
        stored["variables"] = []

        lines = persistence.describe_stored_differences(sent, stored)

        assert any(line.startswith("step 0.0 (") and line.endswith("sent, not stored") for line in lines)
        assert any(line.startswith("variable v: sent") and line.endswith("stored null") for line in lines)


class TestReviewedReadBack:
    """Read-back cases raised in review of the save confirmation."""

    @staticmethod
    def _store(monkeypatch) -> "_FakeStore":
        store = _FakeStore()
        monkeypatch.setattr(persistence, "api_request", store.api_request)
        return store

    def test_read_back_that_raises_is_retried_not_reported_as_failure(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)

        async def change():
            # The read the change builds on works; the first read-back fails.
            async def mutate(script):
                store.failing_reads = 1
                script.setdefault("flowElements", []).append(build_flow_element("comment", {"text": "first"}))
            return await load_and_mutate(perfecto_token, ITEM, mutate)

        result = asyncio.run(change())

        assert result.error is None
        assert result.warning is None

    def test_read_back_that_never_works_warns_without_failing(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)

        def mutate(script):
            store.failing_reads = 99
            script.setdefault("flowElements", []).append(build_flow_element("comment", {"text": "first"}))

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, mutate))

        assert result.error is None
        warning = " ".join(result.warning)
        assert "could not be read back to confirm it" in warning
        assert "ConnectError" in warning

    @pytest.mark.parametrize("flag", [True, "true", "True", 1])
    def test_any_truthy_secured_flag_hides_the_value(self, flag):
        def with_password(value):
            script = new_empty_script()
            script["variables"] = [{"@type": "Variable", "data": {
                "@type": "StringData", "name": "password", "secured": flag, "value": value}}]
            return script

        lines = persistence.describe_stored_differences(with_password("sent-cipher"), with_password("stored-cipher"))

        assert lines and "<secured>" in lines[0]
        assert "sent-cipher" not in lines[0] and "stored-cipher" not in lines[0]

    def test_secured_values_are_not_shown_in_the_warning(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)

        def convert(script):
            script["variables"][0]["data"]["value"] = "stored-cipher"

        store.rewrite = convert

        def adding_secured(script):
            script.setdefault("variables", []).append({"@type": "Variable", "data": {
                "@type": "StringData", "name": "password", "secured": True, "value": "sent-cipher"}})

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, adding_secured))

        warning = " ".join(result.warning)
        assert "variable password" in warning and "<secured>" in warning
        assert "sent-cipher" not in warning and "stored-cipher" not in warning

    def test_an_earlier_occurrence_of_a_repeated_argument_is_named(self):
        def concat(*values):
            element = build_flow_element("comment", {"text": "x"})
            element["arguments"] = [
                {"@type": "FunctionArgument", "name": "value",
                 "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT", "value": value}}
                for value in values
            ]
            script = new_empty_script()
            script["flowElements"] = [element]
            return script

        lines = persistence.describe_stored_differences(concat("a", "b"), concat("changed", "b"))

        assert len(lines) == 1
        assert lines[0].startswith("step 0 argument value: sent [")
        assert '"a"' in lines[0] and '"changed"' in lines[0]

    def test_new_test_is_confirmed(self, perfecto_token, monkeypatch):
        store = self._store(monkeypatch)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 5.0)
        store.lag_after_save = 1

        result = asyncio.run(persist_script(perfecto_token, ITEM, _texts_script("created")))

        assert result.error is None and result.warning is None
        assert store.reads == 2  # the lagging read, then the save

    def test_new_test_that_does_not_show_is_reported_as_not_shown(self, perfecto_token, monkeypatch):
        # Nothing is known about what the key held before, so a read that differs is not
        # called "stored differently": it may be the old content of a key being overwritten.
        store = self._store(monkeypatch)
        store.drop_next = True
        store.edit_elsewhere(_texts_script("was there"))

        result = asyncio.run(persist_script(perfecto_token, ITEM, _texts_script("copied")))

        warning = " ".join(result.warning)
        assert "did not show the change" in warning
        assert "stored something different" not in warning


class TestSecondReviewReadBack:
    """Read-back cases raised in the second review of the save confirmation."""

    @staticmethod
    def _answering(monkeypatch, read):
        async def fake_api_request(_token, method, endpoint=None, **_kwargs):
            if method == "GET":
                return await read()
            if "script-draft-repository" in endpoint:
                return BaseResult(result={"key": "draft-1"})
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

    def test_stalled_read_back_is_cut_at_the_deadline(self, perfecto_token, monkeypatch):
        async def stall():
            await asyncio.sleep(3600)

        self._answering(monkeypatch, stall)
        monkeypatch.setattr(persistence, "CONFIRM_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(persistence, "CONFIRM_READ_MIN_SECONDS", 0.1)

        async def timed():
            started = asyncio.get_running_loop().time()
            result = await persist_script(perfecto_token, ITEM, _texts_script("created"))
            return result, asyncio.get_running_loop().time() - started

        result, seconds = asyncio.run(timed())

        assert result.error is None
        assert "could not be read back to confirm it (TimeoutError" in " ".join(result.warning)
        assert seconds < 2

    def test_answer_without_a_script_is_a_warning_not_an_exception(self, perfecto_token, monkeypatch):
        async def no_script():
            return BaseResult(result={"script": None})

        self._answering(monkeypatch, no_script)

        result = asyncio.run(persist_script(perfecto_token, ITEM, _texts_script("created")))

        assert result.error is None
        assert "the answer held no script" in " ".join(result.warning)

    def test_unnamed_secured_entry_does_not_show_its_value(self):
        sent = new_empty_script()
        stored = new_empty_script()
        stored["variables"] = [{"@type": "Variable", "data": {"@type": "StringData", "secured": True,
                                                              "value": "secret-cipher"}}]

        lines = persistence.describe_stored_differences(sent, stored)

        assert lines and lines[0].startswith("variable #0:")
        assert "secret-cipher" not in " ".join(lines)


class TestThirdReviewReadBack:
    """Read-back cases raised in the third review of the save confirmation."""

    @staticmethod
    def _with_arguments(*names: str) -> dict:
        element = build_flow_element("comment", {"text": "x"})
        element["arguments"] = [
            {"@type": "FunctionArgument", "name": name,
             "data": {"@type": "ConstantArgumentData", "dataSource": "CONSTANT", "value": name + "-value"}}
            for name in names
        ]
        script = new_empty_script()
        script["flowElements"] = [element]
        return script

    def test_reordered_arguments_are_named(self):
        lines = persistence.describe_stored_differences(
            self._with_arguments("first", "second"), self._with_arguments("second", "first"))

        assert lines == ['step 0 argument order: sent ["first", "second"], stored ["second", "first"]']

    def test_reordered_variables_are_named(self):
        def with_variables(*names):
            script = new_empty_script()
            script["variables"] = [{"@type": "Variable", "data": {"@type": "StringData", "name": name, "value": "v"}}
                                   for name in names]
            return script

        lines = persistence.describe_stored_differences(with_variables("a", "b"), with_variables("b", "a"))

        assert lines == ['variables order: sent ["a", "b"], stored ["b", "a"]']

    def test_variable_whose_data_is_not_an_object_goes_by_position(self):
        stored = new_empty_script()
        stored["variables"] = [{"@type": "Variable", "data": "not an object"}]

        lines = persistence.describe_stored_differences(new_empty_script(), stored)

        assert lines and lines[0].startswith("variable #0:")

    def test_content_the_comparison_cannot_take_apart_still_warns(self, perfecto_token, monkeypatch):
        store = _FakeStore()
        monkeypatch.setattr(persistence, "api_request", store.api_request)

        def unreadable(script):
            script["flowElements"][-1]["flowElements"] = {"not": "a list"}

        store.rewrite = unreadable

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, _adding("first")))

        assert result.error is None
        assert "the comparison could not name where" in " ".join(result.warning)


class TestDeleteScript:
    """A delete waits for a write in flight, so the save cannot bring the test back."""

    def test_delete_waits_for_a_change_in_flight(self, perfecto_token, monkeypatch):
        order = []
        saving = asyncio.Event()
        finish_save = asyncio.Event()

        async def fake_api_request(_token, method, endpoint=None, **_kwargs):
            if method == "GET":
                return BaseResult(result={"script": _texts_script("kept")})
            if "script-draft-repository" in endpoint:
                saving.set()
                await finish_save.wait()
                return BaseResult(result={"key": "draft-1"})
            order.append(method)
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        async def both():
            change = asyncio.create_task(load_and_mutate(perfecto_token, ITEM, _adding("new")))
            await saving.wait()
            delete = asyncio.create_task(persistence.delete_script(perfecto_token, ITEM))
            await asyncio.sleep(0.05)
            finish_save.set()
            await asyncio.gather(change, delete)

        asyncio.run(both())

        assert order == ["POST", "DELETE"]  # the save first, then the delete
        assert persistence._script_write_locks == {}

    def test_delete_uses_the_selected_store(self, perfecto_token, monkeypatch):
        calls = []

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            calls.append((method, endpoint, kwargs.get("params")))
            return BaseResult(result={"status": "deleted"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        result = asyncio.run(persistence.delete_script(perfecto_token, ITEM))

        assert result.error is None
        assert calls == [("DELETE", "https://demo.perfectomobile.com/scriptless-mobile-engine/script-asset-manager"
                                    "/api/script-repository/script", {"itemKey": ITEM})]


class TestCopyScript:
    """Save as: both locks and one service from reading the source to reading back the copy."""

    OTHER = "PRIVATE:Folder/Copy.xml"

    def test_both_locks_are_held_while_the_copy_is_saved(self, perfecto_token, monkeypatch):
        store = _FakeStore()
        store.edit_elsewhere(_texts_script("original"))
        held_during_save = []

        async def recording(token, method, endpoint=None, **kwargs):
            if method == "POST" and "script-repository/script" in endpoint:
                held_during_save.append(sorted(key[2] for key in persistence._script_write_locks))
            return await store.api_request(token, method, endpoint, **kwargs)

        monkeypatch.setattr(persistence, "api_request", recording)

        result = asyncio.run(persistence.copy_script(perfecto_token, ITEM, self.OTHER))

        assert result.error is None
        assert held_during_save == [sorted([ITEM, self.OTHER])]
        assert _texts(store.sent[-1]) == ["original"]
        assert persistence._script_write_locks == {}

    def test_a_change_to_the_same_key_waits_for_the_copy(self, perfecto_token, monkeypatch):
        store = _FakeStore()
        store.edit_elsewhere(_texts_script("original"))
        monkeypatch.setattr(persistence, "api_request", store.api_request)

        async def both():
            copying = asyncio.create_task(persistence.copy_script(perfecto_token, ITEM, ITEM))
            await asyncio.sleep(0)
            await load_and_mutate(perfecto_token, ITEM, _adding("after"))
            await copying

        asyncio.run(both())

        assert _texts(store.sent[-1]) == ["original", "after"]

    def test_settings_are_read_once_for_the_whole_copy(self, perfecto_token, monkeypatch):
        from tools.ai_scriptless import endpoints

        answers = iter([(True, True), (False, False), (False, False)])

        async def changing(_token):
            return next(answers)

        store = _FakeStore()
        store.edit_elsewhere(_texts_script("original"))
        seen = []

        async def recording(token, method, endpoint=None, **kwargs):
            seen.append(endpoint)
            return await store.api_request(token, method, endpoint, **kwargs)

        monkeypatch.setattr(endpoints, "read_scriptless_settings", changing)
        monkeypatch.setattr(persistence, "api_request", recording)

        asyncio.run(persistence.copy_script(perfecto_token, ITEM, self.OTHER))

        assert seen and all("script-asset-manager" in endpoint for endpoint in seen)

    def test_copies_running_opposite_ways_do_not_wait_on_each_other(self, perfecto_token, monkeypatch):
        store = _FakeStore()
        store.edit_elsewhere(_texts_script("original"))
        monkeypatch.setattr(persistence, "api_request", store.api_request)

        async def both():
            await asyncio.wait_for(asyncio.gather(
                persistence.copy_script(perfecto_token, ITEM, self.OTHER),
                persistence.copy_script(perfecto_token, self.OTHER, ITEM),
            ), timeout=2)

        asyncio.run(both())

        assert persistence._script_write_locks == {}


class TestEmptyReads:
    """A read without the test's content is never built on, copied or taken as confirmation."""

    @staticmethod
    def _answering(monkeypatch, read_answer) -> list:
        writes = []

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if method == "GET":
                return BaseResult(result=copy.deepcopy(read_answer))
            writes.append(endpoint)
            if "script-draft-repository" in endpoint:
                return BaseResult(result={"key": "draft-1"})
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)
        return writes

    @pytest.mark.parametrize("answer", [{"script": None}, {"script": {}}, {}, None])
    def test_change_is_not_built_on_a_read_without_content(self, perfecto_token, monkeypatch, answer):
        writes = self._answering(monkeypatch, answer)

        result = asyncio.run(load_and_mutate(perfecto_token, ITEM, _adding("first")))

        assert result.error == ("Could not read the test (the service answered without the test's content), "
                                "so it was not changed.")
        assert writes == []

    @pytest.mark.parametrize("answer", [{"script": None}, {"script": {}}, {}])
    def test_copy_is_not_made_from_a_read_without_content(self, perfecto_token, monkeypatch, answer):
        writes = self._answering(monkeypatch, answer)

        result = asyncio.run(persistence.copy_script(perfecto_token, ITEM, "PRIVATE:Folder/Copy.xml"))

        assert "nothing was saved" in result.error
        assert writes == []

    def test_empty_read_back_does_not_confirm_an_empty_save(self, perfecto_token, monkeypatch):
        self._answering(monkeypatch, {"script": {}})

        result = asyncio.run(persist_script(perfecto_token, ITEM, {}))

        assert result.error is None
        assert "the answer held no script" in " ".join(result.warning)


def _texts_script(*texts: str) -> dict:
    script = new_empty_script()
    script["flowElements"] = [build_flow_element("comment", {"text": text}) for text in texts]
    return script


class TestScriptWriteLock:
    """One lock per user, cloud and script, kept only while someone holds or waits for it."""

    ALICE = ("cloud-one", "alice-owner")
    BOB = ("cloud-one", "bob-owner")
    ALICE_ELSEWHERE = ("cloud-two", "alice-owner")

    @staticmethod
    async def _second_waits(first: tuple, second: tuple) -> bool:
        holding, release = asyncio.Event(), asyncio.Event()

        async def hold():
            async with persistence.script_write_lock(*first, ITEM):
                holding.set()
                await release.wait()

        async def enter_and_leave():
            async with persistence.script_write_lock(*second, ITEM):
                pass

        holder = asyncio.create_task(hold())
        await asyncio.wait_for(holding.wait(), timeout=1.0)
        try:
            await asyncio.wait_for(enter_and_leave(), timeout=0.2)
            waited = False
        except asyncio.TimeoutError:
            waited = True
        release.set()
        await holder
        return waited

    def test_same_user_and_script_wait_for_each_other(self):
        assert asyncio.run(self._second_waits(self.ALICE, self.ALICE)) is True
        assert persistence._script_write_locks == {}

    def test_other_user_with_the_same_item_key_does_not_wait(self):
        assert asyncio.run(self._second_waits(self.ALICE, self.BOB)) is False
        assert persistence._script_write_locks == {}

    def test_same_user_on_another_cloud_does_not_wait(self):
        assert asyncio.run(self._second_waits(self.ALICE, self.ALICE_ELSEWHERE)) is False
        assert persistence._script_write_locks == {}

    def test_cloud_names_differing_in_case_share_one_lock(self):
        assert asyncio.run(self._second_waits(("Cloud-One", "alice-owner"), ("cloud-one", "alice-owner"))) is True
        assert persistence._script_write_locks == {}

    def test_entry_is_removed_after_release_even_on_error(self):
        async def fail_inside():
            async with persistence.script_write_lock(*self.ALICE, ITEM):
                raise ValueError("boom")

        try:
            asyncio.run(fail_inside())
        except ValueError:
            pass

        assert persistence._script_write_locks == {}


class TestScriptLockOwner:
    """The lock belongs to the user Perfecto reports for the token, never to the token."""

    TOKEN = PerfectoToken("synthetic-token-value", "cloud-one")
    USERNAME = "alice@example.test"

    def _users(self, monkeypatch, answer: BaseResult) -> list:
        calls = []

        async def fake_api_request(_token, method, endpoint=None, **_kwargs):
            calls.append((method, endpoint))
            return answer

        monkeypatch.setattr(persistence, "api_request", fake_api_request)
        return calls

    def test_owner_is_the_hashed_username_from_the_current_user(self, monkeypatch):
        calls = self._users(monkeypatch, BaseResult(result={"username": self.USERNAME}))

        owner = asyncio.run(REAL_LOCK_OWNER(self.TOKEN, ITEM))

        assert owner.error is None
        assert owner.result == hashlib.sha256(self.USERNAME.encode("utf-8")).hexdigest()
        assert calls == [("GET", "https://cloud-one.app.perfectomobile.com"
                                 "/user-management-webapp/rest/v1/user-management/current")]

    def test_same_user_with_another_token_gets_the_same_owner(self, monkeypatch):
        self._users(monkeypatch, BaseResult(result={"username": self.USERNAME}))

        first = asyncio.run(REAL_LOCK_OWNER(self.TOKEN, ITEM))
        second = asyncio.run(REAL_LOCK_OWNER(PerfectoToken("another-token-value", "cloud-one"), ITEM))

        assert first.result == second.result

    def test_public_and_group_tests_share_one_lock_without_a_lookup(self, monkeypatch):
        calls = self._users(monkeypatch, BaseResult(result={"username": self.USERNAME}))

        public = asyncio.run(REAL_LOCK_OWNER(self.TOKEN, "PUBLIC:Folder/Test.xml"))
        other = asyncio.run(REAL_LOCK_OWNER(PerfectoToken("another-token-value", "cloud-one"),
                                            "PUBLIC:Folder/Test.xml"))
        group = asyncio.run(REAL_LOCK_OWNER(self.TOKEN, "GROUP:Folder/Test.xml"))

        assert public.result == other.result == group.result == persistence.SHARED_SCRIPT_OWNER
        assert calls == []

    def test_two_users_wait_for_each_other_on_a_public_test(self, monkeypatch):
        async def both():
            owner_one = await REAL_LOCK_OWNER(self.TOKEN, "PUBLIC:Folder/Test.xml")
            owner_two = await REAL_LOCK_OWNER(PerfectoToken("another-token-value", "cloud-one"),
                                              "PUBLIC:Folder/Test.xml")
            return await TestScriptWriteLock._second_waits(
                ("cloud-one", owner_one.result), ("cloud-one", owner_two.result))

        assert asyncio.run(both()) is True
        assert persistence._script_write_locks == {}

    def test_lookup_error_is_returned(self, monkeypatch):
        self._users(monkeypatch, BaseResult(error="Invalid credentials"))

        assert asyncio.run(REAL_LOCK_OWNER(self.TOKEN, ITEM)).error == "Invalid credentials"

    def test_answer_without_username_is_an_error(self, monkeypatch):
        self._users(monkeypatch, BaseResult(result={"firstName": "Alice"}))

        assert "Could not read the current Perfecto user" in asyncio.run(REAL_LOCK_OWNER(self.TOKEN, ITEM)).error

    def test_write_is_not_made_when_the_owner_is_unknown(self, monkeypatch):
        async def no_owner(_token, _item_key):
            return BaseResult(error="Invalid credentials")

        calls = self._users(monkeypatch, BaseResult(result={"script": new_empty_script()}))
        monkeypatch.setattr(persistence, "script_lock_owner", no_owner)

        saved = asyncio.run(persist_script(self.TOKEN, ITEM, new_empty_script()))
        changed = asyncio.run(load_and_mutate(self.TOKEN, ITEM, _adding("first")))

        assert saved.error == changed.error == "Invalid credentials"
        assert calls == []

    def test_lock_table_holds_neither_token_nor_username_during_a_write(self, monkeypatch):
        seen = []

        async def fake_api_request(_token, method, endpoint=None, **_kwargs):
            if "user-management" in endpoint:
                return BaseResult(result={"username": self.USERNAME})
            seen.append(repr(persistence._script_write_locks))
            if method == "GET":
                return BaseResult(result={"script": new_empty_script()})
            if "script-draft-repository" in endpoint:
                return BaseResult(result={"key": "draft-1"})
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)
        monkeypatch.setattr(persistence, "script_lock_owner", REAL_LOCK_OWNER)

        asyncio.run(load_and_mutate(self.TOKEN, ITEM, _adding("first")))

        assert seen and all(ITEM in table for table in seen)
        assert not any(self.TOKEN.token in table or self.USERNAME in table for table in seen)
        assert persistence._script_write_locks == {}
