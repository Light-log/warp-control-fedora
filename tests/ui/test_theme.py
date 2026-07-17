from warp_control.config import Config
from warp_control.models import WarpState
from warp_control.ui.theme import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    ScreenProviderBinding,
    build_css,
    palette_for,
)


def test_light_and_dark_palettes_have_approved_integrated_headers():
    assert LIGHT_PALETTE.header == "#f5f6f8"
    assert DARK_PALETTE.header == "#0e1726"
    assert palette_for("light") is LIGHT_PALETTE
    assert palette_for("dark") is DARK_PALETTE


def test_css_uses_custom_accent_without_fixed_default_or_black_header():
    config = Config(theme="light", accent="#1267D6")

    css = build_css(config, WarpState.CONNECTED)

    assert "#1267D6" in css
    assert "#16A34A" in css
    assert "#F38020" not in css
    assert "#f5f6f8" in css
    assert "#000000" not in css


def test_state_primary_and_accent_have_separate_css_roles():
    config = Config(accent="#6750A4")

    css = build_css(config, WarpState.ERROR)

    assert ".accent-action" in css
    assert ".state-action" in css
    assert "#6750A4" in css
    assert "#DC2626" in css


def test_css_provider_binding_installs_once_and_moves_between_screens():
    provider = object()
    first_screen = object()
    second_screen = object()
    calls = []
    binding = ScreenProviderBinding(provider, 600)

    binding.install(
        first_screen,
        lambda screen, item, priority: calls.append(("add", screen, item, priority)),
        lambda screen, item: calls.append(("remove", screen, item)),
    )
    binding.install(first_screen, lambda *_args: calls.append(("duplicate",)), lambda *_args: None)
    binding.install(
        second_screen,
        lambda screen, item, priority: calls.append(("add", screen, item, priority)),
        lambda screen, item: calls.append(("remove", screen, item)),
    )

    assert calls == [
        ("add", first_screen, provider, 600),
        ("remove", first_screen, provider),
        ("add", second_screen, provider, 600),
    ]
