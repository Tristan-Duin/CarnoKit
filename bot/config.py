from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import List, Optional

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"
_CONFIG_PATH = Path(os.environ.get("CARNOKIT_CONFIG", str(_DEFAULT_CONFIG)))


def _split_ids(raw: str) -> List[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _opt_int(value: str) -> Optional[int]:
    value = value.strip()
    if not value:
        return None
    return int(value)


class Settings:
    def __init__(self, path: Path = _CONFIG_PATH):
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        self.server_dir = Path(cp.get("server", "dir", fallback="C:/ASA/server"))
        self.server_map = cp.get("server", "map", fallback="TheIsland_WP")
        self.server_session_name = cp.get("server", "session_name", fallback="GameServer")
        self.server_join_password = cp.get("server", "join_password", fallback="")
        self.server_admin_password = cp.get("server", "admin_password", fallback="")
        self.server_max_players = cp.getint("server", "max_players", fallback=70)
        self.log_file_path = Path(cp.get(
            "server", "log_file",
            fallback="C:/ASA/server/ShooterGame/Saved/Logs/ShooterGame.log",
        ))

        self.rcon_host = cp.get("rcon", "host", fallback="127.0.0.1")
        self.rcon_port = cp.getint("rcon", "port", fallback=27020)
        self.rcon_password = cp.get("rcon", "password", fallback="")

        self.discord_token = cp.get("discord", "token", fallback="")
        self._admin_role_ids = cp.get("discord", "admin_role_ids", fallback="")
        self._mod_role_ids = cp.get("discord", "mod_role_ids", fallback="")
        self._owner_user_ids = cp.get("discord", "owner_user_ids", fallback="")
        self.alerts_channel_id = _opt_int(
            cp.get("discord", "alerts_channel_id", fallback="")
        )

        self.steamcmd_path = Path(cp.get(
            "steamcmd", "path", fallback="C:/ASA/steamcmd/steamcmd.exe",
        ))
        self.update_check_minutes = cp.getint("steamcmd", "update_check_minutes", fallback=15)
        self.update_countdown_minutes = cp.getint("steamcmd", "update_countdown_minutes", fallback=30)

        self.schedule_file = Path(cp.get("scheduler", "schedule_file", fallback="schedules.json"))
        self.auto_save_minutes = cp.getint("scheduler", "auto_save_minutes", fallback=15)
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
    def server_exe(self) -> Path:
        return self.server_dir / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"

    @property
    def server_launch_args(self) -> str:
        parts = [
            f"{self.server_map}?listen",
            f"?SessionName={self.server_session_name}",
            f"?Port=7777",
            f"?QueryPort=27015",
            f"?MaxPlayers={self.server_max_players}",
            f"?ServerAdminPassword={self.server_admin_password}",
            f"?RCONPort={self.rcon_port}",
            f"?RCONEnabled=True",
        ]
        if self.server_join_password:
            parts.append(f"?ServerPassword={self.server_join_password}")
        return "".join(parts) + " -NoBattlEye -log"


cfg = Settings()
