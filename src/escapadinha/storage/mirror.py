"""Local folders the full path reads, kept in the object store too (D25).

A GitHub Actions runner starts empty (D21). The Pixabay photo cache (`assets/photos/`) and the
rendered slides (`output/`) are therefore also stored under `photos/` and `output/`, with the
same relative paths. A file is uploaded when it is made (a photo fetched, a deal or guide
rendered) and downloaded the first time a run on another machine needs it.
`upload_missing` copies what a checkout made before D25. Without a store (no R2 keys) every
method only looks at the local folder.
"""

from __future__ import annotations

from pathlib import Path

from escapadinha.storage.objects import ObjectStore, check_key


class Mirror:
    def __init__(self, store: ObjectStore | None, root: Path, prefix: str):
        self.store, self.root, self.prefix = store, root, prefix

    def _key(self, rel: str) -> str:
        return check_key(f"{self.prefix}/{rel}")

    def put(self, path: Path, rel: str | None = None) -> None:
        """Upload one local file (`rel`: its path under the mirror, default: under root)."""
        if self.store is not None:
            rel = rel or path.relative_to(self.root).as_posix()
            self.store.put(self._key(rel), path.read_bytes())

    def put_tree(self, folder: Path) -> None:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                self.put(path)

    def keys(self) -> list[str]:
        """Relative paths of every stored file."""
        if self.store is None:
            return []
        return [key[len(self.prefix) + 1:] for key in self.store.list(f"{self.prefix}/")]

    def _download(self, key: str) -> Path:
        path = self.root / key[len(self.prefix) + 1:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.store.get(key))
        return path

    def file(self, rel: str) -> Path | None:
        """The local file, downloaded first when only the store has it; None when neither has."""
        path = self.root / rel
        if path.is_file():
            return path
        if self.store is None:
            return None
        try:
            return self._download(self._key(rel))
        except KeyError:
            return None

    def folder(self, rel: str) -> Path | None:
        """The local folder, downloaded first when only the store has it; None when neither has."""
        path = self.root / rel
        if path.is_dir():
            return path
        keys = self.store.list(self._key(rel) + "/") if self.store is not None else []
        for key in keys:
            self._download(key)
        return path if keys else None

    def upload_missing(self, files: dict[str, Path]) -> list[str]:
        """Upload the files (relative path -> local file) the store lacks. Returns their keys."""
        if self.store is None or not files:
            return []
        present = set(self.store.list(f"{self.prefix}/"))
        uploaded = []
        for rel, path in sorted(files.items()):
            key = self._key(rel)
            if key not in present:
                self.store.put(key, path.read_bytes())
                uploaded.append(key)
        return uploaded
