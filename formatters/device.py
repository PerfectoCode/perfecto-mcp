from typing import List, Any, Optional

from models.device import RealDevice, VirtualDevice


def format_real_device(devices: dict[str, Any], params: Optional[dict] = None) -> List[RealDevice]:
    formatted_devices = []
    for device in devices.keys():
        if "handset" in devices[device]:
            for d in devices[device]["handset"]:
                if d.get("available") == "true":  # Only available devices
                    formatted_devices.append(
                        RealDevice(
                            device_id=d.get("deviceId"),
                            appium_automation_name="Appium",
                            platform_name=d.get("os"),
                            platform_version=d.get("osVersion"),
                            manufacturer=d.get("manufacturer"),
                            model=d.get("model"),
                            location=d.get("location", ""),
                            description=d.get("description", ""),
                            status=d.get("status"),
                            in_use=d.get("inUse", "false"),  # When device is on error inUse is None
                        )
                    )
    return formatted_devices


def format_virtual_device(devices: dict[str, Any], params: Optional[dict] = None) -> List[VirtualDevice]:
    formatted_devices = []

    for d in devices["ios"]:
        formatted_devices.append(
            VirtualDevice(
                platform_name="iOS",
                platform_version=d.get("versions"),
                manufacturer=d.get("manufacturer"),
                model=d.get("model"),
                use_virtual_device=True
            )
        )
    for d in devices["android"]:
        formatted_devices.append(
            VirtualDevice(
                platform_name="Android",
                platform_version=d.get("versions"),
                manufacturer=d.get("manufacturer"),
                model=d.get("model"),
                use_virtual_device=True
            )
        )
    return formatted_devices
