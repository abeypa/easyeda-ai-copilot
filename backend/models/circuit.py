"""
Circuit data models — mirrors the TypeScript types in circuit.ts / lcsc.ts.
All structures must match what the frontend (Vue/assembleCircuit) expects.
"""

from __future__ import annotations
from typing import Any, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class ElkPoint(BaseModel):
    x: float
    y: float


# ---------------------------------------------------------------------------
# Pin
# ---------------------------------------------------------------------------

class Pin(BaseModel):
    pin_number: Union[int, str] = Field(..., description="Pin number (e.g. 1 or 'A1')")
    name: str = Field(..., description="Pin function name (e.g. 'VCC', 'GND', 'OUT')")
    signal_name: str = Field(
        ...,
        description=(
            "Net/signal name the pin is connected to. "
            "Must match the signal_name on the other end of the connection."
        ),
    )


# ---------------------------------------------------------------------------
# Block (sub-circuit grouping)
# ---------------------------------------------------------------------------

class Block(BaseModel):
    name: str = Field(..., description="Short unique block name, e.g. 'Amplifier'")
    description: str = Field(..., description="What this block does")
    next_block_names: List[str] = Field(
        default_factory=list,
        description="Names of blocks that this block feeds signal into",
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class CircuitMetadata(BaseModel):
    project_name: str = Field(..., description="Human-readable project name")
    description: str = Field(..., description="Short circuit description")


# ---------------------------------------------------------------------------
# Base component (no position)
# ---------------------------------------------------------------------------

class BaseComponent(BaseModel):
    """Base component model. Allows extra fields (e.g. _libraryUuid) for frontend use."""

    model_config = ConfigDict(extra='allow')

    designator: str = Field(..., description="Schematic reference designator, e.g. 'U1', 'R5'")
    value: str = Field(
        ...,
        description=(
            "Minimal value string. For passives: nominal value ('10k', '100nF'). "
            "For ICs: part name ('LM358'). ASCII only."
        ),
    )
    pins: List[Pin] = Field(default_factory=list, description="Pin list with signal assignments")
    block_name: str = Field(..., description="Which block this component belongs to")
    search_query: str = Field(
        ...,
        description="LCSC search query, e.g. '1k 0402 resistor' or 'LM358 SOIC-8'",
    )
    part_uuid: Optional[str] = Field(
        None,
        description="32-char hex LCSC part UUID (without hyphens), null if not yet resolved",
    )


# ---------------------------------------------------------------------------
# Component position
# ---------------------------------------------------------------------------

class ComponentPos(BaseModel):
    x: float
    y: float
    center: ElkPoint
    width: float
    height: float
    rotate: Optional[float] = 0.0


# ---------------------------------------------------------------------------
# Component with position (after layout)
# ---------------------------------------------------------------------------

class ComponentWithPos(BaseComponent):
    pos: ComponentPos


# ---------------------------------------------------------------------------
# ELK edge section (one segment of a routed wire)
# ---------------------------------------------------------------------------

class ElkEdgeSection(BaseModel):
    id: str
    startPoint: ElkPoint
    endPoint: ElkPoint
    bendPoints: Optional[List[ElkPoint]] = None
    incomingShape: Optional[str] = None
    outgoingShape: Optional[str] = None
    incomingSections: Optional[List[str]] = None
    outgoingSections: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# ELK edge (a routed wire between two components)
# ---------------------------------------------------------------------------

class ElkEdge(BaseModel):
    sources: List[str]
    targets: List[str]
    container: str
    sections: List[ElkEdgeSection]


# ---------------------------------------------------------------------------
# Block rectangle (visual bounding box for a block group)
# ---------------------------------------------------------------------------

class BlockRect(BaseModel):
    name: str
    description: str
    x: float
    y: float
    width: float
    height: float


# ---------------------------------------------------------------------------
# Net entry (for pins that have no direct routed wire)
# ---------------------------------------------------------------------------

class AddedNet(BaseModel):
    designator: str
    pin_number: Union[int, str]
    net: str


# ---------------------------------------------------------------------------
# Assembly options
# ---------------------------------------------------------------------------

class AssemblyOptions(BaseModel):
    centered: Optional[bool] = None


# ---------------------------------------------------------------------------
# CircuitBlocks — output of the Architect agent
# ---------------------------------------------------------------------------

class CircuitBlocks(BaseModel):
    metadata: CircuitMetadata
    blocks: List[Block]


# ---------------------------------------------------------------------------
# CircuitStruct — complete circuit definition (no positions)
# ---------------------------------------------------------------------------

class CircuitStruct(BaseModel):
    metadata: CircuitMetadata
    blocks: List[Block]
    components: List[BaseComponent]


# ---------------------------------------------------------------------------
# CircuitAssembly — full positioned output sent to the frontend
# ---------------------------------------------------------------------------

class CircuitAssembly(BaseModel):
    metadata: CircuitMetadata
    components: List[ComponentWithPos]
    edges: List[ElkEdge]
    blocks: List[Block]
    blocks_rect: Optional[List[BlockRect]] = None
    assembly_options: Optional[AssemblyOptions] = None
    added_net: Optional[List[AddedNet]] = None
    rm_components: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Error entry (per-component pipeline errors)
# ---------------------------------------------------------------------------

class CircuitError(BaseModel):
    component: str = Field(..., description="Component designator, e.g. 'U1'")
    error: str = Field(..., description="Human-readable error message")
    severity: str = Field("warning", description="'info', 'warning', or 'error'")


# ---------------------------------------------------------------------------
# Chat message shape (mirrors frontend ChatMessage)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # 'human' | 'ai'
    content: str
    options: dict = Field(default_factory=dict)
    isReady: bool = True
    thinking: Optional[str] = None
    checkpoint: Optional[str] = None
    attachments: Optional[List[Any]] = None


# ---------------------------------------------------------------------------
# LLM settings (sent by the frontend in every chat request)
# ---------------------------------------------------------------------------

class AgentModelSettings(BaseModel):
    model: Optional[str] = None
    reasoning: Optional[str] = None


class LLMSettings(BaseModel):
    provider: str = "openai"
    apiKey: Optional[str] = None
    base_url: Optional[str] = Field(None, alias="base-url")

    base: Optional[AgentModelSettings] = None
    chat: Optional[AgentModelSettings] = None
    block_diagram: Optional[AgentModelSettings] = Field(None, alias="block-diagram")
    circuit_explainer: Optional[AgentModelSettings] = Field(None, alias="circuit-explainer")
    circuit_maker: Optional[AgentModelSettings] = Field(None, alias="circuit-maker")
    completions: Optional[AgentModelSettings] = None
    completions_list: Optional[AgentModelSettings] = Field(None, alias="completions-list")
    diagnostic_algoritm: Optional[AgentModelSettings] = Field(None, alias="diagnostic-algoritm")
    pin_desc: Optional[AgentModelSettings] = Field(None, alias="pin-desc")
    lcsc_search: Optional[AgentModelSettings] = Field(None, alias="lcsc-search")
    lcsc_most_rel_catalog: Optional[AgentModelSettings] = Field(None, alias="lcsc-most-rel-catalog")
    tavily_api_key: Optional[str] = Field(None, alias="tavily-api-key")

    model_config = {"populate_by_name": True}

    def get_model_for_agent(self, agent_name: str, fallback: str = "gpt-4o-mini") -> str:
        """
        Return the configured model for a named agent.
        Falls back to base model, then to the provided fallback.
        """
        agent_map = {
            "chat": self.chat,
            "block-diagram": self.block_diagram,
            "circuit-maker": self.circuit_maker,
            "circuit-explainer": self.circuit_explainer,
            "lcsc-search": self.lcsc_search,
            "lcsc-most-rel-catalog": self.lcsc_most_rel_catalog,
            "pin-desc": self.pin_desc,
            "completions": self.completions,
            "completions-list": self.completions_list,
            "diagnostic-algoritm": self.diagnostic_algoritm,
        }
        agent_settings = agent_map.get(agent_name)
        if agent_settings and agent_settings.model:
            return agent_settings.model
        if self.base and self.base.model:
            return self.base.model
        return fallback


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    context: List[ChatMessage] = Field(default_factory=list)
    llmSettings: LLMSettings


class LCSCSearchRequest(BaseModel):
    query: str
    limit: int = 10


class LCSCStockRequest(BaseModel):
    components: List[BaseComponent]
    min_stock: int = Field(100, description="Minimum acceptable stock level")
