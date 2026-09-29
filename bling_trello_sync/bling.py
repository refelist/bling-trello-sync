import base64
import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .storage import Storage, TokenBling

TENTATIVAS_LIMITE_TAXA = 5
ESPERA_INICIAL_SEGUNDOS = 2.0


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

    def _espera_do_limite(self, resposta: httpx.Response, tentativa: int) -> float:
        cabecalho = resposta.headers.get("Retry-After")
        if cabecalho:
            try:
                return float(cabecalho)
            except ValueError:
                pass
        return ESPERA_INICIAL_SEGUNDOS * (2**tentativa)

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
        for tentativa in range(TENTATIVAS_LIMITE_TAXA):
            if resposta.status_code != 429:
                break
            time.sleep(self._espera_do_limite(resposta, tentativa))
            resposta = self._client.get(url, params=params, headers=headers)
        resposta.raise_for_status()
        return resposta.json()

    def obter_pedido_venda(self, pedido_id: int) -> dict[str, Any]:
        return self._get(f"/pedidos/vendas/{pedido_id}")["data"]

    def obter_nota_fiscal(self, nota_fiscal_id: int) -> dict[str, Any]:
        return self._get(f"/nfe/{nota_fiscal_id}")["data"]

    def obter_pedido_compra(self, pedido_id: int) -> dict[str, Any]:
        return self._get(f"/pedidos/compras/{pedido_id}")["data"]

    def listar_pedidos_compras(
        self,
        pagina: int = 1,
        limite: int = 100,
        data_inicial: str | None = None,
        data_final: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final
        return self._get("/pedidos/compras", params=params)["data"]

    def obter_categoria_receita_despesa(self, categoria_id: int) -> dict[str, Any]:
        return self._get(f"/categorias/receitas-despesas/{categoria_id}")["data"]

    def listar_categorias_receitas_despesas(
        self, pagina: int = 1, limite: int = 100
    ) -> list[dict[str, Any]]:
        params = {"pagina": pagina, "limite": limite}
        return self._get("/categorias/receitas-despesas", params=params)["data"]

    def listar_contas_financeiras(self, pagina: int = 1, limite: int = 100) -> list[dict[str, Any]]:
        return self._get("/contas-contabeis", params={"pagina": pagina, "limite": limite})["data"]

    def listar_formas_pagamentos(self, pagina: int = 1, limite: int = 100) -> list[dict[str, Any]]:
        return self._get("/formas-pagamentos", params={"pagina": pagina, "limite": limite})["data"]

    def listar_contas_receber(
        self,
        pagina: int = 1,
        limite: int = 100,
        tipo_filtro_data: str = "E",
        data_inicial: str | None = None,
        data_final: str | None = None,
    ) -> list[dict[str, Any]]:
        """Contas a receber do período.

        `tipo_filtro_data`: E (emissão), V (vencimento) ou R (recebimento).
        """
        params: dict[str, Any] = {
            "pagina": pagina,
            "limite": limite,
            "tipoFiltroData": tipo_filtro_data,
        }
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final
        return self._get("/contas/receber", params=params)["data"]

    def obter_conta_receber(self, conta_id: int) -> dict[str, Any]:
        return self._get(f"/contas/receber/{conta_id}")["data"]

    def listar_contas_pagar(
        self,
        pagina: int = 1,
        limite: int = 100,
        data_emissao_inicial: str | None = None,
        data_emissao_final: str | None = None,
        data_vencimento_inicial: str | None = None,
        data_vencimento_final: str | None = None,
        data_pagamento_inicial: str | None = None,
        data_pagamento_final: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if data_emissao_inicial:
            params["dataEmissaoInicial"] = data_emissao_inicial
        if data_emissao_final:
            params["dataEmissaoFinal"] = data_emissao_final
        if data_vencimento_inicial:
            params["dataVencimentoInicial"] = data_vencimento_inicial
        if data_vencimento_final:
            params["dataVencimentoFinal"] = data_vencimento_final
        if data_pagamento_inicial:
            params["dataPagamentoInicial"] = data_pagamento_inicial
        if data_pagamento_final:
            params["dataPagamentoFinal"] = data_pagamento_final
        return self._get("/contas/pagar", params=params)["data"]

    def obter_conta_pagar(self, conta_id: int) -> dict[str, Any]:
        return self._get(f"/contas/pagar/{conta_id}")["data"]

    def obter_bordero(self, bordero_id: int) -> dict[str, Any]:
        return self._get(f"/borderos/{bordero_id}")["data"]

    def obter_contato(self, contato_id: int) -> dict[str, Any]:
        return self._get(f"/contatos/{contato_id}")["data"]

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
        numero: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if numero is not None:
            params["numero"] = numero
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
