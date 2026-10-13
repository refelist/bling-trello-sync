"""Contadores operacionais leves (limites de taxa, erros) compartilhados pelo processo."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Metricas:
    bling_429: int = 0
    bling_erros_http: int = 0
    financeiro_coletas_ok: int = 0
    financeiro_coletas_erro: int = 0
    financeiro_ultima_empresa: str = ""
    financeiro_ultima_ok: bool = False
    financeiro_ultima_erros: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def registrar_429(self) -> None:
        with self._lock:
            self.bling_429 += 1

    def registrar_erro_http(self) -> None:
        with self._lock:
            self.bling_erros_http += 1

    def registrar_coleta_financeira(self, *, empresa: str, ok: bool, erros: int) -> None:
        with self._lock:
            if ok:
                self.financeiro_coletas_ok += 1
            else:
                self.financeiro_coletas_erro += 1
            self.financeiro_ultima_empresa = empresa
            self.financeiro_ultima_ok = ok
            self.financeiro_ultima_erros = erros

    def instantaneo(self) -> dict[str, int | str | bool]:
        with self._lock:
            return {
                "bling_429": self.bling_429,
                "bling_erros_http": self.bling_erros_http,
                "financeiro_coletas_ok": self.financeiro_coletas_ok,
                "financeiro_coletas_erro": self.financeiro_coletas_erro,
                "financeiro_ultima_empresa": self.financeiro_ultima_empresa,
                "financeiro_ultima_ok": self.financeiro_ultima_ok,
                "financeiro_ultima_erros": self.financeiro_ultima_erros,
            }


metricas = Metricas()
