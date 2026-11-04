"""Offline process-supervisor staging safety contract (no processes started)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from deploy.container import run_combined


def test_background_jobs_are_disabled_on_staging_opt_out(monkeypatch):
    monkeypatch.setenv("RUN_BACKGROUND_JOBS", "false")
    assert {item.name for item in run_combined._specs()} == {"fastapi", "nextjs"}


def test_existing_production_default_still_starts_all_processes(monkeypatch):
    monkeypatch.delenv("RUN_BACKGROUND_JOBS", raising=False)
    names = {item.name for item in run_combined._specs()}
    assert names == {"fastapi", "nextjs", "celery-worker", "celery-beat"}


def test_false_variants_disable_jobs(monkeypatch):
    for value in ("0", "off", "no", "FALSE"):
        monkeypatch.setenv("RUN_BACKGROUND_JOBS", value)
        assert {item.name for item in run_combined._specs()} == {"fastapi", "nextjs"}
