from typing import List, Any, Optional

from models.execution import Execution, ExecutionPlatform
from tools.utils import get_date_time_iso


def format_executions(executions: dict[str, Any], params: Optional[dict] = None) -> List[Execution]:
    cloud_name = params.get("cloud_name", "unknown")
    formatted_executions = []
    if "items" in executions:
        for item in executions["items"]:
            platforms = []
            for plat in item.get("platforms"):
                model = ""
                if "mobileInfo" in plat:
                    model = plat["mobileInfo"].get("model", "")
                platforms.append(
                    ExecutionPlatform(
                        device_id=plat.get("deviceId"),
                        model=model,
                        platform_name=plat.get("deviceType"),
                        os=plat.get("os"),
                        os_version=plat.get("osVersion"),
                        browser=plat.get("browserInfo", {}),
                    )
                )

            execution_url = f"https://{cloud_name}.app.perfectomobile.com/reporting/test/{item.get('id')}"

            failure_reason = item.get("failureReason", {})
            error_analysis = item.get("errorAnalysis", {})
            formatted_executions.append(
                Execution(
                    test_id=item.get("id"),
                    test_name=item.get("name"),
                    execution_id=item.get("testExecutionId"),
                    execution_url=execution_url,
                    start_time=get_date_time_iso(item.get("startTime", 0) / 1000),
                    end_time=get_date_time_iso(item.get("endTime", 0) / 1000),
                    status=item.get("status"),
                    job_id=item.get("job", {}).get("number", None),
                    job_name=item.get("job", {}).get("name", None),
                    tags=item.get("tags", []),
                    framework=item.get("automationFramework"),
                    platforms=platforms,
                    failure_reason=failure_reason,
                    error_analysis=error_analysis,
                )
            )
    return formatted_executions
