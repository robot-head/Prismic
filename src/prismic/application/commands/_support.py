"""Shared command contracts and context validation helpers."""

from prismic.application.commands.base import Command, CommandContext
from prismic.domain.tag import Tag
from prismic.persistence.errors import UnknownTagError

__all__ = ["Command", "CommandContext", "require_tag"]


def require_tag(context: CommandContext, tag_id: int) -> Tag:
    tag = context.tags.get(tag_id)
    if tag is None:
        raise UnknownTagError(tag_id)
    return tag
