import base64
from pathlib import Path
from importlib import resources

TOOLS_PREFIX: str = "perfecto"
WEBSITE: str = "https://github.com/PerfectoCore/perfecto-mcp/"
GITHUB: str = "https://github.com/PerfectoCore/perfecto-mcp"
SUPPORT_MESSAGE: str = "If you think this is a bug, please contact Perfecto support or report issue at https://github.com/PerfectoCore/perfecto-mcp/issues"

SECURITY_TOKEN_FILE_ENV_NAME: str = "PERFECTO_SECURITY_TOKEN_FILE"
SECURITY_TOKEN_ENV_NAME: str = "PERFECTO_SECURITY_TOKEN"
PERFECTO_CLOUD_NAME_ENV_NAME: str = 'PERFECTO_CLOUD_NAME'

SECURITY_TOKEN_NOT_SET_MESSAGE: str = f"Perfecto Security Token not set. Set environment variable {SECURITY_TOKEN_FILE_ENV_NAME} or {SECURITY_TOKEN_ENV_NAME}"
PERFECTO_CLOUD_NAME_NOT_SET_MESSAGE: str = f"Perfecto Environment Cloud Name not set. Set environment variable {PERFECTO_CLOUD_NAME_ENV_NAME}"

def get_mcp_icon_uri():
    name = "app.png"
    try:
        icon_path = resources.files("../resources").joinpath(name)
        # print(icon_path)
    except Exception:
        icon_path = (Path(__file__).parent.parent / "resources" / name)
        # print(icon_path)

    # icon_path = Path(__file__).parent.parent / "app.png"
    icon_data = base64.standard_b64encode(icon_path.read_bytes()).decode()
    return f"data:image/png;base64,{icon_data}"

def get_tenant_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/tenant-management-webapp/rest/v1/tenant-management/tenants/current"


def get_user_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/user-management-webapp/rest/v1/user-management"


def get_real_device_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/api/v1/device-management/devices"


def get_execution_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.executions.perfectomobile.com/execution-manager/api/v1/executions"


def get_test_execution_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/test-execution-management-webapp/rest/v1/test-execution-management"


def get_test_execution_name_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/test-execution-management-webapp/rest/v1/metadata/search/testExecutionNames"


def get_test_execution_metadata_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/test-execution-management-webapp/rest/v1/metadata"


def get_report_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.app.perfectomobile.com/export/api/v3/test-executions"


def get_virtual_device_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.perfectomobile.com/vd/api/public/v1/supportedModels"


def get_web_desktop_management_api_url(cloud_name: str) -> str:
    return f"https://{cloud_name}.perfectomobile.com/web/api/v1/config/devices"

def get_real_devices_extended_commands_help_url() -> str:
    return "https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/perfecto_extensions.htm"

def get_real_devices_extended_command_base_help_url() -> str:
    return "https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/"