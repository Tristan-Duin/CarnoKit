"""Boss fight countdown signups driven by Discord reactions."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from utils import embeds
from utils.formatting import countdown_label

log = logging.getLogger(__name__)

_DEFAULT_EMOJI = "\N{CROSSED SWORDS}"
_MAX_HOURS = 168.0
_SURVIVER_ROLE_MENTION = "<@&1526687172609179790>"
_COUNTDOWN_REFRESH_SECONDS = 60


class _BossCountdown:
    """One active boss fight countdown and its reaction roster."""

    def __init__(
        self,
        *,
        id: str,
        channel_id: int,
        message_id: int,
        creator_id: int,
        title: str,
        emoji: str,
        end_ts: int,
        participants: Optional[list[int]] = None,
    ):
        self.id = id
        self.channel_id = channel_id
        self.message_id = message_id
        self.creator_id = creator_id
        self.title = title
        self.emoji = emoji
        self.end_ts = end_ts
        self.participants = participants or []
        self.task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "creator_id": self.creator_id,
            "title": self.title,
            "emoji": self.emoji,
            "end_ts": self.end_ts,
            "participants": self.participants,
        }


class BossCog(commands.GroupCog, group_name="boss"):
    """Start and track boss fight countdown rosters."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._countdowns: dict[int, _BossCountdown] = {}
        self._lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self._load_state()
        for countdown in self._countdowns.values():
            countdown.task = asyncio.create_task(self._run_countdown(countdown))

    async def cog_unload(self) -> None:
        for countdown in self._countdowns.values():
            if countdown.task and not countdown.task.done():
                countdown.task.cancel()

    @app_commands.command(name="start", description="Start a boss fight countdown with reaction signups")
    @app_commands.describe(
        hours="How many hours until the boss fight starts",
        title="Boss fight name shown on the signup message",
        emoji="Emoji people react with to join",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        hours: float,
        title: str = "Boss Fight",
        emoji: str = _DEFAULT_EMOJI,
    ):
        if hours <= 0 or hours > _MAX_HOURS:
            return await interaction.response.send_message(
                embed=embeds.error("Invalid Countdown", f"Hours must be greater than 0 and no more than {_MAX_HOURS:g}."),
                ephemeral=True,
            )

        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=embeds.error("Unsupported Channel", "Boss countdowns can only be started in a server text channel."),
                ephemeral=True,
            )

        countdown = _BossCountdown(
            id=str(uuid.uuid4())[:8],
            channel_id=interaction.channel.id,
            message_id=0,
            creator_id=interaction.user.id,
            title=(title.strip() or "Boss Fight")[:80],
            emoji=emoji.strip() or _DEFAULT_EMOJI,
            end_ts=int(time.time()) + int(hours * 3600),
        )

        await interaction.response.send_message(
            content=(
                f"{_SURVIVER_ROLE_MENTION} there is a boss fight coming up. "
                f"React with {countdown.emoji} to join the fight!"
            ),
            embed=self._countdown_embed(countdown),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        message = await interaction.original_response()
        countdown.message_id = message.id

        try:
            await message.add_reaction(countdown.emoji)
        except discord.HTTPException as exc:
            log.warning("Failed to add boss signup reaction %r: %s", countdown.emoji, exc)
            await message.edit(
                embed=embeds.warning(
                    "Boss Countdown Not Started",
                    f"I could not add `{countdown.emoji}` as a reaction. Try a standard emoji or a custom emoji I can access.",
                )
            )
            return

        async with self._lock:
            self._countdowns[countdown.message_id] = countdown
            countdown.task = asyncio.create_task(self._run_countdown(countdown))
            self._save_state()

    @app_commands.command(name="list", description="Show active boss fight countdowns")
    async def list_countdowns(self, interaction: discord.Interaction):
        active = sorted(self._countdowns.values(), key=lambda c: c.end_ts)
        if not active:
            return await interaction.response.send_message(embed=embeds.info("Boss Countdowns", "No active boss fight countdowns."))

        lines = []
        for countdown in active:
            lines.append(
                f"**{countdown.title}** `{countdown.id}` - <t:{countdown.end_ts}:R> "
                f"with {len(countdown.participants)} signed up"
            )
        await interaction.response.send_message(embed=embeds.info("Boss Countdowns", "\n".join(lines)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        await self._set_participant(payload, joined=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._set_participant(payload, joined=False)

    async def _set_participant(self, payload: discord.RawReactionActionEvent, *, joined: bool) -> None:
        async with self._lock:
            countdown = self._countdowns.get(payload.message_id)
            if countdown is None or str(payload.emoji) != countdown.emoji:
                return
            if int(time.time()) >= countdown.end_ts:
                return

            user_id = payload.user_id
            changed = False
            if joined and user_id not in countdown.participants:
                countdown.participants.append(user_id)
                changed = True
            elif not joined and user_id in countdown.participants:
                countdown.participants.remove(user_id)
                changed = True

            if not changed:
                return

            self._save_state()

        await self._refresh_message(countdown)

    async def _run_countdown(self, countdown: _BossCountdown) -> None:
        try:
            while True:
                remaining = countdown.end_ts - int(time.time())
                if remaining <= 0:
                    break
                await asyncio.sleep(min(_COUNTDOWN_REFRESH_SECONDS, remaining))
                if int(time.time()) < countdown.end_ts:
                    await self._refresh_message(countdown)
            await self._finish_countdown(countdown)
        except asyncio.CancelledError:
            pass

    async def _finish_countdown(self, countdown: _BossCountdown) -> None:
        async with self._lock:
            current = self._countdowns.pop(countdown.message_id, None)
            if current is None:
                return
            self._save_state()

        for user_id in list(countdown.participants):
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                await user.send(f"{countdown.title} is starting now. Boss fight time!")
            except Exception as exc:
                log.warning("Failed to DM boss countdown participant %s: %s", user_id, exc)

        await self._refresh_message(countdown, finished=True)

    async def _refresh_message(self, countdown: _BossCountdown, *, finished: bool = False) -> None:
        channel = self.bot.get_channel(countdown.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(countdown.message_id)
            await message.edit(embed=self._countdown_embed(countdown, finished=finished))
        except discord.NotFound:
            async with self._lock:
                self._countdowns.pop(countdown.message_id, None)
                self._save_state()
        except Exception as exc:
            log.warning("Failed to refresh boss countdown %s: %s", countdown.id, exc)

    def _countdown_embed(self, countdown: _BossCountdown, *, finished: bool = False) -> discord.Embed:
        if finished:
            description = "Boss fight time! Signed-up players have been sent a DM."
            color = embeds.COLOR_OK
        else:
            remaining = max(0, countdown.end_ts - int(time.time()))
            description = (
                f"React with {countdown.emoji} to join.\n"
                f"Starts: <t:{countdown.end_ts}:F> (<t:{countdown.end_ts}:R>)\n"
                f"Remaining: **{countdown_label(remaining)}**"
            )
            color = embeds.COLOR_WARN

        embed = discord.Embed(title=countdown.title, description=description, color=color)
        embed.add_field(name="Joining", value=self._participant_list(countdown.participants), inline=False)
        embed.set_footer(text=f"Boss countdown ID: {countdown.id}")
        return embed

    def _participant_list(self, participants: list[int]) -> str:
        if not participants:
            return "No one yet."
        lines = [f"{index}. <@{user_id}>" for index, user_id in enumerate(participants[:45], start=1)]
        if len(participants) > 45:
            lines.append(f"...and {len(participants) - 45} more.")
        return "\n".join(lines)

    @property
    def _state_path(self) -> Path:
        return cfg.boss_countdown_file

    def _save_state(self) -> None:
        data = [countdown.to_dict() for countdown in self._countdowns.values()]
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            for item in data:
                countdown = _BossCountdown(
                    id=item["id"],
                    channel_id=int(item["channel_id"]),
                    message_id=int(item["message_id"]),
                    creator_id=int(item.get("creator_id", 0)),
                    title=item.get("title", "Boss Fight"),
                    emoji=item.get("emoji", _DEFAULT_EMOJI),
                    end_ts=int(item["end_ts"]),
                    participants=[int(user_id) for user_id in item.get("participants", [])],
                )
                self._countdowns[countdown.message_id] = countdown
        except Exception as exc:
            log.warning("Failed to load boss countdowns: %s", exc)


async def setup(bot: commands.Bot):
    await bot.add_cog(BossCog(bot))
