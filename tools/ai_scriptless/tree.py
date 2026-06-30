from typing import Any, Optional

from tools.ai_scriptless.step_path import StepPath, StepPathInput, coerce_step_path


CONTAINER_TYPES = frozenset({"LogicalStep", "Loop", "Branch"})


def _update_branch_container(branch: dict[str, Any]) -> None:
    children = branch.setdefault("flowElements", [])
    for child in children:
        _update_element_counts(child)
    count = len(children)
    branch["numOfFlowElements"] = count
    if "empty" in branch:
        branch["empty"] = count == 0


def _update_element_counts(element: dict[str, Any]) -> None:
    element_type = element.get("@type")
    if element_type == "IfStatement":
        branches = element.get("branches", [])
        direct_in_branches = 0
        for branch in branches:
            _update_branch_container(branch)
            direct_in_branches += len(branch.get("flowElements", []))
        # Perfecto: 3 + direct step count in Then/Else (nested steps count inside their own IfStatement).
        element["numOfFlowElements"] = 3 + direct_in_branches
    elif element_type in ("LogicalStep", "Loop"):
        children = element.setdefault("flowElements", [])
        for child in children:
            _update_element_counts(child)
        element["numOfFlowElements"] = len(children)
    elif element_type == "Branch":
        _update_branch_container(element)


def validate_step_path(step_path: str) -> None:
    StepPath.parse(step_path)


def find_step_path_for_element(script: dict[str, Any], target: dict[str, Any]) -> Optional[str]:
    def walk(
            flow_elements: list[dict[str, Any]],
            parent: Optional[StepPath],
    ) -> Optional[StepPath]:
        for index, element in enumerate(flow_elements):
            step_path = (
                StepPath.root_index(index)
                if parent is None
                else parent.child_index(index)
            )
            if element is target:
                return step_path
            nested = walk(element.get("flowElements", []), step_path)
            if nested:
                return nested
            if element.get("@type") == "IfStatement":
                for branch_index, branch in enumerate(element.get("branches", [])):
                    branch_path = step_path.branch(branch_index)
                    if branch is target:
                        return branch_path
                    nested = walk(branch.get("flowElements", []), branch_path)
                    if nested:
                        return nested
        return None

    located = walk(script.get("flowElements", []), None)
    return str(located) if located is not None else None


def find_element_by_path(
        script: dict[str, Any],
        step_path: StepPathInput,
) -> Optional[tuple[list[dict[str, Any]], int, dict[str, Any]]]:
    path = coerce_step_path(step_path)
    if path is None:
        return None
    parts = path.parts
    current_list = script.get("flowElements", [])
    parent_list: Optional[list[dict[str, Any]]] = None
    parent_index: Optional[int] = None
    current_element: Optional[dict[str, Any]] = None

    for part_index, part in enumerate(parts):
        is_last = part_index == len(parts) - 1

        if part.startswith("b"):
            if current_element is None or current_element.get("@type") != "IfStatement":
                return None
            branch_index = int(part[1:])
            branches = current_element.get("branches", [])
            if branch_index >= len(branches):
                return None
            if is_last:
                parent_list = branches
                parent_index = branch_index
                current_element = branches[branch_index]
            else:
                current_element = branches[branch_index]
                current_list = current_element.get("flowElements", [])
            continue

        index = int(part)
        if index >= len(current_list):
            return None
        if is_last:
            parent_list = current_list
            parent_index = index
            current_element = current_list[index]
        else:
            current_element = current_list[index]
            next_part = parts[part_index + 1]
            if not next_part.startswith("b"):
                current_list = current_element.get("flowElements", [])

    if current_element is None or parent_list is None or parent_index is None:
        return None
    return parent_list, parent_index, current_element


def find_container_by_path(script: dict[str, Any], step_path: StepPathInput) -> Optional[dict[str, Any]]:
    located = find_element_by_path(script, step_path)
    if located is None:
        return None
    _, _, element = located
    return element


def update_flow_element_counts(script: dict[str, Any]) -> None:
    for element in script.get("flowElements", []):
        _update_element_counts(element)
    script["numOfFlowElements"] = len(script.get("flowElements", []))


def insert_flow_element(
        script: dict[str, Any],
        element: dict[str, Any],
        after_path: StepPathInput = None,
        parent_path: StepPathInput = None,
) -> None:
    if parent_path:
        parent = find_container_by_path(script, parent_path)
        if parent is None:
            raise ValueError(f"parent_path not found: {parent_path}")
        if parent.get("@type") not in CONTAINER_TYPES:
            raise ValueError(
                f"parent_path must reference a container (LogicalStep, Loop, Branch): {parent_path}"
            )
        parent.setdefault("flowElements", []).append(element)
    elif after_path:
        located = find_element_by_path(script, after_path)
        if located is None:
            raise ValueError(f"after_path not found: {after_path}")
        elements, index, _ = located
        elements.insert(index + 1, element)
    else:
        script.setdefault("flowElements", []).append(element)
    update_flow_element_counts(script)


def delete_element_by_path(script: dict[str, Any], step_path: StepPathInput) -> None:
    located = find_element_by_path(script, step_path)
    if located is None:
        raise ValueError(f"step_path not found: {step_path}")
    elements, index, _ = located
    elements.pop(index)
    update_flow_element_counts(script)


def set_element_enabled(script: dict[str, Any], step_path: StepPathInput, enabled: bool) -> None:
    located = find_element_by_path(script, step_path)
    if located is None:
        raise ValueError(f"step_path not found: {step_path}")
    _, _, element = located
    element["active"] = enabled


def set_condition_expression(script: dict[str, Any], step_path: StepPathInput, expression: str) -> None:
    located = find_element_by_path(script, step_path)
    if located is None:
        raise ValueError(f"step_path not found: {step_path}")
    _, _, element = located
    if element.get("@type") != "IfStatement":
        raise ValueError(f"step_path must reference an IfStatement: {step_path}")
    element["expression"] = expression


def move_element_by_path(
        script: dict[str, Any],
        step_path: StepPathInput,
        after_path: StepPathInput = None,
        parent_path: StepPathInput = None,
) -> None:
    located = find_element_by_path(script, step_path)
    if located is None:
        raise ValueError(f"step_path not found: {step_path}")
    source_list, source_index, element = located
    source_list.pop(source_index)

    if parent_path:
        parent = find_container_by_path(script, parent_path)
        if parent is None:
            raise ValueError(f"parent_path not found: {parent_path}")
        if parent.get("@type") not in CONTAINER_TYPES:
            raise ValueError(
                f"parent_path must reference a container (LogicalStep, Loop, Branch): {parent_path}"
            )
        parent.setdefault("flowElements", []).append(element)
    elif after_path:
        target = find_element_by_path(script, after_path)
        if target is None:
            raise ValueError(f"after_path not found: {after_path}")
        target_list, target_index, _ = target
        if target_list is source_list and source_index < target_index:
            target_index -= 1
        target_list.insert(target_index + 1, element)
    else:
        script.setdefault("flowElements", []).append(element)
    update_flow_element_counts(script)
