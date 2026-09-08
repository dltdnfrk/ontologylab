"""Desktop-only backend entry point for the inherited supervisor socket."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, assert_never

import uvicorn
from pydantic import BaseModel, ConfigDict, Field

from ontologylab.desktop_logging import (
    DesktopLogPolicy,
    configure_desktop_logging,
)
from ontologylab.desktop_state import DesktopPaths, SuppliedDesktopPaths
from ontologylab.server import settings as settings_mod
from ontologylab.server.app import create_app
from ontologylab.storage_compatibility import (
    CURRENT_STORAGE_VERSION,
    preflight_storage,
)
from ontologylab.storage_quiescence import load_quiescence_proof
from ontologylab.storage_types import (
    CompatibilityState,
    StorageCompatibilityRefused,
    StorageHandshakeRefused,
)
from ontologylab.storage_upgrade import UpgradeRequest, run_staged_upgrade
from ontologylab.storage_upgrade_journal import JOURNAL_NAME

_READY_SCHEMA: Final = "ontologylab-ready-v1"
_NONCE_PATTERN: Final = r"^[0-9a-f]{32}$"


@dataclass(frozen=True, slots=True)
class DesktopSocketError(Exception):
    member: str

    def __str__(self) -> str:
        return f"desktop socket refused: {self.member}"


@dataclass(frozen=True, slots=True)
class ReadinessWriteError(Exception):
    expected: int
    written: int

    def __str__(self) -> str:
        return f"readiness write was short: {self.written}/{self.expected}"


class DesktopEnvironment(BaseModel):
    """Parsed supervisor-owned process boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    listener_fd: Annotated[int, Field(ge=0)]
    ready_fd: Annotated[int, Field(ge=0)]
    nonce: Annotated[str, Field(pattern=_NONCE_PATTERN)]
    version: Annotated[str, Field(min_length=1)]
    storage_version: Annotated[str, Field(min_length=1)]
    supervisor_pid: Annotated[int, Field(gt=0)]
    quiescence_receipt: Path
    resources_dir: Path
    data_dir: Path
    packs_dir: Path
    logs_dir: Path
    runtime_dir: Path

    @classmethod
    def from_process(cls) -> DesktopEnvironment:
        """Parse and preflight the exact fields supplied by the Swift parent."""
        environment = cls.model_validate(
            {
                "listener_fd": os.environ.get("ONTOLOGYLAB_LISTENER_FD"),
                "ready_fd": os.environ.get("ONTOLOGYLAB_READY_FD"),
                "nonce": os.environ.get("ONTOLOGYLAB_NONCE"),
                "version": os.environ.get("ONTOLOGYLAB_APP_VERSION"),
                "storage_version": os.environ.get("ONTOLOGYLAB_STORAGE_VERSION"),
                "supervisor_pid": os.environ.get("ONTOLOGYLAB_SUPERVISOR_PID"),
                "quiescence_receipt": os.environ.get(
                    "ONTOLOGYLAB_QUIESCENCE_RECEIPT"
                ),
                "resources_dir": os.environ.get("ONTOLOGYLAB_RESOURCES_DIR"),
                "data_dir": os.environ.get("ONTOLOGYLAB_DATA_DIR"),
                "packs_dir": os.environ.get("ONTOLOGYLAB_PACKS_DIR"),
                "logs_dir": os.environ.get("ONTOLOGYLAB_LOG_DIR"),
                "runtime_dir": os.environ.get("ONTOLOGYLAB_RUNTIME_DIR"),
            }
        )
        environment.paths.require_supplied_paths(
            SuppliedDesktopPaths(
                data_dir=environment.data_dir,
                packs_dir=environment.packs_dir,
                logs_dir=environment.logs_dir,
                runtime_dir=environment.runtime_dir,
            )
        )
        return environment

    @property
    def paths(self) -> DesktopPaths:
        return DesktopPaths.for_home(Path.home(), self.resources_dir)


class ReadyPayload(BaseModel):
    """Machine-consumed readiness protocol payload."""

    model_config = ConfigDict(frozen=True, strict=True)

    contract_schema: Literal["ontologylab-ready-v1"] = Field(alias="schema")
    version: str
    port: Annotated[int, Field(gt=0, le=65535)]
    nonce: Annotated[str, Field(pattern=_NONCE_PATTERN)]
    storage_version: str


class DesktopServer(uvicorn.Server):
    """Uvicorn server that emits readiness only after application startup."""

    def __init__(
        self,
        config: uvicorn.Config,
        payload: ReadyPayload,
        ready_fd: int,
    ) -> None:
        super().__init__(config)
        self._payload = payload
        self._ready_fd = ready_fd

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Start the inherited listener, then atomically publish one JSON line."""
        await super().startup(sockets=sockets)
        line = self._payload.model_dump_json(by_alias=True).encode() + b"\n"
        written = os.write(self._ready_fd, line)
        if written != len(line):
            raise ReadinessWriteError(expected=len(line), written=written)
        os.close(self._ready_fd)


def main() -> None:
    """Serve the dashboard on the supervisor's inherited loopback socket."""
    environment = DesktopEnvironment.from_process()
    if environment.storage_version != str(CURRENT_STORAGE_VERSION):
        raise StorageHandshakeRefused(
            expected=CURRENT_STORAGE_VERSION,
            received=environment.storage_version,
        )
    storage = preflight_storage(environment.data_dir, environment.packs_dir)
    match storage.state:
        case CompatibilityState.SUPPORTED_OLDER:
            upgrade_required = True
        case CompatibilityState.UNKNOWN if storage.inventory.wal_present:
            upgrade_required = True
        case (
            CompatibilityState.BOOTSTRAP_REQUIRED
            | CompatibilityState.CURRENT
            | CompatibilityState.NEWER
            | CompatibilityState.UNKNOWN
            | CompatibilityState.CORRUPT
        ):
            upgrade_required = False
        case unreachable:
            assert_never(unreachable)
    upgrade_required = upgrade_required or (
        environment.paths.application_support_dir / JOURNAL_NAME
    ).is_file()
    if upgrade_required:
        environment.paths.prepare()
        run_staged_upgrade(
            UpgradeRequest(
                application_support_dir=environment.paths.application_support_dir,
                data_dir=environment.data_dir,
                packs_dir=environment.packs_dir,
                backups_dir=environment.paths.backups_dir,
                quiescence=load_quiescence_proof(
                    environment.quiescence_receipt,
                    supervisor_pid=environment.supervisor_pid,
                    nonce=environment.nonce,
                    data_dir=environment.data_dir,
                ),
            )
        )
        storage = preflight_storage(environment.data_dir, environment.packs_dir)
    if not storage.starts_without_migration:
        raise StorageCompatibilityRefused(storage)
    environment.paths.prepare()
    logger = configure_desktop_logging(
        environment.paths,
        DesktopLogPolicy(sensitive_values=(environment.nonce,)),
    )
    logger.info("desktop.backend.start")
    with socket.socket(fileno=environment.listener_fd) as listener:
        host, port = listener.getsockname()
        if host != "127.0.0.1":
            raise DesktopSocketError(member="host")
        settings_mod.apply_to_environment(
            settings_mod.load_settings(environment.data_dir)
        )
        app = create_app(
            data_dir=environment.data_dir,
            packs_dir=environment.packs_dir,
        )
        server = DesktopServer(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="info",
                log_config=None,
            ),
            ReadyPayload(
                schema=_READY_SCHEMA,
                version=environment.version,
                port=port,
                nonce=environment.nonce,
                storage_version=environment.storage_version,
            ),
            environment.ready_fd,
        )
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
