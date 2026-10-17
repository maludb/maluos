"""Tests for M12: the documents route resolves the subject types an extraction uses before it ingests (no Postgres: the
catalogue and the register facade are faked)."""

from __future__ import annotations

from app.helpers.subject_types import resolve_subject_types, slug_of


class FakeCatalog:
    def __init__(self, types, can_register=True):
        self.types, self.can, self.registered = set(types), can_register, []

    def __call__(self, conn, sql, params=None):
        if "FROM maludb_subject_type" in sql:
            return [{"subject_type": t} for t in sorted(self.types)]
        if "to_regproc" in sql:
            return [{"ok": self.can}]
        if "maludb_register_subject_type" in sql:
            self.registered.append(params[0])
            self.types.add(params[0])
            return [{"registered": True}]
        raise AssertionError(sql)


def test_known_types_pass_through_and_unknown_ones_are_registered_once():
    q = FakeCatalog({"person", "equipment", "other"})
    out = resolve_subject_types(None, ["person", "product", "product", "policy"], "other", q)
    assert out == {"person": "person", "product": "product", "policy": "policy"}
    assert q.registered == ["product", "policy"]


def test_a_declared_type_is_slugged_before_it_is_registered():
    q = FakeCatalog({"other"})
    out = resolve_subject_types(None, ["Spare Part"], "other", q)
    assert out == {"Spare Part": "spare_part"} and q.registered == ["spare_part"]
    assert slug_of(" Line-Item ") == "line_item"


def test_without_the_register_facade_unknown_types_fall_back():
    q = FakeCatalog({"person", "other"}, can_register=False)
    out = resolve_subject_types(None, ["product", "person"], "other", q)
    assert out == {"product": "other", "person": "person"} and q.registered == []


def test_a_name_the_catalogue_cannot_hold_falls_back_to_the_default_type():
    q = FakeCatalog({"concept", "other"})
    out = resolve_subject_types(None, ["9lives"], "concept", q)
    assert out == {"9lives": "concept"} and q.registered == []


def test_the_fallback_is_a_generic_type_when_the_default_is_unknown():
    q = FakeCatalog({"other"}, can_register=False)
    assert resolve_subject_types(None, ["product"], "missing_default", q) == {"product": "other"}
