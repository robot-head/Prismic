"""Tag creation, rename, and deletion commands."""

from __future__ import annotations

from dataclasses import dataclass, field

from prismic.application.commands import _support


@dataclass
class TagCreateCommand(_support.Command):
    name: str
    _created_tag_id: int | None = field(default=None, init=False, repr=False)

    def execute(self, context: _support.CommandContext) -> None:
        tag = context.tags.create(self.name)
        self._created_tag_id = tag.id

    def undo(self, context: _support.CommandContext) -> None:
        assert self._created_tag_id is not None
        context.tags.delete(self._created_tag_id)


@dataclass
class TagRenameCommand(_support.Command):
    tag_id: int
    new_name: str
    _previous_name: str | None = field(default=None, init=False, repr=False)

    def execute(self, context: _support.CommandContext) -> None:
        tag = _support.require_tag(context, self.tag_id)
        self._previous_name = tag.name
        context.tags.rename(self.tag_id, self.new_name)

    def undo(self, context: _support.CommandContext) -> None:
        assert self._previous_name is not None
        context.tags.rename(self.tag_id, self._previous_name)


@dataclass
class TagDeleteCommand(_support.Command):
    """Deletes a tag and every mapping referencing it.

    Undo recreates the tag and its mappings and restores its filter
    membership — necessarily as a *new* tag id, since ids aren't reused.
    Tag ids are immutable while a tag exists, not across a delete/undo
    round trip; nothing outside this command instance is expected to have
    held onto the old id once it's gone, since undo/redo stack discipline
    means any later command referencing this tag would already have been
    undone first.
    """

    tag_id: int
    _deleted_tag_name: str | None = field(default=None, init=False, repr=False)
    _mapped_media_ids: list[int] = field(default_factory=list, init=False, repr=False)
    _was_selected: bool = field(default=False, init=False, repr=False)

    def execute(self, context: _support.CommandContext) -> None:
        tag = _support.require_tag(context, self.tag_id)
        self._deleted_tag_name = tag.name
        self._mapped_media_ids = context.mappings.media_ids_for_tags([self.tag_id])
        self._was_selected = self.tag_id in context.state.selected_tag_ids

        context.tags.delete(self.tag_id)
        if self._was_selected:
            context.state.selected_tag_ids.remove(self.tag_id)

    def undo(self, context: _support.CommandContext) -> None:
        assert self._deleted_tag_name is not None
        recreated = context.tags.create(self._deleted_tag_name)
        for media_id in self._mapped_media_ids:
            context.mappings.add(media_id, recreated.id)
        if self._was_selected:
            context.state.selected_tag_ids.append(recreated.id)
