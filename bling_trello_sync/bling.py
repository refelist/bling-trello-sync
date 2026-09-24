import base64
import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .storage import Storage, TokenBling


class BlingAuthError(RuntimeError):
    pass


def validar_assinatura(corpo: bytes, assinatura: str | None, client_secret: str) -> bool:
    """Valida o header X-Bling-Signature-256 (HMAC-SHA256 do payload com o client secret)."""
    if not assinatura:
        return False
    esperado = hmac.new(client_secret.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    recebido = assinatura.removeprefix("sha256=").strip()
    return hmac.compare_digest(esperado, recebido)


class BlingClient:
    def __init__(self, settings: Settings, storage: Storage, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self._client = client or httpx.Client(timeout=30)

    def url_de_autorizacao(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.bling_client_id,
            "state": state,
        }
        return f"{self.settings.bling_auth_base}/oauth/authorize?{urlencode(params)}"

    def _header_basic(self) -> str:
        credenciais = f"{self.settings.bling_client_id}:{self.settings.bling_client_secret}"
        return "Basic " + base64.b64encode(credenciais.encode("utf-8")).decode("ascii")

    def _requisitar_token(self, dados: dict[str, str]) -> TokenBling:
        resposta = self._client.post(
            f"{self.settings.bling_auth_base}/oauth/token",
            data=dados,
            headers={
                "Authorization": self._header_basic(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        if resposta.status_code >= 400:
            raise BlingAuthError(f"Falha ao obter token no Bling ({resposta.status_code}): {resposta.text}")
        corpo = resposta.json()
        token = TokenBling(
            access_token=corpo["access_token"],
            refresh_token=corpo["refresh_token"],
            expira_em=time.time() + float(corpo.get("expires_in", 21600)),
        )
        self.storage.salvar_token(token)
        return token

    def trocar_codigo_por_token(self, code: str) -> TokenBling:
        return self._requisitar_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.bling_redirect_uri,
            }
        )

    def renovar_token(self, refresh_token: str) -> TokenBling:
        return self._requisitar_token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _access_token(self) -> str:
        token = self.storage.obter_token()
        if token is None:
            raise BlingAuthError(
                "Nenhum token do Bling armazenado. Conclua o fluxo em /oauth/bling/autorizar."
            )
        if token.expirado:
            token = self.renovar_token(token.refresh_token)
        return token.access_token

    def _get(self, caminho: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.settings.bling_api_base}{caminho}"
        headers = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json"}
        resposta = self._client.get(url, params=params, headers=headers)
        if resposta.status_code == 401:
            token = self.storage.obter_token()
            if token is not None:
                novo = self.renovar_token(token.refresh_token)
                headers["Authorization"] = f"Bearer {novo.access_token}"
                resposta = self._client.get(url, params=params, headers=headers)
        resposta.raise_for_status()
        return resposta.json()

    def obter_pedido_venda(self, pedido_id: int) -> dict[str, Any]:
        return self._get(f"/pedidos/vendas/{pedido_id}")["data"]

    def obter_situacao(self, situacao_id: int) -> dict[str, Any]:
        return self._get(f"/situacoes/{situacao_id}")["data"]

    def listar_modulos_situacoes(self) -> list[dict[str, Any]]:
        return self._get("/situacoes/modulos")["data"]

    def listar_situacoes_do_modulo(self, id_modulo: int) -> list[dict[str, Any]]:
        return self._get(f"/situacoes/modulos/{id_modulo}")["data"]

    def listar_pedidos_vendas(
        self,
        pagina: int = 1,
        limite: int = 100,
        data_inicial: str | None = None,
        data_final: str | None = None,
        data_alteracao_inicial: str | None = None,
        data_alteracao_final: str | None = None,
        ids_situacoes: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final
        if data_alteracao_inicial:
            params["dataAlteracaoInicial"] = data_alteracao_inicial
        if data_alteracao_final:
            params["dataAlteracaoFinal"] = data_alteracao_final
        if ids_situacoes:
            params["idsSituacoes[]"] = ids_situacoes
        return self._get("/pedidos/vendas", params=params)["data"]
