"""Detectors package: pure functions over TigerGraph query results that identify the
five documented fraud patterns plus shared_origin (R6/undocumented). See patterns.py."""

from src.detectors.patterns import (
    Finding,
    detect_card_testing,
    detect_cnp_burst,
    detect_new_device,
    detect_out_of_region,
    detect_account_takeover,
    detect_shared_origin,
)

__all__ = [
    "Finding",
    "detect_card_testing",
    "detect_cnp_burst",
    "detect_new_device",
    "detect_out_of_region",
    "detect_account_takeover",
    "detect_shared_origin",
]
