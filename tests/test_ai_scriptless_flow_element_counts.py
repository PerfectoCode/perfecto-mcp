"""
numOfFlowElements on nested containers (Branch, LogicalStep, Loop, IfStatement).

Perfecto wire format (observed on beta API):
- Script / LogicalStep / Loop / Branch: len(flowElements)
- IfStatement: 3 + direct children across all branches (not recursive)
- Leaf Action/Validation: no numOfFlowElements field
"""

from __future__ import annotations

from tools.ai_scriptless.elements import (
    build_flow_element,
    build_if_statement,
    build_logical_step,
    build_loop,
    new_empty_script,
)
from tools.ai_scriptless.tree import (
    delete_element_by_path,
    insert_flow_element,
    update_flow_element_counts,
)


def _comment(text: str) -> dict:
    return build_flow_element("comment", {"text": text})


class TestNestedFlowElementCounts:
    def test_empty_if_statement_counts(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        update_flow_element_counts(script)
        ifs = script["flowElements"][0]
        assert ifs["numOfFlowElements"] == 3
        assert ifs["branches"][0]["numOfFlowElements"] == 0
        assert ifs["branches"][0]["empty"] is True

    def test_insert_into_then_updates_branch_and_if_counts(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        insert_flow_element(script, _comment("a"), parent_path="0.b0")
        ifs = script["flowElements"][0]
        assert ifs["branches"][0]["numOfFlowElements"] == 1
        assert ifs["branches"][0]["empty"] is False
        assert ifs["numOfFlowElements"] == 4

    def test_insert_into_else_increments_if_count(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        insert_flow_element(script, _comment("else"), parent_path="0.b1")
        ifs = script["flowElements"][0]
        assert ifs["branches"][1]["numOfFlowElements"] == 1
        assert ifs["numOfFlowElements"] == 4

    def test_two_direct_then_children_gives_if_num_five(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        insert_flow_element(script, _comment("a"), parent_path="0.b0")
        insert_flow_element(script, _comment("b"), parent_path="0.b0")
        ifs = script["flowElements"][0]
        assert ifs["branches"][0]["numOfFlowElements"] == 2
        assert ifs["numOfFlowElements"] == 5

    def test_nested_if_counts_direct_child_only_not_recursive(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement("Outer")]
        inner = build_if_statement("Inner")
        insert_flow_element(script, inner, parent_path="0.b0")
        insert_flow_element(script, _comment("deep"), parent_path="0.b0.0.b0")
        outer = script["flowElements"][0]
        inner_ifs = outer["branches"][0]["flowElements"][0]
        assert outer["numOfFlowElements"] == 4
        assert outer["branches"][0]["numOfFlowElements"] == 1
        assert inner_ifs["numOfFlowElements"] == 4
        assert inner_ifs["branches"][0]["numOfFlowElements"] == 1

    def test_logical_step_count_matches_children(self):
        script = new_empty_script()
        group = build_logical_step("G")
        group["flowElements"] = [_comment("a"), build_loop(2)]
        script["flowElements"] = [group]
        update_flow_element_counts(script)
        assert group["numOfFlowElements"] == 2
        assert group["flowElements"][1]["numOfFlowElements"] == 0

    def test_delete_from_then_decrements_counts(self):
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        insert_flow_element(script, _comment("a"), parent_path="0.b0")
        insert_flow_element(script, _comment("b"), parent_path="0.b0")
        delete_element_by_path(script, "0.b0.0")
        ifs = script["flowElements"][0]
        assert ifs["branches"][0]["numOfFlowElements"] == 1
        assert ifs["numOfFlowElements"] == 4

    def test_parent_path_insert_updates_logical_step_count(self):
        script = new_empty_script()
        script["flowElements"] = [build_logical_step("G")]
        insert_flow_element(script, _comment("inside"), parent_path="0")
        group = script["flowElements"][0]
        assert group["numOfFlowElements"] == 1

    def test_leaf_actions_have_no_num_of_flow_elements(self):
        script = new_empty_script()
        insert_flow_element(script, _comment("x"))
        leaf = script["flowElements"][0]
        assert "numOfFlowElements" not in leaf or leaf.get("numOfFlowElements") is None

    def test_persist_prep_matches_perfecto_formula(self):
        """Simulate wrong counts; update_flow_element_counts repairs before persist."""
        script = new_empty_script()
        script["flowElements"] = [build_if_statement()]
        insert_flow_element(script, _comment("a"), parent_path="0.b0")
        insert_flow_element(script, _comment("b"), parent_path="0.b0")
        ifs = script["flowElements"][0]
        ifs["numOfFlowElements"] = 3
        ifs["branches"][0]["numOfFlowElements"] = 0
        update_flow_element_counts(script)
        assert ifs["numOfFlowElements"] == 5
        assert ifs["branches"][0]["numOfFlowElements"] == 2
