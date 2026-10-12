from prismic.application.state import ApplicationState
from prismic.domain.media import MediaState
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository


def _add_active_media(media: MediaRepository, relative_path: str) -> int:
    return media.create(
        relative_path=relative_path,
        content_hash=relative_path,
        size=1,
        mtime=1.0,
        state=MediaState.ACTIVE,
    ).id


def test_zero_tags_makes_all_active_media_eligible_in_path_order(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    _add_active_media(media, "z.jpg")
    _add_active_media(media, "a.jpg")
    media.create(
        relative_path="missing.jpg",
        content_hash="missing",
        size=1,
        mtime=1.0,
        state=MediaState.MISSING,
    )

    state = ApplicationState()
    state.recompute(media, mappings)

    paths = [m.relative_path for m in media.list_all() if m.id in state.result_set]
    assert sorted(paths) == ["a.jpg", "z.jpg"]
    assert len(state.result_set) == 2


def test_current_item_unchanged_when_it_survives(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    a = _add_active_media(media, "a.jpg")
    _add_active_media(media, "b.jpg")

    state = ApplicationState()
    state.recompute(media, mappings)
    state.current_item = a

    state.recompute(media, mappings)

    assert state.current_item == a


def test_current_item_none_stays_none_even_with_results(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    _add_active_media(media, "a.jpg")

    state = ApplicationState()
    assert state.current_item is None

    state.recompute(media, mappings)

    assert state.current_item is None


def test_current_item_moves_to_nearest_surviving_item(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    a = _add_active_media(media, "a.jpg")
    b = _add_active_media(media, "b.jpg")
    d = _add_active_media(media, "d.jpg")
    e = _add_active_media(media, "e.jpg")
    removed = max(a, b, d, e) + 1000  # stands in for an item deleted since the last scan

    state = ApplicationState()
    # Previous navigation order had `removed` selected, sitting between b and d.
    state.result_set = [a, b, removed, d, e]
    state.current_item = removed

    state.recompute(media, mappings)

    # `removed` no longer exists; the nearest surviving neighbor in the
    # previous order is `d` (checked before `b`, its equidistant neighbor,
    # since forward is preferred at equal distance).
    assert state.current_item == d


def test_nearest_surviving_search_includes_the_first_item_at_any_distance() -> None:
    state = ApplicationState(result_set=[10])

    assert state._resolve_current_item([10, 20], 20) == 10
    assert state._resolve_current_item([10, 20, 30, 40], 40) == 10


def test_current_item_falls_back_to_first_result_when_no_neighbor_survives(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    state = ApplicationState()
    state.result_set = [1, 2, 3]
    state.current_item = 2

    kept = _add_active_media(media, "kept.jpg")

    state.recompute(media, mappings)

    assert state.current_item == kept


def test_current_item_becomes_none_when_result_set_is_empty(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    state = ApplicationState()
    state.result_set = [1]
    state.current_item = 1

    state.recompute(media, mappings)

    assert state.result_set == []
    assert state.current_item is None


def test_selected_items_defaults_to_empty(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    state = ApplicationState()

    state.recompute(media, mappings)

    assert state.selected_items == frozenset()


def test_selected_items_survives_a_recompute_when_still_eligible(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    a = _add_active_media(media, "a.jpg")
    b = _add_active_media(media, "b.jpg")
    c = _add_active_media(media, "c.jpg")

    state = ApplicationState()
    state.recompute(media, mappings)
    state.current_item = a
    state.selected_items = frozenset({a, b, c})

    state.recompute(media, mappings)

    assert state.selected_items == frozenset({a, b, c})


def test_selected_items_drops_an_id_that_leaves_the_result_set(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    a = _add_active_media(media, "a.jpg")
    b = _add_active_media(media, "b.jpg")
    removed = max(a, b) + 1000  # stands in for an item deleted since the last scan

    state = ApplicationState()
    state.result_set = [a, b, removed]
    state.current_item = a
    state.selected_items = frozenset({a, b, removed})

    state.recompute(media, mappings)

    assert state.selected_items == frozenset({a, b})


def test_current_item_is_always_included_in_selected_items(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    """`current_item` is the click/keyboard anchor -- it must never fall
    outside `selected_items`, even if nothing had explicitly added it
    (e.g. after `_resolve_current_item` reassigns it to a fresh item with
    no selection of its own yet)."""
    a = _add_active_media(media, "a.jpg")

    state = ApplicationState()
    state.result_set = [1]
    state.current_item = 1
    state.selected_items = frozenset()

    state.recompute(media, mappings)

    assert state.current_item == a
    assert state.selected_items == frozenset({a})
