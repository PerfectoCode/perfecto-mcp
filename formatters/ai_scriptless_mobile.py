from typing import List, Any, Optional


def format_ai_scriptless_mobile_tests_filter_values(tests: dict[str, Any], params: Optional[dict] = None) -> dict[str, Any]:
    filter_values = {
        "test_name": [],
        "owner_list": [],
    }

    for item_visibility in tests["items"]:
        stack_tests = list(item_visibility.get("items", []))
        while stack_tests:
            test = stack_tests.pop()
            node_type = test["type"]
            if node_type == "SIMPLE":
                test_name = test['name'].rstrip('.xml')
                if test_name not in filter_values["test_name"]:
                    filter_values["test_name"].append(test_name)
                if test['createdBy'] not in filter_values["owner_list"]:
                    filter_values["owner_list"].append(test['createdBy'])
                if test['modifiedBy'] not in filter_values["owner_list"]:
                    filter_values["owner_list"].append(test['modifiedBy'])
            elif node_type == "CONTAINER":
                stack_tests.extend(reversed(test.get("items", [])))
    return filter_values


def format_ai_scriptless_mobile_tests(tests: dict[str, Any], params: Optional[dict] = None) -> List[dict[str, Any]]:
    formatted_ai_scriptless_mobile_tests = []
    filters = params.get("filters", {})
    page_size = params["page_size"]
    skip = params["skip"]
    offset = skip + page_size

    for item_visibility in tests["items"]:
        visibility = item_visibility["visibility"]
        if "visibility" in filters and visibility != filters.get("visibility"):
            continue
        stack_tests = list(item_visibility.get("items", []))
        while stack_tests:
            test = stack_tests.pop()
            node_type = test["type"]
            if node_type == "SIMPLE":
                if "test_name" in filters and filters["test_name"].lower() not in test["name"].lower():
                    continue
                if "owner_list" in filters and test['createdBy'] not in filters.get('owner_list', []):
                    continue
                test_formatted = f"id:{test['key']} name:{test['name'].rstrip('.xml')} created[user:{test['createdBy']} date:{test['creationTime']['formatted']}] modified[user:{test['modifiedBy']} date:{test['modificationTime']['formatted']}]"
                formatted_ai_scriptless_mobile_tests.append(test_formatted)
            elif node_type == "CONTAINER":
                stack_tests.extend(reversed(test.get("items", [])))

            if len(formatted_ai_scriptless_mobile_tests) > offset:
                break

    if len(formatted_ai_scriptless_mobile_tests) >= offset:
        offset = len(formatted_ai_scriptless_mobile_tests) - 1

    return formatted_ai_scriptless_mobile_tests[skip:offset]
