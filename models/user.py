from pydantic import BaseModel, Field


class User(BaseModel):
    username: str = Field(description="The unique identifier for the user")
    display_name: str = Field(description="Display name of the user")
    first_name: str = Field(description="First name of the user")
    last_name: str = Field(description="Last name of the user")
    cloud_name: str = Field(description="Perfecto cloud name from MCP configuration (PERFECTO_CLOUD_NAME)")
    cloud_url: str = Field(description="Perfecto cloud portal URL (https://{cloud_name}.app.perfectomobile.com)")