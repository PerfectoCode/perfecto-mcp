from pydantic import BaseModel, Field


class RealDevice(BaseModel):
    device_id: str = Field(description="Unique identifier of the device (capability=deviceName)")
    appium_automation_name: str = Field(description="Name of the appium automation (capability=appium:automationName)")
    platform_name: str = Field(description="The Platform Name (capability=platformName)")
    platform_version: str = Field(description="The Platform Version (capability=platformVersion)")
    manufacturer: str = Field(description="The Manufacturer (capability=manufacturer)")
    model: str = Field(description="The Model Name (capability=model)")
    location: str = Field(description="The Location Name (capability=location)")
    description: str = Field(description="The Device Description")
    status: str = Field(description="The Device Status")
    in_use: str = Field(description="Whether the device is in use")

class VirtualDevice(BaseModel):
    platform_name: str = Field(description="The Platform Name (capability=platformName)")
    platform_version: list[str] = Field(description="The Platform Version (capability=platformVersion)")
    manufacturer:str = Field(description="The Manufacturer (capability=manufacturer)")
    model:str = Field(description="The Model Name (capability=model)")
    use_virtual_device: bool = Field(description="The Use Virtual Device (capability=useVirtualDevice)")