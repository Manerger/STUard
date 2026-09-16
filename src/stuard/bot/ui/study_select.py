"""Cascading degree → programme → year editor (ephemeral)."""

from __future__ import annotations

from typing import Any

import discord

from stuard import texts as T
from stuard.config import AppConfig
from stuard.domain.roleplan import StudySel, valid_study
from stuard.timeutil import now_ts


def study_summary(cfg: AppConfig, study: StudySel | None) -> str | None:
    if study is None or not valid_study(study, cfg):
        return None
    programme = cfg.study.programme(study.programme_id)
    degree = cfg.study.degrees[study.degree]
    assert programme is not None
    return f"{degree.label} · {programme.name} · {T.STUDY_YEAR.format(year=study.year)}"


class _FieldSelect(discord.ui.Select["StudyEditorView"]):
    def __init__(
        self, editor: StudyEditorView, field: str, placeholder: str, options: list[discord.SelectOption], row: int
    ):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1, row=row)
        self.editor = editor
        self.field = field

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.editor.on_select(interaction, self.field, self.values[0])


class StudyEditorView(discord.ui.View):
    def __init__(self, bot: Any, user_id: int, current: StudySel | None) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        valid = current if current is not None and valid_study(current, bot.cfg) else None
        self.degree: str | None = valid.degree if valid else None
        self.programme_id: str | None = valid.programme_id if valid else None
        self.year: int | None = valid.year if valid else None
        self._build()

    @property
    def selection(self) -> StudySel | None:
        if self.degree and self.programme_id and self.year:
            return StudySel(self.degree, self.programme_id, self.year)
        return None

    def summary(self) -> str:
        return study_summary(self.bot.cfg, self.selection) or T.STUDY_INCOMPLETE

    def _build(self) -> None:
        self.clear_items()
        study = self.bot.cfg.study
        degree_options = [
            discord.SelectOption(label=d.label, value=key, default=key == self.degree)
            for key, d in study.degrees.items()
        ]
        self.add_item(_FieldSelect(self, "degree", T.STUDY_PICK_DEGREE, degree_options, row=0))
        if self.degree:
            programme_options = [
                discord.SelectOption(
                    label=p.name[:100],
                    value=p.id,
                    description="English" if p.lang == "en" else None,
                    default=p.id == self.programme_id,
                )
                for p in study.programmes_for(self.degree)
            ]
            self.add_item(_FieldSelect(self, "programme", T.STUDY_PICK_PROGRAMME, programme_options, row=1))
            year_options = [
                discord.SelectOption(label=T.STUDY_YEAR.format(year=y), value=str(y), default=y == self.year)
                for y in range(1, study.degrees[self.degree].years + 1)
            ]
            self.add_item(_FieldSelect(self, "year", T.STUDY_PICK_YEAR, year_options, row=2))

        save = discord.ui.Button[StudyEditorView](
            label=T.STUDY_SAVE, style=discord.ButtonStyle.success, disabled=self.selection is None, row=3
        )
        save.callback = self._save  # type: ignore[method-assign]
        clear = discord.ui.Button[StudyEditorView](label=T.STUDY_CLEAR, style=discord.ButtonStyle.secondary, row=3)
        clear.callback = self._clear  # type: ignore[method-assign]
        self.add_item(save)
        self.add_item(clear)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def on_select(self, interaction: discord.Interaction, field: str, value: str) -> None:
        if field == "degree" and value != self.degree:
            self.degree, self.programme_id, self.year = value, None, None
        elif field == "programme":
            self.programme_id = value
        elif field == "year":
            self.year = int(value)
        self._build()
        await interaction.response.edit_message(content=T.STUDY_EDITOR.format(summary=self.summary()), view=self)

    async def _allowed(self) -> bool:
        member = await self.bot.repo.get_member(self.user_id)
        return member is not None and member.status in self.bot.cfg.study.allowed_statuses

    async def _save(self, interaction: discord.Interaction) -> None:
        selection = self.selection
        if not await self._allowed():
            await interaction.response.edit_message(content=T.STUDY_NOT_ALLOWED, view=None, embed=None)
            self.stop()
            return
        if selection is None or not valid_study(selection, self.bot.cfg):
            await interaction.response.edit_message(content=T.STUDY_EDITOR.format(summary=self.summary()), view=self)
            return
        await interaction.response.defer()
        await self.bot.repo.set_study(self.user_id, selection, now_ts())
        await self.bot.roles.sync_user(self.user_id, reason="STUard: výber štúdia")
        await interaction.edit_original_response(
            content=T.STUDY_SAVED.format(summary=self.summary()), view=None, embed=None
        )
        self.stop()

    async def _clear(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self.bot.repo.clear_study(self.user_id)
        await self.bot.roles.sync_user(self.user_id, reason="STUard: výber štúdia vymazaný")
        await interaction.edit_original_response(content=T.STUDY_CLEARED, view=None, embed=None)
        self.stop()


async def open_study_editor(interaction: discord.Interaction) -> None:
    bot: Any = interaction.client
    if interaction.guild is None:
        await interaction.response.send_message(T.NOT_IN_GUILD, ephemeral=True)
        return
    member = await bot.repo.get_member(interaction.user.id)
    if member is None or member.status not in bot.cfg.study.allowed_statuses:
        await interaction.response.send_message(T.STUDY_NOT_ALLOWED, ephemeral=True)
        return
    view = StudyEditorView(bot, interaction.user.id, await bot.repo.get_study(interaction.user.id))
    await interaction.response.send_message(T.STUDY_EDITOR.format(summary=view.summary()), view=view, ephemeral=True)
