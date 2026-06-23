"""Centralised configuration for the ASA cluster tooling.

Reads the shared ``/opt/asa-cluster/config.ini`` (override with the
``ASA_CONFIG`` environment variable). Supports a multi-server cluster via
the ``[servers]`` list and one ``[server.<key>]`` section per map.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:  # discord is only needed for server_choices(); keep config importable without it
    from discord import app_commands
except Exception:  # pragma: no cover
    app_commands = None  # type: ignore[assignment]

# Locate the shared config file.  Override with the ASA_CONFIG env var.
_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"
_CONFIG_PATH = Path(os.environ.get("ASA_CONFIG", str(_DEFAULT_CONFIG)))


def _split_ids(raw: str) -> List[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _opt_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    return int(value)


@dataclass
class ServerConfig:
    """Settings for a single map in the cluster."""

    key: str
    name: str
    map: str
    game_port: int
    rcon_port: int
    container: str
    log_file: Path

    @property
    def server_files(self) -> Path:
        """Path to this server's ``server-files`` directory.

        Derived from ``log_file`` which is
        ``<server-files>/ShooterGame/Saved/Logs/ShooterGame.log``.
        """
        return self.log_file.parents[3]


class Settings:
    """All configuration used by the cluster tooling, loaded from config.ini."""

    def __init__(self, path: Path = _CONFIG_PATH):
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        self._cp = cp

        # [cluster]
        self.base_dir = Path(cp.get("cluster", "base_dir", fallback="/opt/asa-cluster"))
        self.compose_project = cp.get("cluster", "compose_project", fallback="asa-cluster")
        self.cluster_id = cp.get("cluster", "cluster_id", fallback="arkcluster01")
        self.mods = cp.get("cluster", "mods", fallback="")
        self.admin_password = cp.get("cluster", "admin_password", fallback="")
        self.join_password = cp.get("cluster", "join_password", fallback="")
        self.max_players = cp.getint("cluster", "max_players", fallback=70)
        self.rcon_host = cp.get("cluster", "rcon_host", fallback="127.0.0.1")

        # [discord]
        self.discord_token = cp.get("discord", "token", fallback="")
        self._admin_role_ids = cp.get("discord", "admin_role_ids", fallback="")
        self._mod_role_ids = cp.get("discord", "mod_role_ids", fallback="")
        self._owner_user_ids = cp.get("discord", "owner_user_ids", fallback="")
        self.alerts_channel_id = _opt_int(cp.get("discord", "alerts_channel_id", fallback=""))

        # [steamcmd]
        self.asa_app_id = cp.get("steamcmd", "asa_app_id", fallback="2430930")
        self.update_check_minutes = cp.getint("steamcmd", "update_check_minutes", fallback=15)
        self.update_countdown_minutes = cp.getint("steamcmd", "update_countdown_minutes", fallback=30)

        # [scheduler]
        self.schedule_file = Path(cp.get("scheduler", "schedule_file", fallback="schedules.json"))
        self.auto_save_minutes = cp.getint("scheduler", "auto_save_minutes", fallback=10)

        # [servers] + [server.<key>]
        self.servers: Dict[str, ServerConfig] = {}
        raw_list = cp.get("servers", "list", fallback="")
        for key in [k.strip() for k in raw_list.split(",") if k.strip()]:
            section = f"server.{key}"
            if not cp.has_section(section):
                continue
            self.servers[key] = ServerConfig(
                key=key,
                name=cp.get(section, "name", fallback=key),
                map=cp.get(section, "map", fallback="TheIsland_WP"),
                game_port=cp.getint(section, "game_port", fallback=7777),
                rcon_port=cp.getint(section, "rcon_port", fallback=27020),
                container=cp.get(section, "container", fallback=f"asa-{key}"),
                log_file=Path(cp.get(section, "log_file", fallback="")),
            )

    # --- Derived helpers ---

    @property
    def admin_roles(self) -> List[int]:
        return _split_ids(self._admin_role_ids)

    @property
    def mod_roles(self) -> List[int]:
        return _split_ids(self._mod_role_ids)

    @property
    def owner_users(self) -> List[int]:
        return _split_ids(self._owner_user_ids)

    @property
    def mods_list(self) -> List[str]:
        return [m.strip() for m in self.mods.split(",") if m.strip()]

    @property
    def default_server_key(self) -> str:
        return next(iter(self.servers), "")

    def server(self, key: Optional[str]) -> ServerConfig:
        """Return the requested server, or the first one if key is falsy/unknown."""
        if key and key in self.servers:
            return self.servers[key]
        return self.servers[self.default_server_key]


cfg = Settings()


def server_choices() -> list:
    """Discord ``app_commands.Choice`` list for a ``server`` command argument."""
    if app_commands is None:
        return []
    return [app_commands.Choice(name=s.name, value=k) for k, s in cfg.servers.items()]
