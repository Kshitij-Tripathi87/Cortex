"""Workspace scope ContextVar behavior tests.

Exercises the public API without going through the auth dependency:
    set_workspace_scope / reset_workspace_scope / current_workspace_id /
    require_workspace_id / with_workspace_scope.
"""

from __future__ import annotations

import uuid

import pytest

from app.common.workspace_scope import (
    current_workspace_id,
    require_workspace_id,
    reset_workspace_scope,
    set_workspace_scope,
    with_workspace_scope,
)


def test_unset_returns_none() -> None:
    assert current_workspace_id() is None


def test_set_and_reset_round_trip() -> None:
    ws_id = uuid.uuid4()
    token = set_workspace_scope(ws_id)
    assert current_workspace_id() == ws_id
    reset_workspace_scope(token)
    assert current_workspace_id() is None


def test_nested_calls_keep_latest() -> None:
    outer = uuid.uuid4()
    inner = uuid.uuid4()
    t1 = set_workspace_scope(outer)
    assert current_workspace_id() == outer
    t2 = set_workspace_scope(inner)
    assert current_workspace_id() == inner
    reset_workspace_scope(t2)
    assert current_workspace_id() == outer
    reset_workspace_scope(t1)
    assert current_workspace_id() is None


def test_require_workspace_id_raises_when_unset() -> None:
    with pytest.raises(RuntimeError, match="No workspace_id"):
        require_workspace_id()


def test_require_workspace_id_returns_when_set() -> None:
    ws_id = uuid.uuid4()
    token = set_workspace_scope(ws_id)
    try:
        assert require_workspace_id() == ws_id
    finally:
        reset_workspace_scope(token)


def test_with_workspace_scope_context_manager() -> None:
    ws_id = uuid.uuid4()
    with with_workspace_scope(ws_id):
        assert current_workspace_id() == ws_id
    assert current_workspace_id() is None


def test_with_workspace_scope_resets_on_exception() -> None:
    ws_id = uuid.uuid4()
    with pytest.raises(ValueError), with_workspace_scope(ws_id):
        assert current_workspace_id() == ws_id
        raise ValueError("boom")
    assert current_workspace_id() is None
