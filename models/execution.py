from typing import List, Any, Optional

from pydantic import BaseModel, Field


class ExecutionPlatform(BaseModel):
    platform_name: Optional[str] = Field(description="Platform name of the execution, also know as DeviceType")
    device_id: Optional[str] = Field(description="Device IDs of the execution")
    model: Optional[str] = Field(description="Device Model Name of the execution")
    os: Optional[str] = Field(description="OS name of the execution")
    os_version: Optional[str] = Field(description="OS version of the execution")
    browser: dict[str, Any] = Field(description="Browsers of the execution")


class Execution(BaseModel):
    test_id: str = Field(description="Unique identifier of the report")
    test_name: str = Field(description="Name of the test also know as report name")
    execution_id: str = Field(description="Unique identifier of the execution")
    execution_url: str = Field(description="URL of the report")
    start_time: str = Field(description="Start time of the test")
    end_time: str = Field(description="End time of the test")
    status: str = Field(description="Execution status")
    job_id: Optional[int] = Field(description="Unique identifier of the job", default=None)
    job_name: Optional[str] = Field(description="Name of the job", default=None)
    tags: List[str] = Field(description="Tags of the execution")
    framework: Optional[str] = Field(description="Automation Framework of the execution", default=None)
    platforms: List[ExecutionPlatform] = Field(description="Platforms of the execution")
    failure_reason: dict[str, Any] = Field(description="Failure reason of the execution")
    error_analysis: dict[str, Any] = Field(description="Error analysis of the execution")
