# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for portable/installed data-directory selection."""
from __future__ import annotations

from pathlib import Path

from sdr_scanner.paths import resolve_data_home


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
    ) == Path(r"C:\Data") / "SDRScanner"


def test_env_override_wins(tmp_path):
    assert resolve_data_home(
        frozen=True, app_root=tmp_path,
        env={"LOCALAPPDATA": r"C:\Data",
             "SDR_SCANNER_DATA_DIR": str(tmp_path / "custom")},
        portable=True,
    ) == tmp_path / "custom"


def test_old_env_override_still_works(tmp_path):
    assert resolve_data_home(
        frozen=True, app_root=tmp_path,
        env={"LOCALAPPDATA": r"C:\Data",
             "PLUTO_SCANNER_DATA_DIR": str(tmp_path / "old")},
        portable=True,
    ) == tmp_path / "old"


def test_installed_build_migrates_the_old_data_folder(tmp_path):
    legacy = tmp_path / "PlutoScanner" / "user_data"
    legacy.mkdir(parents=True)
    (legacy / "ml_model.json").write_text("{}", encoding="utf-8")

    home = resolve_data_home(
        frozen=True, app_root=tmp_path, env={"LOCALAPPDATA": str(tmp_path)}
    )

    assert home == tmp_path / "SDRScanner"
    assert (home / "user_data" / "ml_model.json").exists()
    assert not (tmp_path / "PlutoScanner").exists()
