"""Errors with stable codes. Every refusal tells the agent what to do next."""
from __future__ import annotations

from typing import Any


class PipelineError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.details:
            out["details"] = self.details
        return out


# Stable error codes (documented in docs/v2/spec.md §5).
NO_PIPELINE = "NO_PIPELINE"
BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
BRIEF_NO_MANIFEST = "BRIEF_NO_MANIFEST"
BRIEF_VERSION = "BRIEF_VERSION"
BRIEF_INVALID = "BRIEF_INVALID"
PROJECT_MISMATCH = "PROJECT_MISMATCH"
ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
INVALID_STATE = "INVALID_STATE"
LEASED_BY_OTHER = "LEASED_BY_OTHER"
STYLE_NOT_LOCKED = "STYLE_NOT_LOCKED"
HEROES_NOT_APPROVED = "HEROES_NOT_APPROVED"
GATE_DUE = "GATE_DUE"
GATE_NOT_FOUND = "GATE_NOT_FOUND"
GATE_NOT_REVIEWED = "GATE_NOT_REVIEWED"
USER_SIGNOFF_REQUIRED = "USER_SIGNOFF_REQUIRED"
RETRY_BUDGET_SPENT = "RETRY_BUDGET_SPENT"
NO_CAUSE_CHANGE = "NO_CAUSE_CHANGE"
NOT_REVIEWED = "NOT_REVIEWED"
REASON_REQUIRED = "REASON_REQUIRED"
SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
WRONG_FORMAT = "WRONG_FORMAT"
NOTHING_CLAIMABLE = "NOTHING_CLAIMABLE"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
BUILD_FAILED = "BUILD_FAILED"      # a recipe did not compile (no attempt used)
UP_TO_DATE = "UP_TO_DATE"        # nothing changed since the last build; nothing to do
NO_RECIPE = "NO_RECIPE"          # the asset has no build entry in the brief
