"""Pure lifecycle state for the Method unit of work."""

from __future__ import annotations

from ontologylab.method_validation import MethodStateError


class UnitOfWorkState:
    """Track one mutable transaction lifecycle without owning a connection."""

    __slots__ = ("active", "spent")

    active: bool
    spent: bool

    def __init__(self) -> None:
        self.active = False
        self.spent = False

    def prepare_enter(self, *, ambient_transaction: bool) -> None:
        if self.spent:
            raise MethodStateError("Method unit of work is permanently spent")
        if self.active:
            raise MethodStateError("nested Method unit of work is not allowed")
        if ambient_transaction:
            raise MethodStateError("ambient transaction ownership is not allowed")

    def mark_active(self) -> None:
        self.active = True

    def require_active(self) -> None:
        if not self.active:
            raise MethodStateError("Method unit of work is not active")

    def mark_spent(self) -> None:
        self.active = False
        self.spent = True
