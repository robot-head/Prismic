"""Media/tag mapping creation and deletion commands."""

from __future__ import annotations

from dataclasses import dataclass, field

from prismic.application.commands import _support
from prismic.application.errors import UnknownMappingError
from prismic.persistence.errors import UnknownMediaError


@dataclass
class _SingleMappingCommand(_support.Command):
    media_id: int
    tag_id: int

    def _set_mapping(self, context: _support.CommandContext, *, adding: bool) -> None:
        operation = context.mappings.add if adding else context.mappings.remove
        operation(self.media_id, self.tag_id)


@dataclass
class MappingAddCommand(_SingleMappingCommand):
    def execute(self, context: _support.CommandContext) -> None:
        if context.media.get(self.media_id) is None:
            raise UnknownMediaError(self.media_id)
        _support.require_tag(context, self.tag_id)
        self._set_mapping(context, adding=True)

    def undo(self, context: _support.CommandContext) -> None:
        self._set_mapping(context, adding=False)


@dataclass
class MappingRemoveCommand(_SingleMappingCommand):
    def execute(self, context: _support.CommandContext) -> None:
        existing_tag_ids = {tag.id for tag in context.mappings.tags_for_media(self.media_id)}
        if self.tag_id not in existing_tag_ids:
            raise UnknownMappingError(self.media_id, self.tag_id)
        self._set_mapping(context, adding=False)

    def undo(self, context: _support.CommandContext) -> None:
        self._set_mapping(context, adding=True)


@dataclass
class MappingSetForManyCommand(_support.Command):
    """Adds or removes `tag_id` across every id in `media_ids`, each
    according to its *own* current state -- the multi-select tag-toggle
    case: "check this tag" must add it only to whichever selected files
    don't already have it (not touch the ones that do), and "uncheck"
    is the mirror. One command, one undo step, regardless of how many of
    `media_ids` actually changed -- undo only reverts the ones this
    `execute()` actually touched, not every id in `media_ids`, since a
    file that already had the tag (and so was left alone going in) must
    stay untouched coming back out too.
    """

    media_ids: frozenset[int]
    tag_id: int
    adding: bool
    _changed_media_ids: list[int] = field(default_factory=list, init=False, repr=False)

    def execute(self, context: _support.CommandContext) -> None:
        _support.require_tag(context, self.tag_id)
        self._changed_media_ids = []
        for media_id in self.media_ids:
            has_it = self.tag_id in {t.id for t in context.mappings.tags_for_media(media_id)}
            if self.adding and not has_it:
                context.mappings.add(media_id, self.tag_id)
                self._changed_media_ids.append(media_id)
            elif not self.adding and has_it:
                context.mappings.remove(media_id, self.tag_id)
                self._changed_media_ids.append(media_id)

    def undo(self, context: _support.CommandContext) -> None:
        for media_id in self._changed_media_ids:
            if self.adding:
                context.mappings.remove(media_id, self.tag_id)
            else:
                context.mappings.add(media_id, self.tag_id)
