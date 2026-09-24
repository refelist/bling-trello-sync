from typing import Any

import httpx

API_BASE = "https://api.trello.com/1"


class TrelloClient:
    def __init__(self, api_key: str, token: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.token = token
        self._client = client or httpx.Client(timeout=30)

    def _auth(self) -> dict[str, str]:
        return {"key": self.api_key, "token": self.token}

    def _request(self, metodo: str, caminho: str, params: dict[str, Any] | None = None) -> Any:
        resposta = self._client.request(
            metodo,
            f"{API_BASE}{caminho}",
            params={**self._auth(), **(params or {})},
            headers={"Accept": "application/json"},
        )
        resposta.raise_for_status()
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
        params: dict[str, Any] = {"idList": id_list, "name": nome, "desc": descricao, "pos": "top"}
        if due:
            params["due"] = due
        if id_labels:
            params["idLabels"] = ",".join(id_labels)
        return self._request("POST", "/cards", params)

    def atualizar_card(
        self,
        card_id: str,
        nome: str | None = None,
        descricao: str | None = None,
        id_list: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if nome is not None:
            params["name"] = nome
        if descricao is not None:
            params["desc"] = descricao
        if id_list is not None:
            params["idList"] = id_list
        if due is not None:
            params["due"] = due
        if closed is not None:
            params["closed"] = str(closed).lower()
        return self._request("PUT", f"/cards/{card_id}", params)

    def comentar(self, card_id: str, texto: str) -> dict[str, Any]:
        return self._request("POST", f"/cards/{card_id}/actions/comments", {"text": texto})

    def obter_card(self, card_id: str) -> dict[str, Any]:
        return self._request("GET", f"/cards/{card_id}", {"fields": "id,name,idList,closed,shortUrl"})
