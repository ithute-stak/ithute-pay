from pathlib import Path


PROVIDERS_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "app"
    / "dashboard"
    / "providers"
    / "page.tsx"
)


def test_provider_catalogue_keeps_all_visible_payment_rails():
    source = PROVIDERS_PAGE.read_text(encoding="utf-8")

    for label in (
        "M-Pesa Lesotho",
        "FNB Lesotho",
        "Standard Lesotho Bank",
        "Nedbank Lesotho",
        "Lesotho PostBank",
        "EcoCash Zimbabwe",
        "PayPal",
        "Debit / Credit Cards",
    ):
        assert label in source


def test_fnb_is_configurable_without_claiming_live_readiness():
    source = PROVIDERS_PAGE.read_text(encoding="utf-8")

    assert 'key: "fnb", name: "FNB Lesotho"' in source
    assert "FNB operation paths must be valid JSON" in source
    assert "Live collections remain guarded until the contracted payload and signing specification is configured" in source


def test_unimplemented_lesotho_banks_are_explicitly_roadmap_only():
    source = PROVIDERS_PAGE.read_text(encoding="utf-8")

    assert source.count("roadmap: true") >= 3
    assert "No live adapter is implemented yet" in source
    assert "No production payment adapter is implemented yet" in source
