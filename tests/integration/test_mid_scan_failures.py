"""A file disappearing mid-hash (a genuine race between the scanner listing
it and the hasher opening it) must not crash the scan or corrupt state for
the other files in it -- Phase 6's "mid-scan filesystem errors" case.
"""

from pathlib import Path

import prismic.indexing.reconciler as reconciler_module
from prismic.indexing.reconciler import Reconciler, run_reconciliation
from prismic.persistence.repositories.media_repository import MediaRepository
from tests._reconciliation_test_context import ReconciliationTestContext


def test_a_file_deleted_between_scan_and_hash_does_not_crash_or_corrupt_other_files(
    reconciliation_test_context: ReconciliationTestContext,
) -> None:
    context = reconciliation_test_context
    doomed = context.root / "doomed.jpg"
    safe = context.root / "safe.jpg"
    doomed.write_bytes(b"about to vanish")
    safe.write_bytes(b"stays put")

    real_hash_file = reconciler_module.hash_file

    def _hash_file_racing_a_deletion(path: Path) -> str:
        if path == doomed:
            path.unlink()  # simulates the file disappearing after the scan listed it
        return real_hash_file(path)

    context.monkeypatch.setattr(reconciler_module, "hash_file", _hash_file_racing_a_deletion)

    reconciler = Reconciler()
    generation = reconciler.begin_scan()
    result = run_reconciliation(reconciler, context.collection, generation, context.connection)

    assert result.applied
    media = MediaRepository(context.connection).list_all()
    assert [m.relative_path for m in media] == ["safe.jpg"]
