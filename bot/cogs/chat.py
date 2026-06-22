"""Chat bridge cog - bidirectional Discord <-> ARK in-game chat (per-map)."""

from __future__ import annotations

from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg, server_choices
from services.chat_bridge import ChatBridge
from utils import embeds
from utils.permissions import require_admin


class ChatCog(commands.GroupCog, group_name="chat"):
    """Manage the live chat bridges between Discord and each ARK server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bridges: Dict[str, ChatBridge] = {}
        self._channel_to_key: Dict[int, str] = {}
        for key, sc in cfg.servers.items():
            if sc.chat_bridge_channel_id:
                self.bridges[key] = ChatBridge(self.bot.rcon_for(key), bot, sc)  # type: ignore[attr-defined]
                self._channel_to_key[sc.chat_bridge_channel_id] = key

    async def cog_load(self) -> None:
        for bridge in self.bridges.values():
            bridge.start()

    async def cog_unload(self) -> None:
        for bridge in self.bridges.values():
            bridge.stop()

    # ── /chat send ────────────────────────────────────────────────────────

    @app_commands.command(name="send", description="Send a message to a server's chat")
    @app_commands.describe(message="Text to send in-game", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    async def send(self, interaction: discord.Interaction, message: str, server: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        sc = cfg.server(server)
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        author = interaction.user.display_name
        bridge = self.bridges.get(sc.key)
        if bridge:
            await bridge.send_to_ark(author, message)
        else:
            await rcon.command(f"ServerChat [Discord] {author}: {message}")
        await interaction.followup.send(
            embed=embeds.success("Chat Sent", f"**{author}** -> {sc.name}: {message}"),
            ephemeral=True,
        )

    # ── /chat toggle ──────────────────────────────────────────────────────

    @app_commands.command(name="toggle", description="Enable or disable a server's chat bridge")
    @app_commands.describe(server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def toggle(self, interaction: discord.Interaction, server: Optional[str] = None):
        sc = cfg.server(server)
        bridge = self.bridges.get(sc.key)
        if not bridge:
            await interaction.response.send_message(
                embed=embeds.error("Chat Bridge", f"No chat channel configured for {sc.name}.")
            )
            return
        bridge.enabled = not bridge.enabled
        state = "enabled" if bridge.enabled else "disabled"
        await interaction.response.send_message(
            embed=embeds.info("Chat Bridge", f"Chat bridge for {sc.name} is now **{state}**.")
        )

    # ── /chat status ──────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Show chat bridge status for every map")
    async def status(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Chat Bridges", color=0x3498DB)
        for key, sc in cfg.servers.items():
            bridge = self.bridges.get(key)
            if not bridge:
                embed.add_field(name=sc.name, value="Not configured", inline=True)
                continue
            ch = bridge.channel
            chan = f"#{ch.name}" if ch else "(channel missing)"
            state = "Running" if bridge.enabled else "Stopped"
            embed.add_field(name=sc.name, value=f"{state}\n{chan}", inline=True)
        embed.set_footer(text=f"Poll interval: {cfg.chat_poll_seconds}s")
        await interaction.response.send_message(embed=embed)

    # ── Listener: relay Discord messages to the matching server ───────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        key = self._channel_to_key.get(message.channel.id)
        if not key:
            return
        bridge = self.bridges.get(key)
        if not bridge or not bridge.enabled:
            return
        await bridge.send_to_ark(message.author.display_name, message.content)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
