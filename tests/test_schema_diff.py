"""Schema version diff: field-level comparison between two snapshots.

Versions are additive history — nothing is edited in place — so the only
way to see what a revision changed is to compare two snapshots. The diff
reports added/removed types and per-field old→new values for changed
ones.
"""

from __future__ import annotations


def _v1(store):
    return store.install_schema(
        label="v1",
        description="",
        entity_types=[
            {"name": "Gene", "description": "a gene", "attributes": {}},
            {"name": "Disease", "description": "a disease", "attributes": {}},
            {"name": "Legacy", "description": "going away", "attributes": {}},
        ],
        relation_types=[
            {"name": "causes", "description": "x", "domain_type": "Gene",
             "range_type": "Disease", "directed": True},
        ],
    )


def test_diff_reports_added_removed_changed(store):
    a = _v1(store)
    b = store.install_schema(
        label="v2",
        description="",
        entity_types=[
            {"name": "Gene", "description": "a gene or locus",
             "attributes": {"symbol": "text"}},
            {"name": "Disease", "description": "a disease", "attributes": {}},
            {"name": "Drug", "description": "new", "attributes": {}},
        ],
        relation_types=[
            {"name": "causes", "description": "x", "domain_type": "*",
             "range_type": "Disease", "directed": True},
            {"name": "treats", "description": "x", "domain_type": "Drug",
             "range_type": "Disease", "directed": True},
        ],
    )
    d = store.diff_schema_versions(a, b)
    assert d["entity_types"]["added"] == ["Drug"]
    assert d["entity_types"]["removed"] == ["Legacy"]
    changed = {c["name"]: c["fields"] for c in d["entity_types"]["changed"]}
    assert changed["Gene"]["description"] == {
        "from": "a gene", "to": "a gene or locus"
    }
    assert changed["Gene"]["attributes"] == {
        "from": {}, "to": {"symbol": "text"}
    }
    assert d["relation_types"]["added"] == ["treats"]
    rel_changed = {c["name"]: c["fields"]
                   for c in d["relation_types"]["changed"]}
    assert rel_changed["causes"]["domain_type"] == {
        "from": "Gene", "to": "*"
    }


def test_identical_versions_diff_empty(store):
    a = _v1(store)
    d = store.diff_schema_versions(a, a)
    assert d["entity_types"] == {"added": [], "removed": [], "changed": []}
    assert d["relation_types"] == {"added": [], "removed": [], "changed": []}


def test_parent_change_is_a_field_diff(store):
    a = _v1(store)
    b = store.install_schema(
        label="v2",
        description="",
        entity_types=[
            {"name": "Gene", "description": "a gene", "attributes": {}},
            {"name": "Disease", "description": "a disease", "attributes": {}},
            {"name": "Legacy", "description": "going away", "attributes": {},
             "parent": "Gene"},
        ],
        relation_types=[
            {"name": "causes", "description": "x", "domain_type": "Gene",
             "range_type": "Disease", "directed": True},
        ],
    )
    d = store.diff_schema_versions(a, b)
    changed = {c["name"]: c["fields"] for c in d["entity_types"]["changed"]}
    assert changed["Legacy"]["parent"] == {"from": None, "to": "Gene"}
