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
import json

from models.result import BaseResult
from config.token import PerfectoToken
from tools.ai_scriptless import persistence
from tools.ai_scriptless.elements import build_branch, build_flow_element, build_logical_step, new_empty_script
from tools.ai_scriptless.persistence import load_and_mutate, persist_script
from tools.ai_scriptless.tree import insert_flow_element
from tools.ai_scriptless.script import Script


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
        assert len(calls) == 2
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"].endswith("/script-draft-repository/draft")
        assert calls[1]["method"] == "POST"
        assert calls[1]["endpoint"].endswith("/script-repository/script")
        assert calls[1]["json"]["draftKey"] == "draft-abc"
        assert calls[1]["json"]["itemKey"] == "PRIVATE:Folder/Test.xml"

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


class TestLoadAndMutateAsyncMutator:
    """Mutators may be async when they need the API before mutating (command definitions)."""

    @staticmethod
    def _mock_script_io(monkeypatch, persisted: dict):
        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": new_empty_script()})

        async def fake_persist(_token, item_key, mutated_script, saved_script, snapshot_comment=None):
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
    """Keeps every save as a version and serves one, misbehaving the ways beta did."""

    def __init__(self):
        self.versions: list[dict] = [self._as_served(new_empty_script())]
        self.served = 0
        self.lag_reads = 0      # the next reads return the version before the served one
        self.lag_after_save = 0  # how many reads lag after each kept save
        self.drop_next = False  # the next save answers success and keeps nothing
        self.refuse = False     # saves answer HTTP 400
        self.rewrite = None     # applied to what is kept, the way beta drops or converts content
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
    """A read right after a save can return the version from before it (seen on beta)."""

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
        sent = new_empty_script()
        sent["flowElements"] = [build_flow_element("comment", {"text": "x"})]
        served = _FakeStore._as_served(sent)
        served["info"] = {"@type": "ScriptInfo", "modelVersion": "2.0"}
        served["numOfFlowElements"] = 1
        changed = copy.deepcopy(sent)
        changed["flowElements"].append(build_flow_element("comment", {"text": "y"}))

        assert persistence.script_fingerprint(served) == persistence.script_fingerprint(sent)
        assert persistence.script_fingerprint(changed) != persistence.script_fingerprint(sent)

    def test_content_stored_differently_is_named_in_the_warning(self, perfecto_token, monkeypatch):
        # Measured on beta: a field the service does not know is dropped, a number
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


class TestScriptWriteLock:
    """One lock per user, cloud and script, kept only while someone holds or waits for it."""

    ALICE = PerfectoToken("alice-token", "cloud-one")
    BOB = PerfectoToken("bob-token", "cloud-one")
    ALICE_ELSEWHERE = PerfectoToken("alice-token", "cloud-two")

    @staticmethod
    async def _second_waits(first: PerfectoToken, second: PerfectoToken) -> bool:
        holding, release = asyncio.Event(), asyncio.Event()

        async def hold():
            async with persistence.script_write_lock(first, ITEM):
                holding.set()
                await release.wait()

        async def enter_and_leave():
            async with persistence.script_write_lock(second, ITEM):
                pass

        holder = asyncio.create_task(hold())
        await holding.wait()
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

    def test_entry_is_removed_after_release_even_on_error(self):
        async def fail_inside():
            async with persistence.script_write_lock(self.ALICE, ITEM):
                raise ValueError("boom")

        try:
            asyncio.run(fail_inside())
        except ValueError:
            pass

        assert persistence._script_write_locks == {}

    def test_token_is_not_kept_in_the_key(self):
        async def look_inside():
            async with persistence.script_write_lock(self.ALICE, ITEM):
                return list(persistence._script_write_locks)

        keys = asyncio.run(look_inside())

        assert len(keys) == 1
        assert "alice-token" not in repr(keys)
