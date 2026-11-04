"""Ensure the optional registry-verification workflow can never deploy or publish."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "staging-image-verify.yml"


def test_manual_only_and_read_only_permissions():
    data = yaml.safe_load(WORKFLOW.read_text())
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert set(triggers["workflow_dispatch"]["inputs"]) == {"commit_sha", "image_digest"}
    assert data["permissions"] == {"contents": "read", "packages": "read"}
    assert set(data["jobs"]) == {"verify-published-image"}


def test_registry_verify_must_be_no_execute_no_deploy():
    content = WORKFLOW.read_text()
    assert "ghcr.io/ithute-stak/ithute-pay@$IMAGE_DIGEST" in content
    assert "org.opencontainers.image.revision" in content
    assert "git rev-parse HEAD" in content
    assert "docker pull" in content
    assert "docker image inspect" in content
    assert "RepoDigests" in content
    assert "actions/upload-artifact@v4" in content
    assert "ithutepay-verified-registry-image" in content
    assert "validate_staging_registry_evidence.py" in content
    assert "\"github_run_id\": os.environ[\"GITHUB_RUN_ID\"]" in content
    steps = yaml.safe_load(content)["jobs"]["verify-published-image"]["steps"]
    validator = next(i for i, step in enumerate(steps) if step["name"] == "Independently validate registry evidence")
    upload = next(i for i, step in enumerate(steps) if step["name"] == "Upload non-secret registry verification evidence")
    assert validator < upload
    assert "continue-on-error" not in steps[validator]
    assert "\"container_executed\": False" in content
    assert "\"staging_deployed\": False" in content
    for command in (
        "docker run ", "docker compose up", "docker push ",
        "docker build ", "kubectl apply", "ssh ", "scp ",
        "alembic upgrade", "docker exec ",
    ):
        assert command not in content
