"""
IfStatement tree contract: branches[] vs thenClause/elseClause.

Documents failure modes without normalization and expected behavior after
normalize_if_statement_aliases + tree mutations.
"""

from __future__ import annotations

import asyncio
import copy

import pytest

from formatters.ai_scriptless import _format_root_flow_elements, format_test_structure
from models.result import BaseResult
from tools.ai_scriptless import persistence
from tools.ai_scriptless.elements import (
    build_branch,
    build_flow_element,
    build_if_statement,
    build_logical_step,
    new_empty_script,
    normalize_if_statement_aliases,
    strip_non_api_script_fields,
)
from tools.ai_scriptless.persistence import _persist_script
from tools.ai_scriptless.tree import (
    delete_element_by_path,
    find_element_by_path,
    find_step_path_for_element,
    insert_flow_element,
    move_element_by_path,
)


def _comment(text: str) -> dict:
    return build_flow_element("comment", {"text": text})


def _api_style_if_statement(
        *,
        then_in_branch: list | None = None,
        then_in_clause: list | None = None,
        else_in_branch: list | None = None,
        else_in_clause: list | None = None,
        label: str = "API",
) -> dict:
    """Perfecto-like payload: branches and clauses are separate objects."""
    then_branch = build_branch("THEN")
    else_branch = build_branch("ELSE")
    then_clause = build_branch("THEN")
    else_clause = build_branch("ELSE")
    if then_in_branch is not None:
        then_branch["flowElements"] = list(then_in_branch)
    if then_in_clause is not None:
        then_clause["flowElements"] = list(then_in_clause)
    if else_in_branch is not None:
        else_branch["flowElements"] = list(else_in_branch)
    if else_in_clause is not None:
        else_clause["flowElements"] = list(else_in_clause)
    return {
        "@type": "IfStatement",
        "branches": [then_branch, else_branch],
        "thenClause": then_clause,
        "elseClause": else_clause,
        "label": label,
        "active": True,
    }


def _script_with_if_statement(ifs: dict) -> dict:
    script = new_empty_script()
    script["flowElements"] = [ifs]
    return script


def _then_child_commands(ifs: dict) -> list[str | None]:
    return [
        el.get("command")
        for el in ifs["branches"][0].get("flowElements", [])
    ]


def _clause_child_commands(ifs: dict) -> list[str | None]:
    return [
        el.get("command")
        for el in ifs["thenClause"].get("flowElements", [])
    ]


class TestIfStatementBuilderContract:
    def test_new_builder_aliases_clauses_to_branches(self):
        ifs = build_if_statement("Check")
        assert ifs["thenClause"] is ifs["branches"][0]
        assert ifs["elseClause"] is ifs["branches"][1]

    def test_mutation_through_branch_updates_clause(self):
        ifs = build_if_statement()
        ifs["branches"][0]["flowElements"].append(_comment("a"))
        assert len(ifs["thenClause"]["flowElements"]) == 1


class TestIfStatementWithoutNormalize:
    """Documents broken or inconsistent behavior when API payload is not normalized."""

    def test_insert_into_then_branch_does_not_update_then_clause(self):
        ifs = _api_style_if_statement()
        script = _script_with_if_statement(ifs)
        insert_flow_element(script, _comment("orphan"), parent_path="0.b0")
        assert len(ifs["branches"][0]["flowElements"]) == 1
        assert len(ifs["thenClause"]["flowElements"]) == 0

    def test_formatter_reads_branches_not_clauses(self):
        ifs = _api_style_if_statement(
            then_in_clause=[_comment("only in clause")],
        )
        script = _script_with_if_statement(ifs)
        formatted = _format_root_flow_elements(script["flowElements"], {})
        then_branch = formatted[0].children[0]
        assert then_branch.children == []

    def test_find_step_path_ignores_then_clause_object(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("c")])
        script = _script_with_if_statement(ifs)
        assert find_step_path_for_element(script, ifs["thenClause"]) is None

    def test_deepcopy_breaks_nothing_if_already_aliased(self):
        ifs = build_if_statement()
        ifs["branches"][0]["flowElements"].append(_comment("x"))
        copied = copy.deepcopy(_script_with_if_statement(ifs))
        condition = copied["flowElements"][0]
        assert condition["thenClause"] is condition["branches"][0]
        assert len(condition["thenClause"]["flowElements"]) == 1

    def test_deepcopy_keeps_duplicate_trees_separate(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("c")])
        copied = copy.deepcopy(_script_with_if_statement(ifs))
        condition = copied["flowElements"][0]
        assert condition["thenClause"] is not condition["branches"][0]
        assert len(condition["branches"][0]["flowElements"]) == 0
        assert len(condition["thenClause"]["flowElements"]) == 1


class TestNormalizeIfStatementAliases:
    def test_syncs_children_from_then_clause_when_branch_empty(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("from clause")])
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        assert ifs["thenClause"] is ifs["branches"][0]
        assert _then_child_commands(ifs) == ["comment"]

    def test_syncs_children_from_else_clause_when_branch_empty(self):
        ifs = _api_style_if_statement(else_in_clause=[_comment("else")])
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        assert ifs["elseClause"] is ifs["branches"][1]
        assert len(ifs["branches"][1]["flowElements"]) == 1

    def test_prefers_branch_when_both_have_same_length_different_children(self):
        ifs = _api_style_if_statement(
            then_in_branch=[_comment("branch wins")],
            then_in_clause=[_comment("clause loses")],
        )
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        texts = [
            el["arguments"][0]["data"]["value"]
            for el in ifs["branches"][0]["flowElements"]
        ]
        assert texts == ["branch wins"]
        assert ifs["thenClause"] is ifs["branches"][0]

    def test_prefers_clause_when_it_has_more_children(self):
        ifs = _api_style_if_statement(
            then_in_branch=[_comment("one")],
            then_in_clause=[_comment("one"), _comment("two")],
        )
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        assert len(ifs["branches"][0]["flowElements"]) == 2
        assert ifs["thenClause"] is ifs["branches"][0]

    def test_nested_if_inside_then_branch(self):
        inner = _api_style_if_statement(then_in_clause=[_comment("inner")])
        outer = build_if_statement("Outer")
        outer["branches"][0]["flowElements"] = [inner]
        outer["thenClause"] = build_branch("THEN")
        script = _script_with_if_statement(outer)
        normalize_if_statement_aliases(script)
        nested = outer["branches"][0]["flowElements"][0]
        assert nested["thenClause"] is nested["branches"][0]
        assert len(nested["branches"][0]["flowElements"]) == 1

    def test_nested_if_inside_logical_step(self):
        inner = _api_style_if_statement(then_in_clause=[_comment("deep")])
        group = build_logical_step("G")
        group["flowElements"] = [inner]
        script = new_empty_script()
        script["flowElements"] = [group]
        normalize_if_statement_aliases(script)
        nested = group["flowElements"][0]
        assert nested["thenClause"] is nested["branches"][0]


class TestIfStatementTreeAfterNormalize:
    @pytest.fixture
    def script(self) -> dict:
        ifs = _api_style_if_statement()
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        return script

    def test_insert_into_then_updates_clause(self, script: dict):
        insert_flow_element(script, _comment("step"), parent_path="0.b0")
        ifs = script["flowElements"][0]
        assert _then_child_commands(ifs) == ["comment"]
        assert _clause_child_commands(ifs) == ["comment"]

    def test_delete_from_then_clears_clause(self, script: dict):
        insert_flow_element(script, _comment("step"), parent_path="0.b0")
        delete_element_by_path(script, "0.b0.0")
        ifs = script["flowElements"][0]
        assert _then_child_commands(ifs) == []
        assert _clause_child_commands(ifs) == []

    def test_move_from_then_to_else(self, script: dict):
        insert_flow_element(script, _comment("movable"), parent_path="0.b0")
        move_element_by_path(script, "0.b0.0", parent_path="0.b1")
        ifs = script["flowElements"][0]
        assert _then_child_commands(ifs) == []
        assert [el.get("command") for el in ifs["branches"][1]["flowElements"]] == ["comment"]
        assert ifs["elseClause"] is ifs["branches"][1]

    def test_find_paths_after_insert(self, script: dict):
        insert_flow_element(script, _comment("step"), parent_path="0.b0")
        ifs = script["flowElements"][0]
        child = ifs["branches"][0]["flowElements"][0]
        assert find_step_path_for_element(script, child) == "0.b0.0"
        assert find_step_path_for_element(script, ifs["branches"][0]) == "0.b0"
        assert find_step_path_for_element(script, ifs["thenClause"]) == "0.b0"

    def test_find_element_round_trip(self, script: dict):
        insert_flow_element(script, _comment("step"), parent_path="0.b0")
        located = find_element_by_path(script, "0.b0.0")
        assert located is not None
        _, _, element = located
        assert element["command"] == "comment"

    def test_insert_nested_condition_in_then(self, script: dict):
        inner = build_if_statement("Inner")
        insert_flow_element(script, inner, parent_path="0.b0")
        nested = script["flowElements"][0]["branches"][0]["flowElements"][0]
        assert nested["thenClause"] is nested["branches"][0]
        insert_flow_element(script, _comment("deep"), parent_path="0.b0.0.b0")
        assert len(nested["branches"][0]["flowElements"]) == 1


class TestIfStatementPersistPreparation:
    def test_persist_deepcopy_keeps_alias_and_children(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "draft-management" in endpoint:
                return BaseResult(result={"key": "d1"})
            captured["save_script"] = kwargs["json"]["script"]
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        ifs = _api_style_if_statement()
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        insert_flow_element(script, _comment("persist me"), parent_path="0.b0")

        asyncio.run(
            _persist_script(perfecto_token, "PRIVATE:F/T.xml", script, script)
        )

        saved = captured["save_script"]["flowElements"][0]
        assert len(saved["branches"][0]["flowElements"]) == 1
        assert len(saved["thenClause"]["flowElements"]) == 1
        assert saved["branches"][0]["flowElements"][0]["command"] == "comment"

    def test_persist_renormalizes_branch_only_edits(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            if endpoint and "draft-management" in endpoint:
                return BaseResult(result={"key": "d1"})
            captured["save_script"] = kwargs["json"]["script"]
            return BaseResult(result={"status": "success"})

        monkeypatch.setattr(persistence, "api_request", fake_api_request)

        ifs = _api_style_if_statement()
        script = _script_with_if_statement(ifs)
        insert_flow_element(script, _comment("branch only"), parent_path="0.b0")
        assert len(ifs["thenClause"]["flowElements"]) == 0

        asyncio.run(
            _persist_script(perfecto_token, "PRIVATE:F/T.xml", script, script)
        )

        saved = captured["save_script"]["flowElements"][0]
        assert len(saved["thenClause"]["flowElements"]) == 1
        assert saved["thenClause"] is saved["branches"][0]

    def test_strip_non_api_fields_with_aliased_branches_is_safe(self):
        ifs = build_if_statement()
        ifs["branches"][0]["uuid"] = "remove-me"
        ifs["branches"][0]["flowElements"] = [_comment("x")]
        script = _script_with_if_statement(ifs)
        strip_non_api_script_fields(script)
        assert "uuid" not in ifs["branches"][0]
        assert len(ifs["thenClause"]["flowElements"]) == 1


class TestIfStatementFormatterAfterNormalize:
    def test_formatter_shows_then_children_after_normalize(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("visible")])
        script = _script_with_if_statement(ifs)
        normalize_if_statement_aliases(script)
        structure = format_test_structure({"script": script}, {"item_key": "PRIVATE:F/T.xml"})
        then_branch = structure.flow_elements[0].children[0]
        assert len(then_branch.children) == 1
        assert then_branch.children[0].command == "comment"

    def test_formatter_on_raw_api_payload_without_normalize_hides_clause_only_children(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("hidden")])
        script = _script_with_if_statement(ifs)
        formatted = _format_root_flow_elements(script["flowElements"], {})
        then_branch = formatted[0].children[0]
        assert then_branch.children == []

    def test_format_test_structure_normalizes_before_display(self):
        ifs = _api_style_if_statement(then_in_clause=[_comment("visible via normalize")])
        script = _script_with_if_statement(ifs)
        structure = format_test_structure({"script": script}, {"item_key": "PRIVATE:F/T.xml"})
        then_branch = structure.flow_elements[0].children[0]
        assert len(then_branch.children) == 1
