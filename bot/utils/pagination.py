from __future__ import annotations

import discord


class PaginatedView(discord.ui.View):

    def __init__(self, embeds: list[discord.Embed], *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current <= 0
        self.next_btn.disabled = self.current >= len(self.embeds) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = min(len(self.embeds) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)
