"""Security regressions use only temporary local files; no network or audio."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


def make_directory_link(target: Path, link: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.fixture
def scoped_engine(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[root])
    return TaskEngine(settings, Store(settings.data_dir)), root


def test_directory_enumeration_does_not_follow_reparse_targets(
    scoped_engine, tmp_path, monkeypatch
):
    engine, root = scoped_engine
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "external-directory"
    make_directory_link(outside, link)
    original_stat = Path.stat

    def require_no_target_follow(path, *args, **kwargs):
        if path == link and kwargs.get("follow_symlinks", True):
            raise AssertionError("Directory enumeration must not access a link target")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", require_no_target_follow)
    task = engine.submit("list_directory", {"path": str(root)})
    assert task["state"] == "completed", task["error"]
    entries = task["result"]["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == link.name
    assert entries[0]["link"] is True


@pytest.mark.parametrize("target_inside_root", [False, True])
def test_direct_file_tools_reject_directory_links(scoped_engine, tmp_path, target_inside_root):
    engine, root = scoped_engine
    target = (root if target_inside_root else tmp_path) / "target"
    target.mkdir()
    source = target / "source.txt"
    source.write_text("temporary local fixture", encoding="utf-8")
    link = root / "linked-directory"
    make_directory_link(target, link)
    for tool, path in [("list_directory", link), ("read_file", link / source.name)]:
        with pytest.raises(PermissionError):
            engine.submit(tool, {"path": str(path)})


def test_pending_approval_rejects_a_replaced_parent_link(scoped_engine, tmp_path):
    engine, root = scoped_engine
    parent = root / "parent"
    parent.mkdir()
    task = engine.submit("create_directory", {"path": str(parent / "new-folder")})
    assert task["state"] == "awaiting_approval"
    parent.rename(root / "original-parent")
    outside = tmp_path / "outside"
    outside.mkdir()
    make_directory_link(outside, parent)
    result = engine.approve(task["id"])
    assert result["state"] == "failed"
    assert not (outside / "new-folder").exists()
    with pytest.raises(ValueError):
        engine.approve(task["id"])


def test_explicit_export_includes_records_beyond_display_limits(tmp_path):
    store = Store(tmp_path / "data")
    for index in range(201):
        store.add_message(
            "long-conversation", "user" if index % 2 == 0 else "assistant", str(index)
        )
    for index in range(501):
        store.save_memory("knowledge", f"memory-{index}", f"saved reference {index}")
        store.put_task(
            dict(
                id=f"task-{index}",
                tool="list_directory",
                arguments={},
                state="completed",
                result={"verified": True},
            )
        )
    exported = store.export()
    assert len(exported["memories"]) == 501
    assert len(exported["tasks"]) == 501
    assert len(exported["sessions"]) == 1
    history = exported["sessions"][0]["history"]
    assert [message["content"] for message in history] == [str(index) for index in range(201)]
