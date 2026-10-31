"""Fail-closed release guard for uncertified Golink payment routing.

These tests must be changed only alongside verified sandbox evidence and a
separate activation review. They are not proof of certification by themselves.
"""
from pathlib import Path

from integrations.registry import PROVIDER_BUILDERS
from providers.golink.additional_rails import PHASE5_RAILS, RAIL_CERTIFICATION
from providers.golink.client import GolinkClient


def test_uncertified_rails_cannot_be_mistaken_for_release_ready():
    assert all(not any(flags.values()) for flags in RAIL_CERTIFICATION.values())
    assert set(RAIL_CERTIFICATION) == PHASE5_RAILS
    assert "golink" not in PROVIDER_BUILDERS


def test_certification_document_requires_actual_sandbox_evidence():
    doc = (Path(__file__).resolve().parents[3] / "docs" /
           "GOLINK_SANDBOX_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "successful read-only GET probe" in doc
    assert "sandbox DEBIT initiation/confirmation" in doc
    assert "explicit owner authorization" in doc
    assert "disabled for live routing" in doc


def test_sandbox_client_remains_read_only_until_explicit_operation():
    client = GolinkClient("glk_test_not_a_real_key")
    assert client.environment == "sandbox"
    assert client.base_url.startswith("https://sandbox.")
