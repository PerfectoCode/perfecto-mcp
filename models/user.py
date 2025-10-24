from pydantic import BaseModel, Field


class User(BaseModel):
    username: str = Field(description="The unique identifier for the user")
    display_name: str = Field(description="Display name of the user")
    first_name: str = Field(description="First name of the user")
    last_name: str = Field(description="Last name of the user")