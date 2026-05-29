from __future__ import annotations

from enum import IntEnum
from typing import Callable

import discord
from discord import app_commands

from config import cfg


class Tier(IntEnum):
    MOD = 1
    ADMIN = 2
    OWNER = 3


def _user_tier(interaction: discord.Interaction) -> Tier:
    user_id = interaction.user.id

    if user_id in cfg.owner_users:
        return Tier.OWNER
    if interaction.guild and interaction.guild.owner_id == user_id:
        return Tier.OWNER

    if isinstance(interaction.user, discord.Member):
        role_ids = {r.id for r in interaction.user.roles}
        if role_ids & set(cfg.admin_roles):
            return Tier.ADMIN
        if role_ids & set(cfg.mod_roles):
            return Tier.MOD

    return Tier.MOD


def require_tier(tier: Tier) -> Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if _user_tier(interaction) >= tier:
            return True
        await interaction.response.send_message(
            "You don't have permission to use this command.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


require_mod = require_tier(Tier.MOD)
require_admin = require_tier(Tier.ADMIN)
require_owner = require_tier(Tier.OWNER)
