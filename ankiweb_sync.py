"""Download a read-only copy of an AnkiWeb collection.

Uses the official `anki` Python package (the same sync code the Anki desktop
app uses). A brand-new, empty collection is created in a temp folder and a
*full download* is requested from AnkiWeb. Nothing is ever uploaded: the
download is forced with upload=False and media sync is disabled.
"""

from __future__ import annotations

import os
import tempfile


# SyncCollectionResponse.ChangesRequired values (anki/sync.proto)
NO_CHANGES, NORMAL_SYNC, FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD = range(5)


class AnkiWebError(RuntimeError):
    pass


def download_collection(username: str, password: str, workdir: str | None = None) -> str:
    """Return the path to a local .anki2 copy of the user's AnkiWeb collection."""
    from anki.collection import Collection  # imported lazily: heavy package

    workdir = workdir or tempfile.mkdtemp(prefix="anki-")
    path = os.path.join(workdir, "collection.anki2")
    col = Collection(path)
    try:
        try:
            auth = col.sync_login(username=username, password=password, endpoint=None)
        except Exception as exc:  # wrong login, network problems, ...
            raise AnkiWebError(f"inloggen bij AnkiWeb mislukt: {exc}") from exc

        try:
            out = col.sync_collection(auth=auth, sync_media=False)
        except Exception as exc:
            raise AnkiWebError(f"synchronisatie met AnkiWeb mislukt: {exc}") from exc

        if getattr(out, "new_endpoint", ""):
            auth.endpoint = out.new_endpoint

        required = int(out.required)
        if required in (FULL_DOWNLOAD, FULL_SYNC):
            col.close_for_full_sync()
            col.full_upload_or_download(
                auth=auth, server_usn=getattr(out, "server_media_usn", None), upload=False
            )
        elif required == FULL_UPLOAD:
            # AnkiWeb has nothing to give us: the account is empty.
            raise AnkiWebError(
                "het AnkiWeb-account lijkt leeg (nog nooit vanaf AnkiDroid gesynchroniseerd?)"
            )
        # NO_CHANGES / NORMAL_SYNC on a fresh collection means the server is empty too.
        else:
            raise AnkiWebError("het AnkiWeb-account lijkt leeg")
    finally:
        try:
            col.close(downgrade=False)
        except Exception:
            pass
    return path
