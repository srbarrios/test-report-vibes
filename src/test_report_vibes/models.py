"""Pydantic data models for Cucumber JSON parsing and issue representation."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class StepResult(BaseModel):
    """Result of a test step execution."""

    status: Literal["passed", "failed", "skipped", "pending", "undefined"]
    duration: Optional[int] = None
    error_message: Optional[str] = None


class Embedding(BaseModel):
    """Embedded content in a step (typically screenshots)."""

    mime_type: str
    data: str  # base64 encoded


class HookMatch(BaseModel):
    """Match information for a hook or step definition."""

    location: Optional[str] = None


class HookEntry(BaseModel):
    """A before/after hook execution."""

    match: Optional[HookMatch] = None
    result: Optional[StepResult] = None

    embeddings: List["Embedding"] = Field(default_factory=list)
    output: List[str] = Field(default_factory=list)


class StepMatch(BaseModel):
    """Match information for a step definition."""

    location: Optional[str] = None


class Step(BaseModel):
    """A single step in a Cucumber scenario."""

    keyword: str
    name: str
    line: Optional[int] = None
    result: StepResult
    match: Optional[StepMatch] = None
    output: List[str] = Field(default_factory=list)
    embeddings: List[Embedding] = Field(default_factory=list)
    after: List[HookEntry] = Field(default_factory=list)


class Tag(BaseModel):
    """A Cucumber tag."""

    name: str
    line: Optional[int] = None


class Scenario(BaseModel):
    """A Cucumber scenario (test case)."""

    id: Optional[str] = None
    name: str
    keyword: str
    description: Optional[str] = None
    type: str
    line: Optional[int] = None
    steps: List[Step] = Field(default_factory=list)
    tags: List[dict] = Field(default_factory=list)
    before: List[HookEntry] = Field(default_factory=list)
    after: List[HookEntry] = Field(default_factory=list)


class Feature(BaseModel):
    """A Cucumber feature file."""

    uri: str
    id: str
    name: str
    keyword: str
    description: Optional[str] = None
    line: Optional[int] = None
    elements: List[Scenario]  # Cucumber uses 'elements' for scenarios
    tags: List[dict] = Field(default_factory=list)


class FilteredStepContext(BaseModel):
    """A step within a failed scenario, providing full context."""

    keyword: str
    name: str
    status: str
    line: Optional[int] = None
    location: Optional[str] = None
    duration: Optional[int] = None
    error_message: Optional[str] = None
    output: List[str] = Field(default_factory=list)
    embeddings_count: int = 0


class FilteredIssue(BaseModel):
    """Represents a single issue (failed/undefined step) to send to LLM."""

    feature_name: str
    feature_uri: str
    feature_description: Optional[str] = None
    feature_tags: List[str] = Field(default_factory=list)
    feature_line: Optional[int] = None
    scenario_name: str
    scenario_id: str
    scenario_description: Optional[str] = None
    scenario_tags: List[str] = Field(default_factory=list)
    scenario_line: Optional[int] = None
    step_keyword: str
    step_name: str
    step_line: Optional[int] = None
    step_location: Optional[str] = None
    step_duration: Optional[int] = None
    status: Literal["failed", "pending", "undefined"]
    error_message: Optional[str] = None
    screenshots: List[str] = Field(default_factory=list)  # base64 image data
    all_steps: List[FilteredStepContext] = Field(default_factory=list)
    before_hooks: List[str] = Field(default_factory=list)  # hook locations
    after_hooks: List[str] = Field(default_factory=list)  # hook locations
