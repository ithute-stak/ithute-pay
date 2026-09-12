from pathlib import Path


PROVIDERS_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "app"
    / "dashboard"
    / "providers"
    / "page.tsx"
)


def _source() -> str:
    return PROVIDERS_PAGE.read_text(encoding="utf-8")


def test_provider_console_is_split_into_focused_tabs():
    source = _source()

    assert 'type ProviderTab = "catalogue" | "environments" | "configure" | "activity"' in source
    assert 'data-testid="provider-tabs"' in source
    assert 'role="tablist"' in source
    assert 'role="tab"' in source
    assert 'Provider catalogue' in source
    assert 'Configured environments' in source
    assert 'Add / update' in source
    assert 'Callbacks & URLs' in source


def test_provider_sections_render_only_for_the_active_tab():
    source = _source()

    assert 'activeTab === "catalogue"' in source
    assert 'activeTab === "environments"' in source
    assert 'activeTab === "configure"' in source
    assert 'activeTab === "activity"' in source
    assert 'data-testid="provider-environments-tab"' in source
    assert 'data-testid="provider-configure-tab"' in source
    assert 'data-testid="provider-activity-tab"' in source


def test_configure_action_moves_into_configuration_tab():
    source = _source()

    assert 'setActiveTab("configure")' in source
    assert 'setActiveTab("environments")' in source
    assert 'md:grid-cols-2 2xl:grid-cols-3' in source
