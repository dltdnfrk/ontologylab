"""Store-boundary ontology validation for proposed writes.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ontologylab import ontology_schema as default_schema

from ontologylab.kgstore_base import (
    SchemaValidationError,
)

class ValidationMixin:

    # ------------------------------------------------------------------
    # Store-boundary ontology validation
    # ------------------------------------------------------------------

    # Curated-resource annotations are platform-owned property blocks rather
    # than extractor-defined attributes. They predate user-installable schemas
    # and are part of every schema's store contract; arbitrary resource names
    # remain off-schema and fail closed.
    _ANNOTATION_PROPERTY_BLOCKS = frozenset(
        {"uniprot", "mygene", "alias_authority"}
    )
    # ``tier`` was accepted by the original default Component store contract
    # and is exercised by the merge API. Keep that historical write valid
    # without changing persisted schemas or exported pack schema bytes.
    _LEGACY_DEFAULT_PROPERTIES = {
        "Component": {
            "tier": {"type": "string", "required": False},
            "purpose": {"type": "string", "required": False},
            "notes": {"type": "string", "required": False},
            "produced_by_failed_stream": {"type": "string", "required": False},
        },
        "Technique": {"category": {"type": "string", "required": False}},
    }
    _LEGACY_DEFAULT_ENTITY_TYPES = frozenset({"Gene", "Disease"})
    _LEGACY_DEFAULT_RELATIONS = {
        "controls": {
            "name": "controls",
            "domain_type": "*",
            "range_type": "*",
            "directed": 1,
        }
    }
    _NORMALIZATION_PROPERTIES = frozenset(
        {
            "eppo_matched_surface",
            "eppo_code_dropped",
            "cas_matched_surface",
            "cas_number_dropped",
            "moa_scheme",
            "moa_code",
            "normalization",
            "eppo_unattested_match_refused",
            "cas_unattested_match_refused",
            # Marks a parser-minted relation endpoint (never observed in the
            # text) so the review surface can show it as synthesized.
            "synthesized_endpoint",
        }
    )

    def _schema_definition(self, schema_version_id: int) -> dict[str, Any]:
        """Load one immutable ontology version by id, never via active state."""
        version = self.conn.execute(
            "SELECT id, label FROM schema_version WHERE id = ?", (schema_version_id,)
        ).fetchone()
        if version is None:
            raise SchemaValidationError(
                f"unknown schema version {schema_version_id!r}"
            )
        entities: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(
            "SELECT name, attributes_json FROM entity_type "
            "WHERE schema_version_id = ?",
            (schema_version_id,),
        ):
            try:
                attributes = json.loads(row["attributes_json"] or "{}")
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"schema {schema_version_id} entity type {row['name']!r} "
                    "has malformed attributes"
                ) from exc
            if not isinstance(attributes, dict):
                raise SchemaValidationError(
                    f"schema {schema_version_id} entity type {row['name']!r} "
                    "attributes must be an object"
                )
            entities[row["name"]] = attributes
        relations: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(
            "SELECT name, domain_type, range_type, directed, qualifiers_json "
            "FROM relation_type WHERE schema_version_id = ?",
            (schema_version_id,),
        ):
            try:
                qualifiers = json.loads(row["qualifiers_json"] or "{}")
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"schema {schema_version_id} relation type {row['name']!r} "
                    "has malformed qualifiers"
                ) from exc
            if not isinstance(qualifiers, dict):
                raise SchemaValidationError(
                    f"schema {schema_version_id} relation type {row['name']!r} "
                    "qualifiers must be an object"
                )
            relation = dict(row)
            relation["qualifiers"] = qualifiers
            relations[row["name"]] = relation
        return {
            "label": version["label"],
            "entities": entities,
            "relations": relations,
        }

    @staticmethod
    def _value_matches_type(value: Any, expected: str) -> bool:
        if expected == "string":
            return isinstance(value, str) and bool(value.strip())
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return False

    def _validate_properties(
        self,
        *,
        schema_version_id: int,
        entity_type: str,
        properties: Any,
        schema: dict[str, Any] | None = None,
    ) -> None:
        definition = schema or self._schema_definition(schema_version_id)
        attributes = definition["entities"].get(entity_type)
        if (
            attributes is None
            and definition["label"] == default_schema.DEFAULT_SCHEMA_LABEL
            and entity_type in self._LEGACY_DEFAULT_ENTITY_TYPES
        ):
            attributes = {}
        if attributes is None:
            raise SchemaValidationError(
                f"entity type {entity_type!r} is not declared in schema "
                f"{schema_version_id}"
            )
        if not isinstance(properties, dict):
            raise SchemaValidationError(
                f"properties for entity type {entity_type!r} must be an object"
            )
        for key, value in properties.items():
            if key in self._ANNOTATION_PROPERTY_BLOCKS:
                if not isinstance(value, dict):
                    raise SchemaValidationError(
                        f"annotation property {key!r} must be an object"
                    )
                continue
            spec = attributes.get(key)
            if key in self._NORMALIZATION_PROPERTIES:
                spec = {"type": "string", "required": False}
            if spec is None and definition["label"] == default_schema.DEFAULT_SCHEMA_LABEL:
                spec = self._LEGACY_DEFAULT_PROPERTIES.get(entity_type, {}).get(key)
            if not isinstance(spec, dict):
                raise SchemaValidationError(
                    f"undeclared property {key!r} for entity type {entity_type!r} "
                    f"in schema {schema_version_id}"
                )
            expected = spec.get("type", "string")
            if not isinstance(expected, str) or not self._value_matches_type(
                value, expected
            ):
                raise SchemaValidationError(
                    f"property {key!r} for entity type {entity_type!r} must be "
                    f"a non-empty {expected}"
                )
            enum = spec.get("enum")
            if enum is not None and (
                not isinstance(enum, list) or value not in enum
            ):
                raise SchemaValidationError(
                    f"property {key!r} value {value!r} is outside its enum"
                )
            if isinstance(value, str):
                minimum = spec.get("minLength")
                maximum = spec.get("maxLength")
                pattern = spec.get("pattern")
                if isinstance(minimum, int) and len(value) < minimum:
                    raise SchemaValidationError(
                        f"property {key!r} is shorter than minLength {minimum}"
                    )
                if isinstance(maximum, int) and len(value) > maximum:
                    raise SchemaValidationError(
                        f"property {key!r} is longer than maxLength {maximum}"
                    )
                if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
                    raise SchemaValidationError(
                        f"property {key!r} does not match its pattern"
                    )
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum = spec.get("minimum")
                maximum = spec.get("maximum")
                if isinstance(minimum, (int, float)) and value < minimum:
                    raise SchemaValidationError(
                        f"property {key!r} is below minimum {minimum}"
                    )
                if isinstance(maximum, (int, float)) and value > maximum:
                    raise SchemaValidationError(
                        f"property {key!r} is above maximum {maximum}"
                    )
        missing = [
            key
            for key, spec in attributes.items()
            if isinstance(spec, dict) and spec.get("required") and key not in properties
        ]
        if missing:
            raise SchemaValidationError(
                f"entity type {entity_type!r} is missing required properties "
                f"{sorted(missing)}"
            )

    def _validate_qualifiers(
        self,
        *,
        schema_version_id: int,
        relation_type: str,
        qualifiers: Any,
        specs: Any,
    ) -> None:
        if not isinstance(qualifiers, dict):
            raise SchemaValidationError(
                f"qualifiers for relation type {relation_type!r} must be an object"
            )
        if not isinstance(specs, dict):
            raise SchemaValidationError(
                f"relation type {relation_type!r} in schema {schema_version_id} "
                "has malformed qualifier specs"
            )
        for name, value in qualifiers.items():
            spec = specs.get(name)
            if not isinstance(spec, dict):
                raise SchemaValidationError(
                    f"undeclared qualifier {name!r} for relation type "
                    f"{relation_type!r} in schema {schema_version_id}"
                )
            expected = spec.get("type", "string")
            if not isinstance(expected, str) or not self._value_matches_type(
                value, expected
            ):
                raise SchemaValidationError(
                    f"qualifier {name!r} for relation type {relation_type!r} "
                    f"must be a non-empty {expected}"
                )
            enum = spec.get("enum")
            if enum is not None and (
                not isinstance(enum, list) or value not in enum
            ):
                raise SchemaValidationError(
                    f"qualifier {name!r} value {value!r} is outside its enum"
                )
            if isinstance(value, str):
                minimum = spec.get("minLength")
                maximum = spec.get("maxLength")
                pattern = spec.get("pattern")
                if isinstance(minimum, int) and len(value) < minimum:
                    raise SchemaValidationError(
                        f"qualifier {name!r} is shorter than minLength {minimum}"
                    )
                if isinstance(maximum, int) and len(value) > maximum:
                    raise SchemaValidationError(
                        f"qualifier {name!r} is longer than maxLength {maximum}"
                    )
                if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
                    raise SchemaValidationError(
                        f"qualifier {name!r} does not match its pattern"
                    )
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum = spec.get("minimum")
                maximum = spec.get("maximum")
                if isinstance(minimum, (int, float)) and value < minimum:
                    raise SchemaValidationError(
                        f"qualifier {name!r} is below minimum {minimum}"
                    )
                if isinstance(maximum, (int, float)) and value > maximum:
                    raise SchemaValidationError(
                        f"qualifier {name!r} is above maximum {maximum}"
                    )
        missing = [
            name
            for name, spec in specs.items()
            if isinstance(spec, dict)
            and spec.get("required")
            and name not in qualifiers
        ]
        if missing:
            raise SchemaValidationError(
                f"relation type {relation_type!r} is missing required qualifiers "
                f"{sorted(missing)}"
            )

    def _validate_relation(
        self,
        *,
        schema_version_id: int,
        relation_type: str,
        src_type: str,
        dst_type: str,
        properties: Any,
        qualifiers: Any,
        schema: dict[str, Any] | None = None,
    ) -> None:
        definition = schema or self._schema_definition(schema_version_id)
        relation = definition["relations"].get(relation_type)
        if relation is None and definition["label"] == default_schema.DEFAULT_SCHEMA_LABEL:
            relation = self._LEGACY_DEFAULT_RELATIONS.get(relation_type)
        if relation is None:
            raise SchemaValidationError(
                f"relation type {relation_type!r} is not declared in schema "
                f"{schema_version_id}"
            )
        if properties:
            raise SchemaValidationError(
                f"undeclared properties on relation type {relation_type!r}"
            )
        self._validate_qualifiers(
            schema_version_id=schema_version_id,
            relation_type=relation_type,
            qualifiers=qualifiers,
            specs=relation.get("qualifiers", {}),
        )
        domain = relation["domain_type"]
        range_ = relation["range_type"]
        if domain != "*" and src_type != domain:
            raise SchemaValidationError(
                f"relation type {relation_type!r} source type {src_type!r} "
                f"violates domain {domain!r}"
            )
        if range_ != "*" and dst_type != range_:
            raise SchemaValidationError(
                f"relation type {relation_type!r} target type {dst_type!r} "
                f"violates range {range_!r}"
            )

    def _validate_annotation_property(
        self, node: sqlite3.Row, resource: str, facts: dict[str, Any]
    ) -> None:
        try:
            existing = json.loads(node["properties_json"] or "{}")
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"node {node['id']!r} has malformed properties"
            ) from exc
        if not isinstance(existing, dict):
            raise SchemaValidationError(
                f"node {node['id']!r} properties must be an object"
            )
        proposed = dict(existing)
        proposed[resource] = facts
        self._validate_properties(
            schema_version_id=node["schema_version_id"],
            entity_type=node["entity_type"],
            properties=proposed,
        )
