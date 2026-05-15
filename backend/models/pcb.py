"""
PCB assembly data models.
Used for the PCB placement pipeline and the /api/pcb/* endpoints.
"""

from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class PCBBoundary(BaseModel):
    type: Literal["rectangle", "polygon"] = "rectangle"
    width: float = Field(..., description="Board width in mm")
    height: float = Field(..., description="Board height in mm")
    polygon_points: Optional[List[dict]] = Field(
        None, description="For polygon boundary: list of {x, y} points in mm"
    )


class FixedPart(BaseModel):
    designator: str = Field(..., description="Component reference designator")
    x: float = Field(..., description="Fixed X position in mm from board origin")
    y: float = Field(..., description="Fixed Y position in mm from board origin")
    side: Literal["top", "bottom"] = "top"
    rotation: float = Field(0.0, description="Component rotation in degrees")


class KeepOutZone(BaseModel):
    x: float
    y: float
    width: float
    height: float
    description: Optional[str] = None


class PCBConstraints(BaseModel):
    min_spacing: float = Field(0.5, description="Minimum spacing between components in mm")
    keep_out_zones: Optional[List[KeepOutZone]] = None


class PCBPlacementRequest(BaseModel):
    components: List[dict] = Field(..., description="Component list from BOM (schematic data)")
    boundary: PCBBoundary
    fixed_parts: Optional[List[FixedPart]] = Field(default_factory=list)
    constraints: Optional[PCBConstraints] = None


class PlacedComponent(BaseModel):
    designator: str
    x: float = Field(..., description="X position in mm from board origin")
    y: float = Field(..., description="Y position in mm from board origin")
    side: Literal["top", "bottom"] = "top"
    rotation: float = 0.0
    rationale: Optional[str] = Field(None, description="Why the placer chose this position")


class PCBPlacementResult(BaseModel):
    placed_components: List[PlacedComponent]
    notes: Optional[str] = None
    warnings: Optional[List[str]] = None
