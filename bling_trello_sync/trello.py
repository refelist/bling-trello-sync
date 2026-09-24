from typing import Any

import httpx

API_BASE = "https://api.trello.com/1"
LIMITE_NOME = 16384
LIMITE_DESCRICAO = 16384
LIMITE_ITEM = 16384


class TrelloError(RuntimeError):
    """Erro da API do Trello com o corpo da resposta, que traz o motivo da recusa."""

    def __init__(self, mensagem: str, status_code: int) -> None:
        super().__init__(mensagem)
        self.status_code = status_code


class CardNaoEncontrado(TrelloError):
    """O card registrado localmente não existe mais no Trello."""


class TrelloClient:
    def __init__(self, api_key: str, token: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.token = token
        self._client = client or httpx.Client(timeout=30)

    def _auth(self) -> dict[str, str]:
        return {"key": self.api_key, "token": self.token}

    def _request(
        self,
        metodo: str,
        caminho: str,
        params: dict[str, Any] | None = None,
        corpo: dict[str, Any] | None = None,
    ) -> Any:
        resposta = self._client.request(
            metodo,
            f"{API_BASE}{caminho}",
            params={**self._auth(), **(params or {})},
            json=corpo,
            headers={"Accept": "application/json"},
        )
        if resposta.status_code >= 400:
            mensagem = f"{resposta.status_code} em {metodo} {caminho}: {resposta.text}"
            if resposta.status_code == 404:
                raise CardNaoEncontrado(mensagem, resposta.status_code)
            raise TrelloError(mensagem, resposta.status_code)
        return resposta.json()

    def listar_listas(self, board_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/boards/{board_id}/lists", {"fields": "id,name"})

    def listar_labels(self, board_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/boards/{board_id}/labels", {"fields": "id,name,color"})

    def criar_card(
        self,
        id_list: str,
        nome: str,
        descricao: str,
        due: str | None = None,
        id_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        corpo: dict[str, Any] = {
            "idList": id_list,
            "name": nome[:LIMITE_NOME],
            "desc": descricao[:LIMITE_DESCRICAO],
            "pos": "top",
        }
        if due:
            corpo["due"] = due
        if id_labels:
            corpo["idLabels"] = id_labels
        return self._request("POST", "/cards", corpo=corpo)

    def atualizar_card(
        self,
        card_id: str,
        nome: str | None = None,
        descricao: str | None = None,
        id_list: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
    ) -> dict[str, Any]:
        corpo: dict[str, Any] = {}
        if nome is not None:
            corpo["name"] = nome[:LIMITE_NOME]
        if descricao is not None:
            corpo["desc"] = descricao[:LIMITE_DESCRICAO]
        if id_list is not None:
            corpo["idList"] = id_list
        if due is not None:
            corpo["due"] = due
        if closed is not None:
            corpo["closed"] = closed
        return self._request("PUT", f"/cards/{card_id}", corpo=corpo)

    def listar_checklists(self, card_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET", f"/cards/{card_id}/checklists", {"fields": "id,name", "checkItems": "all"}
        )

    def criar_checklist(self, card_id: str, nome: str) -> dict[str, Any]:
        return self._request("POST", f"/cards/{card_id}/checklists", corpo={"name": nome})

    def criar_item_checklist(self, checklist_id: str, nome: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/checklists/{checklist_id}/checkItems",
            corpo={"name": nome[:LIMITE_ITEM], "pos": "bottom"},
        )

    def remover_item_checklist(self, checklist_id: str, item_id: str) -> Any:
        return self._request("DELETE", f"/checklists/{checklist_id}/checkItems/{item_id}")

    def comentar(self, card_id: str, texto: str) -> dict[str, Any]:
        return self._request("POST", f"/cards/{card_id}/actions/comments", corpo={"text": texto})

    def obter_card(self, card_id: str) -> dict[str, Any]:
        return self._request("GET", f"/cards/{card_id}", {"fields": "id,name,idList,closed,shortUrl"})
