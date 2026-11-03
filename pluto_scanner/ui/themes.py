"""Theme engine: built-in palettes, user JSON themes, Qt stylesheet builder.

A theme is a plain JSON file with a dozen colours, a font and a corner radius,
so anyone can make their own without touching Python.  Built-in themes show
the intended range: the original dark blue, a pure black-and-white terminal
look, and monochrome variants with one rare accent colour.

Colours used by older widgets are written as literals (``#f87171``).  They are
translated through :func:`qss` / :func:`c` at runtime, so a widget does not
need to know which theme is active.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

THEME_VERSION = 1

# --------------------------------------------------------------------- tokens
TOKENS = (
    "bg",
    "panel",
    "panel_alt",
    "input",
    "hover",
    "border",
    "border_strong",
    "fg",
    "fg_dim",
    "fg_muted",
    "accent",
    "accent_soft",
    "ok",
    "warn",
    "danger",
    "selection_bg",
    "selection_fg",
    "graph_bg",
    "graph_fg",
    "grid",
)

# Every literal colour used in the UI, mapped to a semantic token.  A theme
# only redefines tokens; the mapping stays the same for everyone.
LEGACY_TO_TOKEN: dict[str, str] = {
    # backgrounds
    "#0b1020": "bg",
    "#0a0f1e": "graph_bg",
    "#080d19": "bg",
    "#0f1a2e": "bg",
    "#0b1222": "panel",
    "#0d1426": "panel",
    "#0e172b": "panel_alt",
    "#0f172a": "input",
    "#111a2c": "input",
    "#14203a": "hover",
    "#17233b": "hover",
    "#22345a": "hover",
    # borders
    "#1e2a44": "border",
    "#1e2d4a": "border",
    "#22304a": "border",
    "#2b3d5f": "border",
    "#3b5b8a": "border_strong",
    "#155e75": "selection_bg",
    "#0e7490": "selection_bg",
    # text
    "#d7e2f0": "fg",
    "#e2e8f0": "fg",
    "#ffffff": "fg",
    "#8fa6c0": "fg_dim",
    "#9fb3c8": "fg_dim",
    "#94a3b8": "fg_muted",
    "#64748b": "fg_muted",
    "#52627a": "fg_muted",
    "#475569": "fg_muted",
    # accents
    "#22d3ee": "accent",
    "#67e8f9": "accent",
    "#06b6d4": "accent",
    "#0891b2": "accent_soft",
    "#f472b6": "accent",
    "#e879f9": "accent",
    "#a78bfa": "accent_soft",
    "#c4b5fd": "accent_soft",
    "#4ade80": "ok",
    "#facc15": "warn",
    "#fbbf24": "warn",
    "#f59e0b": "warn",
    "#fb923c": "warn",
    "#f87171": "danger",
    "#ef4444": "danger",
    "#fecaca": "danger",
    "#fda4af": "danger",
    "#7f1d1d": "danger",
}

CLASSIC_COLORS: dict[str, str] = {
    "bg": "#0b1020",
    "panel": "#0d1426",
    "panel_alt": "#0e172b",
    "input": "#0f172a",
    "hover": "#17233b",
    "border": "#22304a",
    "border_strong": "#3b5b8a",
    "fg": "#d7e2f0",
    "fg_dim": "#8fa6c0",
    "fg_muted": "#64748b",
    "accent": "#22d3ee",
    "accent_soft": "#a78bfa",
    "ok": "#4ade80",
    "warn": "#facc15",
    "danger": "#f87171",
    "selection_bg": "#155e75",
    "selection_fg": "#ffffff",
    "graph_bg": "#0a0f1e",
    "graph_fg": "#9fb3c8",
    "grid": "#1e2a44",
}

MONO_COLORS: dict[str, str] = {
    "bg": "#000000",
    "panel": "#000000",
    "panel_alt": "#0a0a0a",
    "input": "#080808",
    "hover": "#161616",
    "border": "#2a2a2a",
    "border_strong": "#6f6f6f",
    "fg": "#f2f2f2",
    "fg_dim": "#aaaaaa",
    "fg_muted": "#6e6e6e",
    "accent": "#ffffff",
    "accent_soft": "#c8c8c8",
    "ok": "#dcdcdc",
    "warn": "#ffffff",
    "danger": "#ffffff",
    "selection_bg": "#ffffff",
    "selection_fg": "#000000",
    "graph_bg": "#000000",
    "graph_fg": "#a0a0a0",
    "grid": "#1c1c1c",
}

MONO_FONT = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'
CLASSIC_FONT = '"Segoe UI", "Inter", sans-serif'


def _mono_accent(color: str) -> dict[str, str]:
    """Pure monochrome with a single rare accent colour."""
    palette = dict(MONO_COLORS)
    palette.update({
        "accent": color,
        "danger": color,
        "warn": "#ffffff",
        "ok": "#dcdcdc",
        "accent_soft": color,
        "selection_bg": color,
        "selection_fg": "#000000",
        "border_strong": "#5a5a5a",
    })
    return palette


@dataclass
class Theme:
    name: str
    title: str
    colors: dict[str, str]
    description: str = ""
    font: str = CLASSIC_FONT
    radius: int = 6
    waterfall: str = "viridis"
    source: str = "built-in"
    path: Path | None = None

    # ------------------------------------------------------------- accessors
    def color(self, token: str) -> str:
        return self.colors.get(token, MONO_COLORS.get(token, "#ff00ff"))

    def resolve(self, value: str) -> str:
        """Resolve a token name or a legacy hex literal to a themed colour."""
        text = str(value or "").strip()
        if not text:
            return self.color("fg")
        if text.startswith("#"):
            token = LEGACY_TO_TOKEN.get(text.lower())
            return self.color(token) if token else text
        if text in self.colors:
            return self.colors[text]
        return text

    # ---------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": THEME_VERSION,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "font": self.font,
            "radius": int(self.radius),
            "waterfall": self.waterfall,
            "colors": dict(self.colors),
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


def theme_from_dict(data: dict[str, Any], *, source: str = "user") -> Theme:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("у темы нет поля name")
    colors = dict(MONO_COLORS)
    incoming = data.get("colors") or {}
    if not isinstance(incoming, dict):
        raise ValueError("colors должен быть объектом")
    for key, value in incoming.items():
        key = str(key)
        if key in TOKENS and isinstance(value, str):
            colors[key] = value
    radius = int(data.get("radius", 0) or 0)
    return Theme(
        name=name,
        title=str(data.get("title") or name),
        colors=colors,
        description=str(data.get("description") or ""),
        font=str(data.get("font") or MONO_FONT),
        radius=max(0, min(20, radius)),
        waterfall=str(data.get("waterfall") or "viridis"),
        source=source,
    )


def load_theme_file(path: str | Path) -> Theme:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    theme = theme_from_dict(data, source=f"файл {path.name}")
    theme.path = path
    return theme


# --------------------------------------------------------------------- built-in
BUILTIN_THEMES: dict[str, Theme] = {
    "classic": Theme(
        name="classic",
        title="Classic",
        description="Исходная тёмно-синяя тема",
        colors=dict(CLASSIC_COLORS),
        font=CLASSIC_FONT,
        radius=6,
    ),
    "mono": Theme(
        name="mono",
        title="MONO",
        description="Чистый чёрно-белый терминал, острые углы",
        colors=dict(MONO_COLORS),
        font=MONO_FONT,
        radius=0,
        waterfall="grey",
    ),
    "mono-acid": Theme(
        name="mono-acid",
        title="MONO / ACID",
        description="Ч/б с редким кислотным акцентом",
        colors=_mono_accent("#c6ff2e"),
        font=MONO_FONT,
        radius=0,
        waterfall="grey",
    ),
    "mono-ember": Theme(
        name="mono-ember",
        title="MONO / EMBER",
        description="Ч/б с редким огненно-оранжевым акцентом",
        colors=_mono_accent("#ff5a1f"),
        font=MONO_FONT,
        radius=0,
        waterfall="grey",
    ),
    "mono-ice": Theme(
        name="mono-ice",
        title="MONO / ICE",
        description="Ч/б с редким холодным циановым акцентом",
        colors=_mono_accent("#35e0ff"),
        font=MONO_FONT,
        radius=0,
        waterfall="grey",
    ),
}

DEFAULT_THEME = "mono"

# ------------------------------------------------------------------- stylesheet
_STYLESHEET = Template("""
QMainWindow, QWidget {
    background-color: $bg;
    color: $fg;
    font-family: $font;
    font-size: 12px;
}
QToolTip {
    background-color: $panel;
    color: $fg;
    border: 1px solid $border_strong;
    padding: 4px;
}
QGroupBox {
    border: 1px solid $border;
    border-radius: ${radius}px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    background-color: $panel;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 5px;
    color: $accent;
    font-weight: 700;
}
QPushButton {
    background-color: $panel_alt;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 5px 9px;
    color: $fg;
}
QPushButton:hover { background-color: $hover; border-color: $border_strong; }
QPushButton:pressed { background-color: $input; }
QPushButton:checked {
    background-color: $selection_bg;
    border-color: $selection_bg;
    color: $selection_fg;
}
QPushButton:disabled { color: $fg_muted; background-color: $panel; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: $input;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 4px 6px;
    color: $fg;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QComboBox::drop-down { border: 0; width: 18px; }
QComboBox QAbstractItemView {
    background-color: $input;
    color: $fg;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
    border: 1px solid $border;
}
QCheckBox { spacing: 6px; color: $fg; }
QCheckBox::indicator {
    width: 13px; height: 13px;
    border: 1px solid $border_strong;
    border-radius: 0px;
    background-color: $input;
}
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
}
QRadioButton { spacing: 6px; color: $fg; }
QSlider::groove:horizontal { height: 3px; background: $border; }
QSlider::handle:horizontal {
    width: 11px; margin: -5px 0; border-radius: 0px;
    background: $accent;
}
QTableWidget {
    background-color: $panel;
    alternate-background-color: $panel_alt;
    gridline-color: $border;
    border: 1px solid $border;
    border-radius: ${radius}px;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
    color: $fg;
}
QHeaderView::section {
    background-color: $panel_alt;
    color: $fg_dim;
    border: 0;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
    padding: 5px;
    font-weight: 700;
}
QScrollBar:vertical { background: $bg; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: $border; border-radius: 0px; min-height: 25px;
}
QScrollBar::handle:vertical:hover { background: $border_strong; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: $bg; height: 10px; margin: 0; }
QScrollBar::handle:horizontal {
    background: $border; border-radius: 0px; min-width: 25px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QListWidget, QTreeWidget {
    background-color: $input;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 3px;
}
QListWidget::item { padding: 5px; border-radius: 0px; }
QListWidget::item:selected {
    background-color: $selection_bg;
    color: $selection_fg;
}
QStatusBar {
    background-color: $panel;
    border-top: 1px solid $border;
    color: $fg_dim;
}
QMenu {
    background-color: $panel;
    color: $fg;
    border: 1px solid $border;
}
QMenu::item:selected {
    background-color: $selection_bg;
    color: $selection_fg;
}
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: ${radius}px;
    background-color: $panel;
    top: -1px;
}
QTabBar::tab {
    background-color: $panel_alt;
    color: $fg_dim;
    border: 1px solid $border;
    border-bottom: 0;
    padding: 7px 14px;
    margin-right: 2px;
    border-top-left-radius: ${radius}px;
    border-top-right-radius: ${radius}px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background-color: $panel;
    color: $accent;
    border-color: $border_strong;
}
QTabBar::tab:hover { color: $fg; }
QProgressBar {
    background-color: $input;
    border: 1px solid $border;
    border-radius: ${radius}px;
    text-align: center;
    color: $fg;
}
QProgressBar::chunk { background-color: $accent; border-radius: 0px; }
QSplitter::handle { background-color: $border; }
QDialog { background-color: $bg; }
QSplitter::handle:hover { background-color: $border_strong; }
""")


def build_stylesheet(theme: Theme) -> str:
    values = {token: theme.color(token) for token in TOKENS}
    values["font"] = theme.font
    values["radius"] = str(int(theme.radius))
    return _STYLESHEET.substitute(values)


# ------------------------------------------------------------------- activation
_active: Theme = BUILTIN_THEMES[DEFAULT_THEME]


def active_theme() -> Theme:
    return _active


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def tcol(value: Any) -> str:
    """Resolve one colour (token name or legacy hex) for the active theme."""
    if value is None:
        return _active.color("fg")
    return _active.resolve(str(value))


def qss(text: Any) -> str:
    """Rewrite every legacy hex colour in a stylesheet for the active theme."""
    if text is None:
        return ""
    if not isinstance(text, str):
        return text
    return _HEX_RE.sub(lambda match: tcol(match.group(0)), text)


def trgba(red: int, green: int, blue: int, alpha: int = 255) -> QColor:
    """Map an RGB triple through the active theme, keeping the alpha."""
    color = QColor(tcol(f"#{int(red):02x}{int(green):02x}{int(blue):02x}"))
    color.setAlpha(int(alpha))
    return color


def set_style(widget: "QWidget", template: Any) -> None:
    """Apply a stylesheet and remember the raw template for live re-theming."""
    if widget is None:
        return
    widget.setProperty("_theme_template", template if isinstance(template, str) else "")
    widget.setStyleSheet(qss(template))


def retint(root: "QWidget") -> None:
    """Re-apply every stored stylesheet template after a theme change."""
    if root is None:
        return
    from PySide6.QtWidgets import QWidget

    for widget in [root, *root.findChildren(QWidget)]:
        template = widget.property("_theme_template")
        if isinstance(template, str) and template:
            widget.setStyleSheet(qss(template))


def _palette(theme: Theme) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.color("bg")))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.color("fg")))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.color("input")))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.color("panel_alt")))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.color("fg")))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.color("panel_alt")))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.color("fg")))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.color("selection_bg")))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.color("selection_fg")))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.color("panel")))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.color("fg")))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.color("fg_muted")))
    return palette


def apply_theme(app: QApplication, theme: Theme | None = None) -> Theme:
    global _active
    theme = theme or _active
    _active = theme
    app.setStyle("Fusion")
    app.setPalette(_palette(theme))
    app.setStyleSheet(build_stylesheet(theme))
    pg.setConfigOption("background", theme.color("graph_bg"))
    pg.setConfigOption("foreground", theme.color("graph_fg"))
    pg.setConfigOptions(antialias=True)
    return theme


# -------------------------------------------------------------------- discovery
def theme_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "themes"


THEME_README = """\
Свои темы Pluto Scanner
=======================

Положите сюда файл *.json — он появится в списке тем без перезапуска
(список обновляется при старте программы).

Минимальный пример:

{
  "version": 1,
  "name": "my-theme",
  "title": "MY THEME",
  "description": "что угодно",
  "font": "Consolas",
  "radius": 0,
  "waterfall": "grey",
  "colors": {
    "bg": "#000000",
    "panel": "#000000",
    "panel_alt": "#0a0a0a",
    "input": "#080808",
    "hover": "#161616",
    "border": "#2a2a2a",
    "border_strong": "#6f6f6f",
    "fg": "#f2f2f2",
    "fg_dim": "#aaaaaa",
    "fg_muted": "#6e6e6e",
    "accent": "#ffffff",
    "accent_soft": "#c8c8c8",
    "ok": "#dcdcdc",
    "warn": "#ffffff",
    "danger": "#ffffff",
    "selection_bg": "#ffffff",
    "selection_fg": "#000000",
    "graph_bg": "#000000",
    "graph_fg": "#a0a0a0",
    "grid": "#1c1c1c"
  }
}

Недостающие токены берутся из темы MONO. Неизвестные игнорируются.
waterfall: "viridis", "grey" или другое имя карты pyqtgraph.
"""


def ensure_theme_dir(data_dir: str | Path) -> Path:
    """Create the user theme folder and a short format description."""
    directory = theme_dir(data_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        readme = directory / "README.txt"
        if not readme.exists():
            readme.write_text(THEME_README, encoding="utf-8")
    except OSError:
        pass
    return directory


def available_themes(extra_dir: str | Path | None = None) -> dict[str, Theme]:
    """Built-in themes plus any valid ``*.json`` in the user theme folder."""
    themes: dict[str, Theme] = dict(BUILTIN_THEMES)
    if extra_dir is None:
        return themes
    directory = Path(extra_dir)
    if not directory.exists():
        return themes
    for path in sorted(directory.glob("*.json")):
        try:
            theme = load_theme_file(path)
        except Exception as exc:
            log.warning("theme %s skipped: %s", path.name, exc)
            continue
        if theme.name in BUILTIN_THEMES:
            theme.name = f"{theme.name}-{path.stem}"
            theme.title = f"{theme.title} ({path.stem})"
        themes[theme.name] = theme
    return themes


# ------------------------------------------------------------------- settings
def load_settings(path: str | Path) -> dict[str, Any]:
    try:
        path = Path(path)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(path: str | Path, data: dict[str, Any]) -> None:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("settings write failed: %s", exc)


def resolve_theme(
    name: str, extra_dir: str | Path | None = None
) -> Theme:
    themes = available_themes(extra_dir)
    if name in themes:
        return themes[name]
    return themes.get(DEFAULT_THEME, BUILTIN_THEMES[DEFAULT_THEME])
