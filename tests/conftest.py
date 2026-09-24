import json

import pytest

from bling_trello_sync.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        bling_client_id="client-id",
        bling_client_secret="client-secret",
        bling_redirect_uri="https://exemplo.com/oauth/bling/callback",
        trello_api_key="trello-key",
        trello_token="trello-token",
        trello_board_id="board-1",
        trello_list_id_padrao="lista-entrada",
        trello_list_id_por_situacao=json.dumps({"9": "lista-atendido"}),
        database_path=str(tmp_path / "teste.db"),
    )


@pytest.fixture
def pedido() -> dict:
    return {
        "id": 12345678,
        "numero": 123,
        "data": "2026-01-12",
        "dataPrevista": "2026-01-20",
        "total": 1234.5,
        "totalProdutos": 1200.0,
        "contato": {"id": 1, "nome": "Cliente Teste", "numeroDocumento": "30188025000121"},
        "situacao": {"id": 9, "valor": 1},
        "itens": [{"codigo": "BLG-5", "descricao": "Produto do Bling", "quantidade": 2, "valor": 600.0}],
        "observacoes": "Entregar pela manhã",
    }
