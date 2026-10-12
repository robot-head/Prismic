"""End-to-end coverage for the item tag panel's "check this next"
promotion (`MainWindow._promote_tags`): mega-popular and correlated tags
actually reordering the real panel, through a real `MainWindow` and a
real (temp) collection -- not just the pure `tag_ranking.promote_ranked_tags`
unit tests, which never touch the DB, settings store, or panel wiring.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pytestqt.qtbot import QtBot

from prismic.application.tag_ranking_settings import TagRankingSettingsStore
from prismic.persistence.preferences import PreferencesStore
from prismic.ui.main_window import MainWindow
from tests.gui.helpers import checked_tag_names, open_and_wait

if TYPE_CHECKING:
    from prismic.application.session import PrismicSession

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


_MEDIA_COUNT = 40
"""Large enough that a tag on the 5-file co-occurrence floor (12.5% of
the collection) stays well under the default 15% mega-popular threshold
-- otherwise a tag correlated via the floor would *also* register as
mega-popular in its own right, making the two promotion tiers
indistinguishable in a test. A smaller, mega-popular-only tag (7 files,
17.5%) then clears that same threshold on purpose."""


@pytest.fixture
def collection_dir(tmp_path: Path) -> Path:
    root = tmp_path / "vacation"
    root.mkdir()
    for i in range(_MEDIA_COUNT):
        shutil.copyfile(FIXTURES_DIR / "supported_image.png", root / f"{i}.png")
    return root


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    store = TagRankingSettingsStore(PreferencesStore(tmp_path / "preferences.json"))
    win = MainWindow(tag_ranking_settings=store)
    qtbot.addWidget(win)
    return win


def _visible_tag_names(window: MainWindow) -> list[str]:
    model = window.item_tag_panel.model
    return [model.tag_at(row).name for row in range(model.rowCount())]


def _open_ranking_collection(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> tuple[PrismicSession, list[int]]:
    open_and_wait(qtbot, window, collection_dir, expected_count=_MEDIA_COUNT)
    session = window.session
    assert session is not None
    return session, sorted(session.state.result_set)


def test_mega_popular_and_correlated_tags_are_promoted_above_the_rest(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    session, media_ids = _open_ranking_collection(qtbot, window, collection_dir)
    assert len(media_ids) == _MEDIA_COUNT

    cat = session.tags.create("cat")
    kitten = session.tags.create("kitten")
    popular = session.tags.create("popular")
    session.tags.create("lonely")  # never mapped to anything -- the "rest" tier

    # cat and kitten co-occur on exactly 5 files (the floor) -- 100% of
    # cat's files there have kitten too, clearing the 80% correlation
    # threshold, while kitten's own 5/40 (12.5%) stays under the 15%
    # mega-popular threshold, so this promotion is attributable to
    # correlation alone.
    for media_id in media_ids[:5]:
        session.mappings.add(media_id, cat.id)
        session.mappings.add(media_id, kitten.id)
    # cat is also (alone) on a 6th file, so checking it there still shows
    # the promotion without kitten already being checked too.
    session.mappings.add(media_ids[5], cat.id)
    # popular is on 7 of 40 files (17.5%), clearing the default 15%
    # mega-popular threshold on its own, uncorrelated with cat.
    for media_id in media_ids[10:17]:
        session.mappings.add(media_id, popular.id)

    session.state.current_item = media_ids[5]
    session.state.selected_items = frozenset({media_ids[5]})
    window._refresh_all()

    assert checked_tag_names(window) == {"cat"}
    order = _visible_tag_names(window)
    assert order[0] == "cat"  # the checked block
    # mega-popular ("popular") ranks above correlated ("kitten"), which
    # ranks above the untouched "lonely" -- exactly the tier order the
    # product asked for.
    assert order[1:] == ["popular", "kitten", "lonely"]


def test_mega_popular_promotes_even_with_nothing_checked(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    session, media_ids = _open_ranking_collection(qtbot, window, collection_dir)

    popular = session.tags.create("popular")
    session.tags.create("lonely")
    for media_id in media_ids[:7]:  # 7 of 40 (17.5%), clears the 15% default
        session.mappings.add(media_id, popular.id)

    untouched_media = media_ids[-1]  # never mapped to anything
    session.state.current_item = untouched_media
    session.state.selected_items = frozenset({untouched_media})
    window._refresh_all()

    assert checked_tag_names(window) == set()
    assert _visible_tag_names(window)[0] == "popular"
