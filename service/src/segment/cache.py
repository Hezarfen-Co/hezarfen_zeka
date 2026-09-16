"""Yanit onbellegi: (soru + istem surumu + model) -> yanit.

Neden: tekrar kosular BEDAVA olsun. 3.833 madde x birden fazla varyant x
kararlilik tekrarlari, onbelleksiz her deneyde bastan ucretlenir.

Anahtar `provider.cache_key()` ile uretilir ve model, sistem istemi, TAM istem
metni (istem surumu ve sorunun kendisi bunun icindedir), sicaklik ve tekrar
indeksini kapsar. Bulgu 5 geregi istem surumu anahtarin ayrilmaz parcasidir:
istem degisince onbellek DOGAL OLARAK gecersizlesir.

Bicim: dizin altinda `<ilk2>/<hash>.json`. Tek dosyalik dev JSON yerine
parca dosyalar — es zamanli yazimda kayip olmaz, kismi kosu kurtarilabilir.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class ResponseCache:
    """Dosya tabanli, es zamanli yazima dayanikli onbellek."""

    def __init__(self, root: Path | str, *, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            if key in self._mem:
                self.hits += 1
                return self._mem[key]
        p = self._path(key)
        if not p.exists():
            with self._lock:
                self.misses += 1
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Bozuk onbellek girdisi sessizce DOGRU sayilmaz: yok kabul edilir.
            with self._lock:
                self.misses += 1
            return None
        with self._lock:
            self._mem[key] = data
            self.hits += 1
        return data

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._mem[key] = value
            self.writes += 1
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomik yazim: gecici dosya + rename (yarim dosya kalmaz).
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(value, fh, ensure_ascii=False)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self.hits, "misses": self.misses,
                    "writes": self.writes, "mem": len(self._mem)}

    def clear(self) -> int:
        """Onbellegi siler; silinen dosya sayisini dondurur."""
        n = 0
        if self.root.exists():
            for p in self.root.rglob("*.json"):
                p.unlink()
                n += 1
        with self._lock:
            self._mem.clear()
        return n


class NullCache(ResponseCache):
    """Onbelleksiz kosu icin (testlerde yalitim)."""

    def __init__(self):
        super().__init__(Path("."), enabled=False)
