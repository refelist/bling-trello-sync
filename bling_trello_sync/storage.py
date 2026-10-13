import hashlib
import secrets
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

CREATE TABLE IF NOT EXISTS card_por_pedido_compra (
    pedido_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL,
    card_url TEXT NOT NULL,
    situacao_id INTEGER,
    atualizado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS comentario_compra (
    pedido_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    conteudo_hash TEXT NOT NULL,
    comentado_em REAL NOT NULL,
    PRIMARY KEY (pedido_id, tipo)
);

CREATE TABLE IF NOT EXISTS nota_comentada (
    pedido_id INTEGER NOT NULL,
    nota_id INTEGER NOT NULL,
    comentado_em REAL NOT NULL,
    PRIMARY KEY (pedido_id, nota_id)
);

CREATE TABLE IF NOT EXISTS evento_processado (
    event_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'done',
    processado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS estado (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_ticket (
    ticket TEXT PRIMARY KEY,
    expira_em REAL NOT NULL
);
"""

CHAVE_ULTIMA_SINCRONIZACAO = "ultima_sincronizacao"
CHAVE_OAUTH_STATE = "oauth_state"
OAUTH_TICKET_TTL_SEGUNDOS = 300


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
            self._migrar_evento_processado(conn)

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.caminho, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
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

    def salvar_card_compra(
        self, pedido_id: int, card_id: str, card_url: str, situacao_id: int | None
    ) -> None:
        with self._conexao() as conn:
            conn.execute(
                "INSERT INTO card_por_pedido_compra "
                "(pedido_id, card_id, card_url, situacao_id, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(pedido_id) DO UPDATE SET card_id = excluded.card_id, "
                "card_url = excluded.card_url, situacao_id = excluded.situacao_id, "
                "atualizado_em = excluded.atualizado_em",
                (pedido_id, card_id, card_url, situacao_id, time.time()),
            )

    def obter_card_compra(self, pedido_id: int) -> CardPedido | None:
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT * FROM card_por_pedido_compra WHERE pedido_id = ?", (pedido_id,)
            ).fetchone()
        if linha is None:
            return None
        return CardPedido(linha["pedido_id"], linha["card_id"], linha["card_url"], linha["situacao_id"])

    def registrar_comentario_compra(self, pedido_id: int, tipo: str, texto: str) -> bool:
        """Devolve True quando o texto ainda não foi comentado nesse pedido de compra."""
        conteudo_hash = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT conteudo_hash FROM comentario_compra WHERE pedido_id = ? AND tipo = ?",
                (pedido_id, tipo),
            ).fetchone()
            if linha is not None and linha["conteudo_hash"] == conteudo_hash:
                return False
            conn.execute(
                "INSERT INTO comentario_compra (pedido_id, tipo, conteudo_hash, comentado_em) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(pedido_id, tipo) DO UPDATE SET conteudo_hash = excluded.conteudo_hash, "
                "comentado_em = excluded.comentado_em",
                (pedido_id, tipo, conteudo_hash, time.time()),
            )
        return True

    def registrar_nota_comentada(self, pedido_id: int, nota_id: int) -> bool:
        """Grava a nota e devolve True só na primeira vez, para não repetir o comentário."""
        with self._conexao() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO nota_comentada (pedido_id, nota_id, comentado_em) "
                "VALUES (?, ?, ?)",
                (pedido_id, nota_id, time.time()),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _migrar_evento_processado(conn: sqlite3.Connection) -> None:
        colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(evento_processado)")}
        if "status" not in colunas:
            conn.execute(
                "ALTER TABLE evento_processado ADD COLUMN status TEXT NOT NULL DEFAULT 'done'"
            )

    def evento_ja_processado(self, event_id: str) -> bool:
        """True quando o evento já foi sincronizado com sucesso (status done)."""
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT status FROM evento_processado WHERE event_id = ?", (event_id,)
            ).fetchone()
        return linha is not None and linha["status"] == "done"

    def reclamar_evento(self, event_id: str) -> bool:
        """Tenta reservar o eventId (status processing). Devolve False se já existe."""
        with self._conexao() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO evento_processado (event_id, status, processado_em) "
                "VALUES (?, 'processing', ?)",
                (event_id, time.time()),
            )
            return cursor.rowcount > 0

    def concluir_evento(self, event_id: str) -> None:
        """Marca o evento como processado com sucesso."""
        with self._conexao() as conn:
            conn.execute(
                "UPDATE evento_processado SET status = 'done', processado_em = ? WHERE event_id = ?",
                (time.time(), event_id),
            )

    def liberar_evento(self, event_id: str) -> None:
        """Remove o claim em processing para o Bling poder reenviar ou o filtro mudar."""
        with self._conexao() as conn:
            conn.execute(
                "DELETE FROM evento_processado WHERE event_id = ? AND status = 'processing'",
                (event_id,),
            )

    def registrar_evento(self, event_id: str) -> bool:
        """Compatível com o fluxo antigo: conclui o evento (ou o cria já como done)."""
        with self._conexao() as conn:
            cursor = conn.execute(
                "INSERT INTO evento_processado (event_id, status, processado_em) "
                "VALUES (?, 'done', ?) "
                "ON CONFLICT(event_id) DO UPDATE SET status = 'done', "
                "processado_em = excluded.processado_em",
                (event_id, time.time()),
            )
            return cursor.rowcount > 0

    def purgar_eventos(self, dias: int = 30) -> int:
        """Remove eventos concluídos mais antigos que `dias`. Devolve quantos foram apagados."""
        if dias <= 0:
            return 0
        limite = time.time() - dias * 86400
        with self._conexao() as conn:
            cursor = conn.execute(
                "DELETE FROM evento_processado WHERE status = 'done' AND processado_em < ?",
                (limite,),
            )
            return cursor.rowcount

    def salvar_oauth_state(self, state: str) -> None:
        self.salvar_estado(CHAVE_OAUTH_STATE, state)

    def consumir_oauth_state(self, state: str) -> bool:
        """Confere e apaga o state OAuth; devolve True só se ele batia com o gravado."""
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT valor FROM estado WHERE chave = ?", (CHAVE_OAUTH_STATE,)
            ).fetchone()
            if linha is None or linha["valor"] != state:
                return False
            conn.execute("DELETE FROM estado WHERE chave = ?", (CHAVE_OAUTH_STATE,))
        return True

    def emitir_oauth_ticket(self, ttl_segundos: int = OAUTH_TICKET_TTL_SEGUNDOS) -> str:
        """Emite um ticket de uso único para abrir /oauth/bling/autorizar no navegador."""
        ticket = secrets.token_urlsafe(24)
        with self._conexao() as conn:
            conn.execute(
                "DELETE FROM oauth_ticket WHERE expira_em < ?", (time.time(),)
            )
            conn.execute(
                "INSERT INTO oauth_ticket (ticket, expira_em) VALUES (?, ?)",
                (ticket, time.time() + ttl_segundos),
            )
        return ticket

    def consumir_oauth_ticket(self, ticket: str) -> bool:
        """Confere, apaga e devolve True se o ticket existia e ainda era válido."""
        agora = time.time()
        with self._conexao() as conn:
            conn.execute("DELETE FROM oauth_ticket WHERE expira_em < ?", (agora,))
            linha = conn.execute(
                "SELECT expira_em FROM oauth_ticket WHERE ticket = ?", (ticket,)
            ).fetchone()
            if linha is None or linha["expira_em"] < agora:
                return False
            conn.execute("DELETE FROM oauth_ticket WHERE ticket = ?", (ticket,))
        return True

    def obter_estado(self, chave: str) -> str | None:
        with self._conexao() as conn:
            linha = conn.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
        return linha["valor"] if linha else None

    def salvar_estado(self, chave: str, valor: str) -> None:
        with self._conexao() as conn:
            conn.execute(
                "INSERT INTO estado (chave, valor) VALUES (?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                (chave, valor),
            )

    def obter_ultima_sincronizacao(self) -> str | None:
        return self.obter_estado(CHAVE_ULTIMA_SINCRONIZACAO)

    def salvar_ultima_sincronizacao(self, momento: str) -> None:
        self.salvar_estado(CHAVE_ULTIMA_SINCRONIZACAO, momento)
