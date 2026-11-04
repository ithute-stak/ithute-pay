"""Verify staging rehearsal claims are tied to exactly the Docker image tested."""
from pathlib import Path
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "build-vps-image.yml"


def _steps():
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]["build"]["steps"]


def test_evidence_is_written_only_after_successful_real_container_rehearsal():
    steps = _steps()
    smoke = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Boot PR image"))
    evidence = next(i for i, step in enumerate(steps) if step.get("name") == "Record offline PR rehearsal evidence")
    upload = next(i for i, step in enumerate(steps) if step.get("name") == "Upload offline staging rehearsal evidence")
    assert smoke < evidence < upload
    for i in (smoke, evidence, upload):
        assert steps[i]["if"] == "github.event_name == 'pull_request'"
    assert "continue-on-error" not in steps[evidence]
    assert steps[upload]["with"]["if-no-files-found"] == "error"


def test_image_tag_must_match_exact_checkout_not_only_pr_head():
    record = next(step for step in _steps() if step.get("name") == "Record offline PR rehearsal evidence")
    script = record["run"]
    assert 'checkout = subprocess.check_output(["git", "rev-parse", "HEAD"]' in script
    assert 'image_tag == "sha-" + checkout' in script
    assert '"tested_checkout_sha": checkout' in script
    assert '"pr_head_sha": os.environ["PR_HEAD_SHA"]' in script
    assert '"checkout_kind": "github_actions_pull_request_checkout"' in script
    assert '"image_tag_matches_tested_checkout": True' in script
    assert '"registry_image_published": False' in script
    assert '"external_sandbox_certified": False' in script
    assert '"operator_staging_deployment": False' in script
    assert '"local_image_id": image_id' in script


def test_running_container_image_id_matches_built_candidate_before_smoke():
    steps = _steps()
    rehearsal = next(step for step in steps if step.get("name", "").startswith("Boot PR image"))
    script = rehearsal["run"]
    assert 'docker compose -f deploy/staging/compose.yaml ps -q app' in script
    assert 'docker image inspect "$STAGING_IMAGE"' in script
    assert 'docker container inspect "$APP_CONTAINER"' in script
    assert 'test "$RUNNING_IMAGE_ID" = "$EXPECTED_IMAGE_ID"' in script
    assert script.index('test "$RUNNING_IMAGE_ID" = "$EXPECTED_IMAGE_ID"') < script.index(
        "staging_postdeploy_smoke.py"
    )
