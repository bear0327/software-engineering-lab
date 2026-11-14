"""The packaged command uses the same isolated smoke check as source launch."""

from stay.__main__ import self_test


def test_self_test_releases_files_on_windows():
    result = self_test()
    assert result["ok"] and result["backup_checked"] and result["idempotency"]
