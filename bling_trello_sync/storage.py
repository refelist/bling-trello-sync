import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

ESQUEMA = """
CREATE TABLE IF NOT EXISTS token_bling (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expira_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS card_por_pedido (
    pedido_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL,
    card_url TEXT NOT NULL,
    situacao_id INTEGER,
    atualizado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS evento_processado (
    event_id TEXT PRIMARY KEY,
    processado_em REAL NOT NULL
);
"""


@dataclass
class TokenBling:
    access_token: str
    refresh_token: str
    expira_em: float

    @property
    def expirado(self) -> bool:
        return time.time() >= self.expira_em - 60


@dataclass
class CardPedido:
    pedido_id: int
    card_id: str
    card_url: str
    situacao_id: int | None


class Storage:
    def __init__(self, caminho: str) -> None:
        self.caminho = caminho
        with self._conexao() as conn:
            conn.executescript(ESQUEMA)

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.caminho, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def salvar_token(self, token: TokenBling) -> None:
        with self._conexao() as conn:
            conn.execute(
                "INSERT INTO token_bling (id, access_token, refresh_token, expira_em) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET access_token = excluded.access_token, "
                "refresh_token = excluded.refresh_token, expira_em = excluded.expira_em",
                (token.access_token, token.refresh_token, token.expira_em),
            )

    def obter_token(self) -> TokenBling | None:
        with self._conexao() as conn:
            linha = conn.execute("SELECT * FROM token_bling WHERE id = 1").fetchone()
        if linha is None:
            return None
        return TokenBling(linha["access_token"], linha["refresh_token"], linha["expira_em"])

    def salvar_card(
        self, pedido_id: int, card_id: str, card_url: str, situacao_id: int | None
    ) -> None:
        with self._conexao() as conn:
            conn.execute(
                "INSERT INTO card_por_pedido (pedido_id, card_id, card_url, situacao_id, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(pedido_id) DO UPDATE SET card_id = excluded.card_id, "
                "card_url = excluded.card_url, situacao_id = excluded.situacao_id, "
                "atualizado_em = excluded.atualizado_em",
                (pedido_id, card_id, card_url, situacao_id, time.time()),
            )

    def obter_card(self, pedido_id: int) -> CardPedido | None:
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT * FROM card_por_pedido WHERE pedido_id = ?", (pedido_id,)
            ).fetchone()
        if linha is None:
            return None
        return CardPedido(linha["pedido_id"], linha["card_id"], linha["card_url"], linha["situacao_id"])

    def remover_card(self, pedido_id: int) -> None:
        with self._conexao() as conn:
            conn.execute("DELETE FROM card_por_pedido WHERE pedido_id = ?", (pedido_id,))

    def registrar_evento(self, event_id: str) -> bool:
        """Registra o evento e retorna False se ele já havia sido processado."""
        with self._conexao() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO evento_processado (event_id, processado_em) VALUES (?, ?)",
                (event_id, time.time()),
            )
        return cursor.rowcount > 0
