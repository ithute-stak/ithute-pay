"""Release-script safety invariants; executed on GitHub, never on the payment VPS."""
from pathlib import Path
import re
import unittest

SCRIPT = Path(__file__).with_name("pull-pay")
source = SCRIPT.read_text()

class DeployGuardTests(unittest.TestCase):
    def test_only_published_image(self):
        self.assertIn("ghcr.io/ithute-stak/ithute-pay:latest", source)
        self.assertIn('docker pull "$IMAGE"', source)
        self.assertNotRegex(source, r"(?m)^\s*(git pull|git fetch|git clone|docker build|pip install|pytest)\b")

    def test_keep_data_services_untouched(self):
        self.assertIn('up -d --no-deps --no-build --pull never --force-recreate "$SERVICE"', source)
        self.assertNotRegex(source, r"(?m)^\s*(docker\s+compose\s+down|docker\s+volume\s+rm|docker\s+system\s+prune)")
        self.assertIn('SERVICE="ithute-pay-bridge"', source)

    def test_pinned_release_image_is_overridden_last(self):
        self.assertIn('ARGS+=(-f "$OVERRIDE")', source)
        self.assertIn('image: ${IPB_IMAGE:?IPB_IMAGE must be set by the release launcher}', source)
        self.assertIn('export IPB_IMAGE="$OLD_IMAGE_ID"', source)
        self.assertIn('export IPB_IMAGE="$NEW_ID"', source)

    def test_previous_image_retained_for_rollback(self):
        self.assertIn('OLD_IMAGE_ID="$(docker inspect', source)
        self.assertIn('export IPB_IMAGE="$OLD_IMAGE_ID"', source)
        self.assertIn('trap rollback ERR', source)

    def test_production_health_required(self):
        self.assertIn('check_health ||', source)
        for indicator in ("PAY_HEALTH_URL", "PAY_API_URL", "PAY_PORTAL_URL", "healthy"):
            self.assertIn(indicator, source)

    def test_migrations_require_approval_and_backup(self):
        self.assertIn('PAY_APPROVE_MIGRATIONS:-no', source)
        self.assertIn("pg_dump", source)
        self.assertIn("alembic current --check", source)
        self.assertIn("alembic upgrade head", source)
        self.assertIn('RUN_MIGRATIONS_ON_START: "false"', source)

    def test_exclusive_lock(self):
        self.assertIn("flock -n 9", source)

if __name__ == "__main__":
    unittest.main()
