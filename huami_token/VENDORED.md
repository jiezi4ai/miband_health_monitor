# Vendored: huami-token

This directory is a **vendored, unmodified copy** of the `huami_token/` package
from the third-party [huami-token](https://codeberg.org/argrento/huami-token)
project by Kirill Snezhko. It is exempt from the project's own lint/size gates
and must stay identical to upstream (LF line endings, no local edits) so future
syncs are painless.

## Provenance

| Field | Value |
|---|---|
| Upstream repository | https://codeberg.org/argrento/huami-token |
| Vendored at commit | `1b32658519d1f35cd3c4345bb9ced3ba6881bb56` (master HEAD) |
| Upstream release | tag **v0.8.0** (2026-02-24) — also the newest release on PyPI as of 2026-11 |
| Verification | LF-normalized byte-identical to upstream `huami_token/` at that commit; upstream unit tests (`test_mi_crypto.py`, `test_xiaomi.py`, `test_encrypt.py`, 23 cases) pass against this copy |
| Local-only files | `LICENSE.md` and this `VENDORED.md` (added here, not present upstream) |

## License

MIT © 2020–2025 Kirill Snezhko — full text in [LICENSE.md](LICENSE.md).
Some upstream source files carry the same MIT header inline; the files without
per-file headers are covered by this directory-level license copy.

## Known upstream status (recorded 2026-11-19)

- **`--method amazfit` (Zepp/Amazfit account)**: last confirmed working in
  2026-04. Zepp changed its login flow twice during 2025, so expect recurring
  breakage; watch [issue #119](https://codeberg.org/argrento/huami-token/issues/119).
- **`--method xiaomi` (Xiaomi Mi Fitness account)**: broken since **2026-04**.
  Xiaomi enforces 2FA / risk control on scripted logins at
  `account.xiaomi.com/pass/serviceLoginAuth2`, so the flow dies with
  "Missing ssecurity or location in auth response" before a session key is
  issued. No upstream fix as of 2026-11. For Mi-Fitness-bound devices use the
  browser `app_token` route (`fetch_by_token.py`) or the Mi Fitness app logs
  instead — see `docs/guides/configuration.md` §3.

## How to sync a newer upstream version

A full upstream clone is kept locally (git-ignored) at `huami_token_upstream/`
for exactly this purpose. To pull in a new upstream release:

```bash
# 1. Refresh the local reference clone (or re-clone it if deleted)
git -C huami_token_upstream pull

# 2. Compare (hash diffs may be pure CRLF noise — verify content like this)
git -C huami_token_upstream diff --no-index -- \
    <repo-root>/huami_token/xiaomi.py  <repo-root>/huami_token_upstream/huami_token/xiaomi.py

# 3. Copy changed upstream files into huami_token/, keeping LF line endings

# 4. Re-run upstream tests against the vendored copy (from the repo root)
python -m pytest huami_token_upstream/tests/test_mi_crypto.py \
                 huami_token_upstream/tests/test_xiaomi.py \
                 huami_token_upstream/tests/test_encrypt.py

# 5. Update the commit hash / tag / status rows in this file
```

Do **not** turn this directory into a nested git repository or a submodule:
the parent repo tracks these files directly, and an embedded `.git` would
detach them from version control.
