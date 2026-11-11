"""
Which service stores AI Scriptless tests on a cloud.

Two versions of Perfecto are in use at once. The older one keeps the test tree,
the tests and their drafts in native-automation-webapp; the newer one moved them
to the script asset manager of scriptless-mobile-engine. Two feature settings say
which one a cloud runs, and the Perfecto UI chooses its endpoints from them:

- the engine setting moves the test tree and the drafts;
- the engine and script repository settings together move reading, saving and
  deleting a test.

These rules are the UI's own (its selectors for the tree, draft, open, save and
delete endpoints). A setting that is missing, false or cannot be read means the
older version, so a cloud that predates the settings keeps working.

The settings are read again for every operation and not kept: one server process
serves many users and clouds, and a value kept in memory would outlive the request
that read it.
"""
from dataclasses import dataclass
from typing import Any, Optional

from config import perfecto
from config.token import PerfectoToken
from tools.utils import api_request

SCRIPTLESS_ENGINE_SETTING = "scriptless-mobile-ide.scriptless-mobile-engine.enabled"
SCRIPT_REPOSITORY_SETTING = "scriptless-mobile-ide.scriptless-mobile-engine.script-repository.enabled"
FEATURE_SETTINGS_CATEGORY = "ui"


@dataclass(frozen=True)
class ScriptEndpoints:
    tree_url: str
    draft_url: str
    script_url: str
    """Read (GET ?itemKey=) and save (POST)."""
    delete_url: str
    """DELETE ?itemKey=."""
    engine: bool
    script_repository: bool


def _enabled(setting: Any) -> bool:
    # The UI reads a BOOLEAN setting as true only when its value is "true" or true.
    value = setting.get("value") if isinstance(setting, dict) else None
    return value == "true" or value is True


async def read_scriptless_settings(token: PerfectoToken) -> tuple[bool, bool]:
    """(engine, script repository) for this user and cloud; (False, False) when unreadable."""
    try:
        result = await api_request(
            token,
            "GET",
            endpoint=perfecto.get_feature_settings_api_url(token.cloud_name),
            params={"category": FEATURE_SETTINGS_CATEGORY},
        )
    except Exception:
        return False, False
    if result.error or not isinstance(result.result, list):
        return False, False
    settings = {
        setting.get("name"): setting
        for setting in result.result
        if isinstance(setting, dict)
    }
    engine = _enabled(settings.get(SCRIPTLESS_ENGINE_SETTING))
    script_repository = engine and _enabled(settings.get(SCRIPT_REPOSITORY_SETTING))
    return engine, script_repository


def endpoints_for(cloud_name: str, engine: bool, script_repository: bool) -> ScriptEndpoints:
    native = perfecto.get_ai_scriptless_api_url(cloud_name)
    asset = perfecto.get_ai_scriptless_script_asset_api_url(cloud_name)
    script_repository = engine and script_repository
    return ScriptEndpoints(
        tree_url=asset + "/script-directory-repository/tree" if engine else native + "/scripts/tree",
        draft_url=(
            asset + "/script-draft-repository/draft"
            if engine else perfecto.get_ai_scriptless_draft_api_url(cloud_name)
        ),
        script_url=asset + "/script-repository/script" if script_repository else native + "/script",
        # The asset manager deletes through the script resource itself; the older
        # service has a separate /repositories path.
        delete_url=asset + "/script-repository/script" if script_repository else native + "/repositories",
        engine=engine,
        script_repository=script_repository,
    )


async def script_endpoints(token: PerfectoToken, known: Optional[ScriptEndpoints] = None) -> ScriptEndpoints:
    """The endpoints for this cloud; ``known`` is reused when the caller already read them."""
    if known is not None:
        return known
    engine, script_repository = await read_scriptless_settings(token)
    return endpoints_for(token.cloud_name, engine, script_repository)
