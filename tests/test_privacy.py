"""tools/check_privacy.py must reject real identifiers and personal paths."""

from __future__ import annotations

import pytest

from tools import check_privacy

# Built at runtime so this test file stays clean for the scanner itself: the
# literal patterns only exist in the generated fixture files, never in source.
REAL_MAC = ":".join(["DE", "AD", "BE", "EF", "00", "01"])
FAKE_KEY = "f" * 32
PRIVATE_KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"
PERSONAL_PATH = "/" + "home/" + "someone/project"


@pytest.fixture()
def scanner_root(tmp_path, monkeypatch):
    """Point the scanner at an isolated tree instead of the checkout."""
    monkeypatch.setattr(check_privacy, "ROOT", tmp_path)
    return tmp_path


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_placeholder_identity_and_test_vectors_are_allowed(scanner_root):
    _write(
        scanner_root,
        "module.py",
        'MAC = "C0:FF:EE:C0:FF:EE"\n'
        'KEY = "0123456789abcdef0123456789abcdef"\n',
    )
    assert check_privacy.scan_file("module.py") == []


def test_real_identifiers_are_rejected(scanner_root):
    _write(scanner_root, "leak.py", f'MAC = "{REAL_MAC}"\nKEY = "{FAKE_KEY}"\n')
    rules = {rule for _, rule, _ in check_privacy.scan_file("leak.py")}
    assert {"real-mac-address", "possible-auth-key"} <= rules


def test_auth_key_rule_skips_test_files(scanner_root):
    _write(scanner_root, "tests/test_vectors.py", f'KEY = "{FAKE_KEY}"\n')
    assert check_privacy.scan_file("tests/test_vectors.py") == []


def test_private_key_block_and_personal_path_are_rejected(scanner_root):
    _write(scanner_root, "notes.txt", f"{PRIVATE_KEY_HEADER}\n{PERSONAL_PATH}\n")
    rules = {rule for _, rule, _ in check_privacy.scan_file("notes.txt")}
    assert {"private-key-block", "personal-home-path"} <= rules


def test_binary_suffixes_are_not_scanned(scanner_root):
    _write(scanner_root, "capture.png", f'MAC = "{REAL_MAC}"\n')
    assert check_privacy.scan_file("capture.png") == []


def test_data_directory_and_env_are_forbidden(scanner_root):
    _write(scanner_root, "data/mi_band.db", "")
    _write(scanner_root, ".env", "MIBAND_DEVICE_ID=C0:FF:EE:C0:FF:EE\n")
    assert check_privacy.scan_file("data/mi_band.db") == [
        (0, "forbidden-tracked-file", "data/mi_band.db"),
    ]
    assert check_privacy.scan_file(".env") == [(0, "forbidden-tracked-file", ".env")]


def test_main_returns_nonzero_only_when_findings_exist(scanner_root, monkeypatch, capsys):
    _write(scanner_root, "clean.py", "VALUE = 1\n")
    monkeypatch.setattr(check_privacy, "git_files", lambda: ["clean.py"])
    assert check_privacy.main([]) == 0
    assert "OK: no real MAC" in capsys.readouterr().out

    _write(scanner_root, "leak.py", f'MAC = "{REAL_MAC}"\n')
    monkeypatch.setattr(check_privacy, "git_files", lambda: ["leak.py"])
    assert check_privacy.main([]) == 1
    out = capsys.readouterr().out
    assert "real-mac-address" in out
    assert "leak.py" in out


def test_windows_env_acl_parser_flags_other_users():
    """icacls listings that grant Users/Authenticated Users must be flagged."""
    loose = (
        ".env BUILTIN\\Administrators:(I)(F)\n"
        "     NT AUTHORITY\\SYSTEM:(I)(F)\n"
        "     BUILTIN\\Users:(I)(RX)\n"
        "     NT AUTHORITY\\Authenticated Users:(I)(M)\n"
        "\n"
        "Successfully processed 1 files; Failed processing 0 files\n"
    )
    assert set(check_privacy._windows_env_offenders(loose)) == {
        "BUILTIN\\Users",
        "NT AUTHORITY\\Authenticated Users",
    }


def test_windows_env_acl_parser_allows_owner_only_listing():
    """A listing with only the current user (plus SYSTEM/Admin) stays clean."""
    tight = (
        ".env WHITENIGHT\\alice:(F)\n"
        "     NT AUTHORITY\\SYSTEM:(F)\n"
        "     BUILTIN\\Administrators:(F)\n"
    )
    assert check_privacy._windows_env_offenders(tight) == []


def test_windows_env_acl_parser_ignores_deny_aces():
    """Deny ACEs restrict instead of grant access, so they are never offenders."""
    listing = ".env WHITENIGHT\\alice:(F)\n     Everyone:(DENY)(DC)\n"
    assert check_privacy._windows_env_offenders(listing) == []


def test_env_permission_warning_uses_posix_bits(monkeypatch, tmp_path):
    """The non-Windows branch keeps the historical chmod-600 warning."""
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    env.chmod(0o666)
    monkeypatch.setattr(check_privacy.os, "name", "posix")
    warning = check_privacy._env_permission_warning(env)
    assert warning is not None and "chmod 600" in warning


def test_env_permission_warning_windows_branch_reads_real_acl(monkeypatch, tmp_path):
    """On Windows the warning must come from the icacls listing, not stat bits."""
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    class _IcaclsResult:
        stdout = b".env BUILTIN\\Users:(I)(RX)\n"

    monkeypatch.setattr(check_privacy.os, "name", "nt")
    monkeypatch.setattr(check_privacy.subprocess, "run", lambda *a, **k: _IcaclsResult())
    warning = check_privacy._env_permission_warning(env)
    assert warning is not None
    assert "icacls .env" in warning
    assert "BUILTIN\\Users" in warning

    class _IcaclsClean:
        stdout = b".env WHITENIGHT\\alice:(F)\n"

    monkeypatch.setattr(
        check_privacy.subprocess, "run", lambda *a, **k: _IcaclsClean()
    )
    assert check_privacy._env_permission_warning(env) is None


def test_env_permission_warning_is_silent_without_env_file(tmp_path):
    assert check_privacy._env_permission_warning(tmp_path / ".env") is None
