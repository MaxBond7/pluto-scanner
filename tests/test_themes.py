"""Tests for the theme engine (built-in palettes and user JSON themes)."""
from __future__ import annotations

import json

from pluto_scanner.ui.themes import (
    BUILTIN_THEMES,
    DEFAULT_THEME,
    MONO_COLORS,
    TOKENS,
    build_stylesheet,
    ensure_theme_dir,
    available_themes,
    load_theme_file,
    qss,
    resolve_theme,
    theme_from_dict,
)


def test_default_theme_is_black_mono():
    assert DEFAULT_THEME in BUILTIN_THEMES
    theme = BUILTIN_THEMES[DEFAULT_THEME]
    assert theme.colors["bg"] == "#000000"
    assert theme.radius == 0


def test_builtin_themes_define_every_token():
    for name, theme in BUILTIN_THEMES.items():
        assert set(theme.colors) == set(TOKENS), name
        for token, value in theme.colors.items():
            assert value.startswith("#") and len(value) == 7, (name, token)


def test_theme_from_dict_fills_defaults_and_ignores_unknown():
    theme = theme_from_dict({
        "name": "custom",
        "title": "CUSTOM",
        "radius": 99,
        "colors": {"bg": "#101010", "accent": "#ff0000", "nonsense": "#123456"},
    })
    assert theme.name == "custom"
    assert theme.colors["bg"] == "#101010"
    assert theme.colors["accent"] == "#ff0000"
    assert "nonsense" not in theme.colors
    assert theme.colors["fg"] == MONO_COLORS["fg"]
    assert theme.radius == 20


def test_legacy_colour_mapping():
    theme = BUILTIN_THEMES["mono-ice"]
    assert theme.resolve("#f87171") == theme.colors["danger"]
    assert theme.resolve("#22d3ee") == theme.colors["accent"]
    assert theme.resolve("danger") == theme.colors["danger"]
    assert theme.resolve("#123456") == "#123456"


def test_qss_rewrites_every_hex_colour():
    text = qss("color:#f87171; background:#0f172a; border:1px solid #22d3ee;")
    assert "#f87171" not in text
    assert "#0f172a" not in text
    assert "#22d3ee" not in text
    assert text.count("#") == 3


def test_build_stylesheet_is_complete():
    for name, theme in BUILTIN_THEMES.items():
        sheet = build_stylesheet(theme)
        assert "$" not in sheet, name
        assert theme.colors["bg"] in sheet
        assert "QPushButton" in sheet


def test_user_themes_are_discovered(tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    good = {
        "name": "mine",
        "title": "MINE",
        "colors": {"bg": "#010101"},
    }
    (folder / "mine.json").write_text(json.dumps(good), encoding="utf-8")
    (folder / "broken.json").write_text("{not json", encoding="utf-8")

    themes = available_themes(folder)
    assert "mine" in themes
    assert themes["mine"].colors["bg"] == "#010101"
    assert "classic" in themes
    assert all(name for name in themes)


def test_user_theme_with_builtin_name_gets_suffix(tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    (folder / "copy.json").write_text(
        json.dumps({"name": "mono", "title": "Copy"}),
        encoding="utf-8",
    )
    themes = available_themes(folder)
    assert "mono-copy" in themes
    assert themes["mono-copy"].title == "Copy (copy)"


def test_load_theme_file_roundtrip(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps({
            "name": "round",
            "title": "ROUND",
            "font": "Consolas",
            "waterfall": "grey",
            "colors": {"accent": "#abcdef"},
        }),
        encoding="utf-8",
    )
    theme = load_theme_file(path)
    assert theme.waterfall == "grey"
    assert theme.font == "Consolas"
    assert theme.colors["accent"] == "#abcdef"
    saved = theme.save(tmp_path / "out.json")
    again = load_theme_file(saved)
    assert again.colors == theme.colors


def test_resolve_theme_falls_back(tmp_path):
    theme = resolve_theme("does-not-exist", tmp_path)
    assert theme.name == DEFAULT_THEME


def test_ensure_theme_dir_creates_readme(tmp_path):
    folder = ensure_theme_dir(tmp_path)
    assert folder.is_dir()
    assert (folder / "README.txt").exists()
    text = (folder / "README.txt").read_text(encoding="utf-8")
    assert "colors" in text and "bg" in text

def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    l1, l2 = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_alarm_banner_text_stays_visible_in_every_theme():
    """The alarm banner used to paint its text in the same colour as its own
    background: both #7f1d1d and #fecaca collapsed into the single ``danger``
    token, so the warning looked empty."""
    from PySide6.QtWidgets import QApplication, QLabel

    from pluto_scanner.ui.themes import apply_theme, set_style

    app = QApplication.instance() or QApplication([])
    try:
        for name, theme in BUILTIN_THEMES.items():
            apply_theme(app, theme)
            background = theme.color("danger_bg")
            foreground = theme.color("danger_fg")
            assert background != foreground, name
            assert _contrast(background, foreground) >= 4.5, name

            label = QLabel("ВНИМАНИЕ")
            set_style(label, "background:$danger_bg; color:$danger_fg;")
            sheet = label.styleSheet()
            assert "$" not in sheet, name
            assert background in sheet and foreground in sheet, name
    finally:
        apply_theme(app, BUILTIN_THEMES[DEFAULT_THEME])
