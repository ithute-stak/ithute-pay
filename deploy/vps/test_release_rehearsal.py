"""Offline end-to-end release-path rehearsal using disposable fake Docker processes.

No network, image pulls, production databases or real Docker needed.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64

MOCK_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
state_file = Path(os.environ["MOCK_STATE"])
s = json.loads(state_file.read_text())
def save():
    state_file.write_text(json.dumps(s))
def log(line):
    with open(os.environ["MOCK_LOG"], "a") as stream:
        stream.write(line + "\n")
old = os.environ["MOCK_OLD"]
new = os.environ["MOCK_NEW"]
log("docker " + " ".join(args))
if args[:2] == ["compose", "version"]:
    print("Docker Compose mock")
elif args and args[0] == "ps" and "-aq" in args:
    print("mock-container")
elif args and args[0] == "inspect" and "mock-container" in args:
    fmt = " ".join(args)
    if ".Id" in fmt:
        print("c" * 64)
    elif ".Image" in fmt:
        print(s["running_image"])
    elif ".State.Running" in fmt:
        print("true")
    elif ".State.Health" in fmt:
        if s["running_image"] == new and s["fail_candidate"]:
            print("unhealthy")
        else:
            print("healthy")
    else:
        sys.exit(3)
elif args[:2] == ["pull", "ghcr.io/ithute-stak/ithute-pay:latest"]:
    pass
elif args[:2] == ["image", "inspect"]:
    print(new)
elif args and args[0] == "compose":
    # Skip configuration arguments, find the actual Docker Compose subcommand.
    index = next((i for i, v in enumerate(args) if v in {"config", "ps", "run", "up", "exec"}), None)
    if index is None:
        sys.exit(4)
    cmd = args[index]
    if cmd == "config":
        pass
    elif cmd == "ps":
        print("mock-container")
    elif cmd == "run":
        if "current" in args and "--check" in args and s["migration_required"]:
            if not s["migration_applied"]:
                sys.exit(10)
        if "upgrade" in args:
            s["migration_applied"] = True
            save()
    elif cmd == "up":
        if os.environ.get("IPB_IMAGE") not in {old, new}:
            sys.exit(5)
        s["running_image"] = os.environ["IPB_IMAGE"]
        save()
    elif cmd == "exec":
        if "pg_dump" in " ".join(args):
            sys.stdout.buffer.write(b"PGDMPfake")
    else:
        sys.exit(6)
else:
    sys.exit(7)
'''

MOCK_CURL = r'''#!/usr/bin/env python3
import os
from pathlib import Path
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write("curl\n")
'''

MOCK_SLEEP = "#!/bin/sh\nexit 0\n"


class ReleaseRehearsal(unittest.TestCase):
    def deploy(self, *, migration=False, approve=False, fail_new=False, same=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bins = root / "bin"
            bins.mkdir()
            for name, data in {"docker": MOCK_DOCKER, "curl": MOCK_CURL, "sleep": MOCK_SLEEP}.items():
                path = bins / name
                path.write_text(data)
                path.chmod(0o755)
            compose = root / "compose.yaml"
            compose.write_text("services:\n  ithute-pay-bridge:\n    image: placeholder\n")
            envfile = root / ".env"
            envfile.write_text("DB_PASSWORD=disposable\n")
            config = root / "config"
            config.write_text(
                f'PAY_DEPLOY_DIR="{root}"\n'
                f'PAY_COMPOSE_FILES="{compose}"\n'
                f'PAY_ENV_FILE="{envfile}"\n'
                f'PAY_DEPLOY_LOCK="{root / "lock"}"\n'
                f'PAY_BACKUP_DIR="{root / "backup"}"\n'
                'PAY_HEALTH_URL="https://example.invalid/health"\n'
                'PAY_API_URL="https://example.invalid/api"\n'
                'PAY_PORTAL_URL="https://example.invalid/portal"\n'
                'PAY_HEALTH_ATTEMPTS=2\n'
            )
            state = root / "state.json"
            state.write_text(json.dumps(dict(
                running_image=OLD,
                fail_candidate=fail_new,
                migration_required=migration,
                migration_applied=False,
            )))
            log = root / "calls.log"
            log.write_text("")
            env = os.environ.copy()
            env.update({
                "PATH": str(bins) + os.pathsep + env["PATH"],
                "PAY_DEPLOY_CONFIG": str(config),
                "MOCK_STATE": str(state),
                "MOCK_LOG": str(log),
                "MOCK_OLD": OLD,
                "MOCK_NEW": OLD if same else NEW,
            })
            if approve:
                env["PAY_APPROVE_MIGRATIONS"] = "yes"
            p = subprocess.run(["bash", str(ROOT / "pull-pay"), "latest"],
                               capture_output=True, text=True, env=env, timeout=20)
            return p, json.loads(state.read_text()), log.read_text(), list((root / "backup").glob("*")) if (root / "backup").exists() else []

    def test_healthy_release(self):
        proc, state, calls, _ = self.deploy()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(state["running_image"], NEW)
        self.assertEqual(calls.count(" --force-recreate "), 1)
        self.assertNotIn("pg_dump", calls)

    def test_unhealthy_candidate_restores_previous(self):
        proc, state, calls, _ = self.deploy(fail_new=True)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(state["running_image"], OLD)
        self.assertEqual(calls.count(" --force-recreate "), 2)

    def test_unapproved_migration_does_not_switch(self):
        proc, state, calls, _ = self.deploy(migration=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(state["running_image"], OLD)
        self.assertNotIn(" --force-recreate ", calls)
        self.assertIn("STOP", proc.stderr)

    def test_approved_migration_has_backup_before_switch(self):
        proc, state, calls, backups = self.deploy(migration=True, approve=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(state["migration_applied"])
        self.assertEqual(state["running_image"], NEW)
        self.assertEqual(len(backups), 1)
        self.assertLess(calls.index("pg_dump"), calls.index("alembic upgrade head"))

    def test_same_image_is_noop(self):
        proc, state, calls, _ = self.deploy(same=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(state["running_image"], OLD)
        self.assertNotIn(" --force-recreate ", calls)


if __name__ == "__main__":
    unittest.main()
