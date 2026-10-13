"""Contadores operacionais leves (limites de taxa, erros) compartilhados pelo processo."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Metricas:
    bling_429: int = 0
    bling_erros_http: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def registrar_429(self) -> None:
        with self._lock:
            self.bling_429 += 1

    def registrar_erro_http(self) -> None:
        with self._lock:
            self.bling_erros_http += 1

    def instantaneo(self) -> dict[str, int]:
        with self._lock:
            return {
                "bling_429": self.bling_429,
                "bling_erros_http": self.bling_erros_http,
            }


metricas = Metricas()
