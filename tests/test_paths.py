"""Tests for portable/installed data-directory selection."""
from __future__ import annotations

from pathlib import Path

from pluto_scanner.paths import resolve_data_home


def test_source_checkout_uses_project_root(tmp_path):
    assert resolve_data_home(
        frozen=False, app_root=tmp_path, env={}
    ) == tmp_path


def test_portable_build_uses_app_root(tmp_path):
    assert resolve_data_home(
        frozen=True, app_root=tmp_path, env={"LOCALAPPDATA": r"C:\Data"},
        portable=True,
    ) == tmp_path


def test_existing_user_data_keeps_app_root(tmp_path):
    (tmp_path / "user_data").mkdir()
    assert resolve_data_home(
        frozen=True, app_root=tmp_path, env={"LOCALAPPDATA": r"C:\Data"}
    ) == tmp_path


def test_installed_build_uses_localappdata(tmp_path):
    assert resolve_data_home(
        frozen=True, app_root=tmp_path, env={"LOCALAPPDATA": r"C:\Data"}
    ) == Path(r"C:\Data") / "PlutoScanner"


def test_env_override_wins(tmp_path):
    assert resolve_data_home(
        frozen=True, app_root=tmp_path,
        env={"LOCALAPPDATA": r"C:\Data",
             "PLUTO_SCANNER_DATA_DIR": str(tmp_path / "custom")},
        portable=True,
    ) == tmp_path / "custom"
