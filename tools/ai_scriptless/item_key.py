from dataclasses import dataclass
from typing import Any


VISIBILITY_UI_ROOT = {
    "PRIVATE": "My Tests",
    "PUBLIC": "Public Tests",
    "GROUP": "Group Tests",
}


@dataclass(frozen=True)
class ItemKey:
    value: str

    @classmethod
    def parse(cls, item_key: str) -> "ItemKey":
        visibility, _, path = item_key.partition(":")
        if not path:
            raise ValueError(f"Invalid itemKey format (expected VISIBILITY:path): {item_key}")
        return cls(item_key)

    @classmethod
    def build(cls, visibility: str, folder: str, name: str) -> "ItemKey":
        test_name = name if name.endswith(".xml") else f"{name}.xml"
        folder_path = folder.strip("/")
        if folder_path:
            return cls(f"{visibility}:{folder_path}/{test_name}")
        return cls(f"{visibility}:{test_name}")

    @property
    def visibility(self) -> str:
        return self.value.partition(":")[0]

    @property
    def path(self) -> str:
        _, _, path = self.value.partition(":")
        return path

    @property
    def file_name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder_path(self) -> str:
        path = self.path
        return path.rsplit("/", 1)[0] if "/" in path else ""

    @property
    def folder_type(self) -> str:
        return folder_type(self.visibility)

    def with_folder(self, folder: str, visibility: str) -> "ItemKey":
        return ItemKey.build(visibility, folder.strip("/"), self.file_name.removesuffix(".xml"))

    def __str__(self) -> str:
        return self.value


def build_item_key(visibility: str, folder: str, name: str) -> str:
    return str(ItemKey.build(visibility, folder, name))


def split_item_key(item_key: str) -> tuple[str, str]:
    parsed = ItemKey.parse(item_key)
    return parsed.visibility, parsed.path


def folder_type(visibility: str) -> str:
    if visibility in ("PRIVATE", "GROUP"):
        return visibility
    return "PUBLIC"


def item_key_file_name(item_key: str) -> str:
    return ItemKey.parse(item_key).file_name


def format_test_ui_location(item_key: str) -> str:
    """Map itemKey to folder/test labels shown in the AI Scriptless Open Test UI."""
    key = ItemKey.parse(item_key)
    root = VISIBILITY_UI_ROOT.get(key.visibility, key.visibility)
    file_name = key.file_name.removesuffix(".xml")
    if key.folder_path:
        return f'"{root}" → folder "{key.folder_path}" → test "{file_name}"'
    return f'"{root}" → test "{file_name}"'


def build_snapshot_search_body(test_id: str) -> dict[str, Any]:
    key = ItemKey.parse(test_id)
    return {
        "repositoryType": "SCRIPTS",
        "keyDetails": {"artifactId": key.path, "version": "v0"},
        "folderType": key.folder_type,
    }


def build_move_test_body(
        test_id: str,
        folder: str,
        visibility: str,
) -> dict[str, Any]:
    source = ItemKey.parse(test_id)
    target = source.with_folder(folder, visibility)
    return {
        "repositoryType": "SCRIPTS",
        "keyDetails": {"artifactId": source.path, "version": "v0"},
        "folderType": source.folder_type,
        "targetKeyDetails": {"artifactId": target.path, "version": "v0"},
        "targetFolderType": target.folder_type,
        "copy": False,
    }
