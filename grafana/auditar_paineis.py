#!/usr/bin/env python3
"""Auditoria estrutural dos dashboards financeiros no Grafana (API HTTP).

Substitui o fluxo contínuo do plugin Grafana Assistant quando ele não está
disponível (OSS sem app). Critérios: dashboards tag=financeiro, painéis com
query SQL, datasource `financeiro`, sem título vazio.

Uso:
  set GRAFANA_URL=https://jh-bi.duckdns.org
  set GRAFANA_TOKEN=<service-account-token>
  python grafana/auditar_paineis.py

Exit 0 se ok; 1 se achar problemas; 2 se config/API falhar.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

TAG = "financeiro"
DS_UID = "financeiro"
ESPERADOS = {
    "fin-visao-geral",
    "fin-dre",
    "fin-fluxo",
    "fin-faturamento",
    "fin-pagar",
    "fin-receber",
    "fin-gastos-receitas",
}


def _env(nome: str) -> str:
    valor = (os.environ.get(nome) or "").strip().rstrip("/")
    if not valor:
        raise SystemExit(f"Defina {nome}")
    return valor


def _get(url: str, token: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - URL de env controlado
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        corpo = erro.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"HTTP {erro.code} em {url}: {corpo}") from erro
    except urllib.error.URLError as erro:
        raise SystemExit(f"Falha de rede em {url}: {erro}") from erro


def _painel_tem_sql(painel: dict[str, Any]) -> bool:
    for alvo in painel.get("targets") or []:
        if (alvo.get("rawSql") or "").strip():
            return True
        if (alvo.get("query") or "").strip():
            return True
    for filho in painel.get("panels") or []:
        if _painel_tem_sql(filho):
            return True
    return False


def _datasource_ok(painel: dict[str, Any]) -> bool:
    ds = painel.get("datasource")
    if isinstance(ds, dict) and ds.get("uid") == DS_UID:
        return True
    if ds is None and not (painel.get("targets") or []):
        return True  # row / text sem query
    for alvo in painel.get("targets") or []:
        ads = alvo.get("datasource")
        if isinstance(ads, dict) and ads.get("uid") == DS_UID:
            return True
    for filho in painel.get("panels") or []:
        if not _datasource_ok(filho):
            return False
    # Painéis sem target (texto) ok; com target sem ds → problema
    if painel.get("targets"):
        return False
    return True


def auditar(base: str, token: str) -> list[str]:
    problemas: list[str] = []
    busca = _get(f"{base}/api/search?type=dash-db&tag={TAG}", token)
    uids = {item["uid"] for item in busca if item.get("uid")}
    faltando = ESPERADOS - uids
    if faltando:
        problemas.append(f"Dashboards esperados ausentes: {sorted(faltando)}")
    extras = uids - ESPERADOS
    if extras:
        # Informativo — não falha, só registra
        print(f"info: uids extras com tag {TAG}: {sorted(extras)}")

    for uid in sorted(uids & ESPERADOS):
        dash = _get(f"{base}/api/dashboards/uid/{uid}", token)
        painel_root = dash.get("dashboard") or {}
        titulo = painel_root.get("title") or uid
        paineis = painel_root.get("panels") or []
        if not paineis:
            problemas.append(f"{titulo} ({uid}): sem painéis")
            continue
        for painel in paineis:
            tipo = painel.get("type") or ""
            if tipo in {"row", "text", "news"}:
                continue
            pid = painel.get("id")
            ptitulo = (painel.get("title") or "").strip()
            if not ptitulo:
                problemas.append(f"{titulo} painel id={pid}: título vazio")
            if not _painel_tem_sql(painel):
                problemas.append(f"{titulo} / {ptitulo or pid}: sem SQL")
            if not _datasource_ok(painel):
                problemas.append(
                    f"{titulo} / {ptitulo or pid}: datasource ≠ uid={DS_UID}"
                )
    return problemas


def main() -> None:
    try:
        base = _env("GRAFANA_URL")
        token = _env("GRAFANA_TOKEN")
    except SystemExit as erro:
        print(erro, file=sys.stderr)
        raise SystemExit(2) from erro

    problemas = auditar(base, token)
    if problemas:
        print(f"FALHA: {len(problemas)} problema(s) na auditoria financeira:")
        for item in problemas:
            print(f"  - {item}")
        raise SystemExit(1)
    print(f"OK: {len(ESPERADOS)} dashboards financeiros estruturalmente íntegros.")


if __name__ == "__main__":
    main()
