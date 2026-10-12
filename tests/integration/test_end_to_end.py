"""End-to-end flows exercising multiple layers together as one session,
per Phase 6 -- the acceptance gates in overview section 13 checked
end-to-end rather than per-component.
"""

from pathlib import Path

from prismic.application.commands import (
    FilterDeselectCommand,
    FilterSelectCommand,
    MappingAddCommand,
    MappingRemoveCommand,
    TagCreateCommand,
)
from prismic.application.session import PrismicSession
from prismic.domain.media import MediaState


def _collection(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "vacation"
    root.mkdir()
    for name, content in files.items():
        (root / name).write_bytes(content)
    return root


def _await_initial_scan(session: PrismicSession) -> None:
    session.initial_reconciliation.result(timeout=10)


def test_fresh_directory_scans_in_the_background_and_the_session_is_usable_immediately(
    tmp_path: Path,
) -> None:
    """Opening returns a working session before the scan finishes -- the
    constructor itself must not block on background work."""
    root = _collection(tmp_path, {"a.jpg": b"content-a", "b.jpg": b"content-b"})

    with PrismicSession.open(root) as session:
        # The session is immediately queryable/commandable, even before the
        # background scan has necessarily finished.
        session.execute(TagCreateCommand(name="vacation"))
        assert [t.name for t in session.tags.list_all()] == ["vacation"]

        _await_initial_scan(session)
        session.refresh_state()

        assert {m.relative_path for m in session.media.list_all()} == {"a.jpg", "b.jpg"}
        assert len(session.state.result_set) == 2


def test_reopening_a_collection_matches_persisted_state_with_no_duplicate_identities(
    tmp_path: Path,
) -> None:
    root = _collection(tmp_path, {"a.jpg": b"content-a"})

    with PrismicSession.open(root) as session:
        _await_initial_scan(session)
        session.execute(TagCreateCommand(name="vacation"))
        tag = session.tags.list_all()[0]
        media_id = session.media.list_all()[0].id
        session.execute(MappingAddCommand(media_id=media_id, tag_id=tag.id))

    with PrismicSession.open(root) as reopened:
        _await_initial_scan(reopened)

        # Same media identity, same tag, same mapping -- not recreated.
        media_list = reopened.media.list_all()
        assert len(media_list) == 1
        assert media_list[0].id == media_id
        assert media_list[0].state == MediaState.ACTIVE

        tags = reopened.tags.list_all()
        assert len(tags) == 1
        assert tags[0].id == tag.id
        assert [t.id for t in reopened.mappings.tags_for_media(media_id)] == [tag.id]


def test_full_tag_filter_navigate_edit_undo_loop_in_one_continuous_session(
    tmp_path: Path,
) -> None:
    root = _collection(
        tmp_path,
        {"a.jpg": b"content-a", "b.jpg": b"content-b", "c.jpg": b"content-c"},
    )

    with PrismicSession.open(root) as session:
        _await_initial_scan(session)
        session.refresh_state()
        a, b, c = (m.id for m in session.media.list_all())

        session.execute(TagCreateCommand(name="beach"))
        tag = session.tags.list_all()[0]

        session.execute(MappingAddCommand(media_id=a, tag_id=tag.id))
        session.execute(MappingAddCommand(media_id=b, tag_id=tag.id))

        session.execute(FilterSelectCommand(tag_id=tag.id))
        # `a`/`b` were bound from `list_all()`'s relative-path order, which
        # is the same ordering `result_set` uses -- so this is exact, not
        # just a membership check.
        assert session.state.result_set == [a, b]

        # Navigate: current item stays valid as the filtered set changes.
        session.state.current_item = a
        session.execute(MappingRemoveCommand(media_id=a, tag_id=tag.id))
        # `a` left the result set; the dispatcher's post-command recompute
        # must have already repaired current_item per the Phase 3 invariant.
        assert (
            session.state.current_item is None
            or session.state.current_item in session.state.result_set
        )
        assert a not in session.state.result_set

        session.undo()  # restores the a<->tag mapping
        assert session.state.result_set == [a, b]

        session.execute(FilterDeselectCommand(tag_id=tag.id))
        assert set(session.state.result_set) == {a, b, c}


def test_opening_with_a_direct_prismic_file_path_opens_to_its_containing_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vacation"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"content")

    with PrismicSession.open(root) as first:
        database_path = first.collection.database_path
        first.initial_reconciliation.result(timeout=10)

    # The double-click launch case: argv hands in the .prismic file itself.
    with PrismicSession.open(database_path) as reopened:
        reopened.initial_reconciliation.result(timeout=10)
        assert reopened.collection.root == root
        assert len(reopened.media.list_all()) == 1
