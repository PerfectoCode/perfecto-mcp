from typing import List, Any, Optional

from models.grid import Grid


def format_grid_info(grids: dict[str, Any], params: Optional[dict] = None) -> List[Grid]:
    formatted_grids = [
        Grid(
            selenium_grid_url=grids.get("gridUrl"),
            selenium_grid_aws_region=grids.get("awsRegion"),
            selenium_grid_status={},
        )
    ]
    return formatted_grids