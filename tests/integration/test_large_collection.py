"""A large-collection stress case, per Phase 6's "responsiveness under
load" checklist.

2,000 files is the chosen "realistic stress case" number: large enough to
meaningfully exercise the scan/hash/reconcile pipeline and the query
layer's sort step at a scale well beyond casual manual testing. That
scale makes both tests here multi-second, so the module is marked
``slow`` -- see tools/run_tests.py for how/when slow tests run.
"""

import time
from pathlib import Path

import pytest

from prismic.application.queries.media_query import eligible_media
from prismic.application.session import PrismicSession

pytestmark = pytest.mark.slow

_FILE_COUNT = 2000


def _large_collection(tmp_path: Path) -> Path:
    root = tmp_path / "big_collection"
    root.mkdir()
    for index in range(_FILE_COUNT):
        (root / f"photo_{index:05d}.jpg").write_bytes(f"content-{index}".encode())
    return root


def test_a_large_collection_opens_without_blocking_and_scans_correctly(
    tmp_path: Path,
) -> None:
    root = _large_collection(tmp_path)

    start = time.perf_counter()
    session = PrismicSession.open(root)
    open_elapsed = time.perf_counter() - start
    try:
        # Opening (and therefore returning control to the GUI thread) must
        # not wait for the scan of 2,000 files -- that's the whole point of
        # running it on a background worker.
        assert open_elapsed < 2.0

        session.initial_reconciliation.result(timeout=30)
        session.refresh_state()

        media = session.media.list_all()
        assert len(media) == _FILE_COUNT
        assert len(session.state.result_set) == _FILE_COUNT

        # The query layer's sort still produces correct, deterministic
        # ordering at this scale.
        ordered = eligible_media(session.media, session.mappings, [])
        assert [m.relative_path for m in ordered] == sorted(m.relative_path for m in ordered)
    finally:
        session.close()


def test_a_large_collection_rescans_quickly_when_nothing_changed(tmp_path: Path) -> None:
    """An unchanged-file rescan is a no-op per file (Phase 2) -- confirms
    that stays true at scale rather than degrading badly."""
    root = _large_collection(tmp_path)

    with PrismicSession.open(root) as session:
        session.initial_reconciliation.result(timeout=30)

        start = time.perf_counter()
        result = session.rescan().result(timeout=30)
        rescan_elapsed = time.perf_counter() - start

        assert result.applied
        assert result.unchanged_count == _FILE_COUNT
        assert result.new_count == 0
        assert rescan_elapsed < 15.0  # generous; catches gross regressions only
