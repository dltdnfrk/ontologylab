"""Typed first-launch policy for the bundled desktop dashboard."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, Protocol, TypedDict

TranslationAction = Literal["translate_visible"]


class SourceConfiguration(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def keychain_account(self) -> str: ...

    @property
    def api_key_env(self) -> str: ...


class PassiveSourceView(TypedDict):
    id: str
    role: str
    label: str
    key_present: bool


def configured_source_ids(sources: Iterable[SourceConfiguration]) -> frozenset[str]:
    return frozenset(source.id for source in sources)


def passive_source_view(source: SourceConfiguration) -> PassiveSourceView:
    """Project registry configuration without resolving its credential."""
    return {
        "id": source.id,
        "role": source.role,
        "label": source.label,
        "key_present": bool(source.keychain_account or source.api_key_env),
    }


@dataclass(frozen=True, slots=True)
class OfflineLaunchPolicy:
    """Defaults that keep passive desktop use local and credential-free."""

    default_engine: Literal["mock"]
    default_model: None
    translation_action: TranslationAction


OFFLINE_LAUNCH_POLICY: Final = OfflineLaunchPolicy(
    default_engine="mock",
    default_model=None,
    translation_action="translate_visible",
)
