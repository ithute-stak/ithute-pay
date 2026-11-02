"""Regression: live M-PESA verification references satisfy hardened provider contract."""

import re

from routers.mpesa_live_testing import _ids


def test_live_verification_references_meet_openapi_wire_limits():
    for operation in ("c2b", "b2c", "b2b", "authorization"):
        refs = [_ids(operation) for _ in range(100)]
        assert len({ref for ref, _, _ in refs}) == len(refs)
        for reference, third_party_reference, conversation_id in refs:
            assert re.fullmatch(r"[0-9A-Za-z_+ ]{1,20}", reference)
            assert re.fullmatch(r"[0-9A-Za-z_+ ]{1,40}", third_party_reference)
            assert re.fullmatch(r"[0-9A-Za-z_+ ]{1,40}", conversation_id)
