# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the backup retention tool."""
from __future__ import annotations

from pathlib import Path

from tools.prune_backups import plan, version_key


def test_version_key_reads_the_version():
    assert version_key("2026-11-04_v0.20.2_menu_fix") == (0, 20, 2)
    assert version_key("2026-11-04_v0.9.10_old") == (0, 9, 10)
    assert version_key("Personal") is None
    assert version_key("2026-11-04_manual") is None


def test_plan_keeps_the_newest_versions(tmp_path):
    names = [
        "2026-11-04_v0.16.0_a",
        "2026-11-04_v0.17.1_b",
        "2026-11-04_v0.19.0_c",
        "2026-11-04_v0.20.1_d",
        "2026-11-04_v0.20.2_e",
        "Personal",
    ]
    for name in names:
        (tmp_path / name).mkdir()
    kept, removed = plan(tmp_path, keep=3)
    assert [path.name for path in kept] == [
        "2026-11-04_v0.20.2_e",
        "2026-11-04_v0.20.1_d",
        "2026-11-04_v0.19.0_c",
    ]
    assert sorted(path.name for path in removed) == [
        "2026-11-04_v0.16.0_a",
        "2026-11-04_v0.17.1_b",
    ]


def test_plan_ignores_folders_without_a_version(tmp_path):
    (tmp_path / "Personal").mkdir()
    (tmp_path / "notes").mkdir()
    kept, removed = plan(tmp_path, keep=3)
    assert kept == [] and removed == []

def test_remove_tree_handles_read_only_files(tmp_path):
    import stat
    from tools.prune_backups import remove_tree

    victim = tmp_path / "backup"
    victim.mkdir()
    locked = victim / "object.bin"
    locked.write_bytes(b"x")
    locked.chmod(stat.S_IREAD)
    assert remove_tree(victim)
    assert not victim.exists()
