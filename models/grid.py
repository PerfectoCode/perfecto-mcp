from pydantic import BaseModel, Field


class Grid(BaseModel):
    selenium_grid_url: str = Field(description="The Selenium Grid URL")
    selenium_grid_aws_region: str = Field(description="The AWS Region")
    selenium_grid_status: dict = Field(description="The Selenium Grid Status")