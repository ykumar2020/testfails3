"""Shared execution status types for provider adapters and the runner."""
from __future__ import annotations

from enum import Enum


class CaseStatus(str, Enum):
    SUCCESS = "success"
    ASSERTION_FAILED = "assertion_failed"
    SCHEMA_VIOLATION = "schema_violation"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_ERROR = "authentication_error"
    BILLING_DEPLETED = "billing_depleted"
    TRANSPORT_TIMEOUT = "transport_timeout"
    TRANSPORT_ERROR = "transport_error"


COMPLETED_STATUSES = frozenset({
    CaseStatus.SUCCESS,
    CaseStatus.ASSERTION_FAILED,
})

