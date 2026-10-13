"""Banco de destino dos dados financeiros, lido depois pelo Power BI.

Funciona em PostgreSQL (produção, acessado pelo Power BI) e em SQLite (testes e uso
local). O SQL usado é o mesmo nos dois bancos; só muda o marcador de parâmetro.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

TABELAS = """
CREATE TABLE IF NOT EXISTS categoria (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    descricao TEXT,
    tipo INTEGER,
    id_categoria_pai BIGINT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS conta_financeira (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    descricao TEXT,
    tipo TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS forma_pagamento (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    descricao TEXT,
    tipo_pagamento INTEGER,
    situacao INTEGER,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS contato (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    nome TEXT,
    documento TEXT,
    tipo TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS conta_receber (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    situacao INTEGER,
    data_emissao DATE,
    competencia DATE,
    vencimento DATE,
    valor DOUBLE PRECISION,
    saldo DOUBLE PRECISION,
    valor_recebido DOUBLE PRECISION,
    numero_documento TEXT,
    historico TEXT,
    categoria_id BIGINT,
    portador_id BIGINT,
    forma_pagamento_id BIGINT,
    contato_id BIGINT,
    contato_nome TEXT,
    vendedor_id BIGINT,
    origem_tipo TEXT,
    origem_id BIGINT,
    origem_numero TEXT,
    atualizado_em TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS conta_pagar (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    situacao INTEGER,
    data_emissao DATE,
    competencia DATE,
    vencimento DATE,
    valor DOUBLE PRECISION,
    saldo DOUBLE PRECISION,
    valor_pago DOUBLE PRECISION,
    numero_documento TEXT,
    historico TEXT,
    categoria_id BIGINT,
    portador_id BIGINT,
    forma_pagamento_id BIGINT,
    contato_id BIGINT,
    contato_nome TEXT,
    atualizado_em TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS movimento_caixa (
    empresa TEXT NOT NULL,
    bordero_id BIGINT NOT NULL,
    conta_id BIGINT NOT NULL,
    sequencia INTEGER NOT NULL DEFAULT 0,
    tipo TEXT NOT NULL,
    data DATE,
    valor_pago DOUBLE PRECISION,
    juros DOUBLE PRECISION,
    desconto DOUBLE PRECISION,
    acrescimo DOUBLE PRECISION,
    tarifa DOUBLE PRECISION,
    categoria_id BIGINT,
    portador_id BIGINT,
    contato_id BIGINT,
    contato_nome TEXT,
    historico TEXT,
    PRIMARY KEY (empresa, bordero_id, conta_id, sequencia)
);

CREATE TABLE IF NOT EXISTS pedido_venda (
    empresa TEXT NOT NULL,
    id BIGINT NOT NULL,
    numero TEXT,
    data DATE,
    data_saida DATE,
    total DOUBLE PRECISION,
    situacao_id BIGINT,
    contato_id BIGINT,
    contato_nome TEXT,
    loja_id BIGINT,
    vendedor_id BIGINT,
    atualizado_em TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS coleta_meta (
    empresa TEXT NOT NULL PRIMARY KEY,
    coletado_em TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    erros INTEGER NOT NULL DEFAULT 0,
    resumo TEXT
);
"""

# Situação de pedido de venda "Cancelado" no mapa JH/JHS (NOMES_SITUACOES / Trello).
SITUACAO_PEDIDO_CANCELADO = 12

_VISOES_TEMPLATE = """
CREATE VIEW vw_lancamento AS
SELECT r.empresa, 'receita' AS natureza, r.id, situacao,
       CASE situacao WHEN 1 THEN 'Em aberto' WHEN 2 THEN 'Liquidado' WHEN 3 THEN 'Parcial'
                     WHEN 4 THEN 'Devolvido' WHEN 5 THEN 'Cancelado'
                     WHEN 6 THEN 'Devolvido parcial' WHEN 7 THEN 'Confirmado'
                     ELSE 'Outra' END AS situacao_nome,
       data_emissao,
       COALESCE(competencia, data_emissao) AS competencia, vencimento,
       valor, saldo, valor_recebido AS valor_liquidado, categoria_id, portador_id,
       r.contato_id, COALESCE(r.contato_nome, ct.nome) AS contato_nome, historico
  FROM conta_receber r
  LEFT JOIN contato ct ON ct.empresa = r.empresa AND ct.id = r.contato_id
UNION ALL
SELECT p.empresa, 'despesa' AS natureza, p.id, situacao,
       CASE situacao WHEN 1 THEN 'Em aberto' WHEN 2 THEN 'Liquidado' WHEN 3 THEN 'Parcial'
                     WHEN 4 THEN 'Devolvido' WHEN 5 THEN 'Cancelado'
                     WHEN 6 THEN 'Devolvido parcial' WHEN 7 THEN 'Confirmado'
                     ELSE 'Outra' END AS situacao_nome,
       data_emissao,
       COALESCE(competencia, data_emissao) AS competencia, vencimento,
       valor, saldo, valor_pago AS valor_liquidado, categoria_id, portador_id,
       p.contato_id, COALESCE(p.contato_nome, ct.nome) AS contato_nome, historico
  FROM conta_pagar p
  LEFT JOIN contato ct ON ct.empresa = p.empresa AND ct.id = p.contato_id;

CREATE VIEW vw_dre AS
SELECT l.empresa,
       l.competencia,
       l.natureza,
       COALESCE(c.descricao, 'Sem categoria') AS categoria,
       CASE WHEN l.natureza = 'receita' THEN l.valor ELSE -l.valor END AS valor
  FROM vw_lancamento l
  LEFT JOIN categoria c ON c.empresa = l.empresa AND c.id = l.categoria_id
 WHERE l.situacao <> 5;

CREATE VIEW vw_fluxo_caixa AS
SELECT m.empresa,
       m.data,
       m.tipo,
       c.descricao AS categoria,
       f.descricao AS conta_financeira,
       m.contato_nome,
       m.valor_pago,
       m.juros,
       m.desconto,
       m.acrescimo,
       m.tarifa,
       CASE WHEN m.tipo = 'receber' THEN
              COALESCE(m.valor_pago, 0) + COALESCE(m.juros, 0) + COALESCE(m.acrescimo, 0)
              - COALESCE(m.desconto, 0) - COALESCE(m.tarifa, 0)
            ELSE
              -(COALESCE(m.valor_pago, 0) + COALESCE(m.juros, 0) + COALESCE(m.acrescimo, 0)
                - COALESCE(m.desconto, 0) - COALESCE(m.tarifa, 0))
       END AS valor
  FROM movimento_caixa m
  LEFT JOIN categoria c ON c.empresa = m.empresa AND c.id = m.categoria_id
  LEFT JOIN conta_financeira f ON f.empresa = m.empresa AND f.id = m.portador_id;

CREATE VIEW vw_contas_em_aberto AS
SELECT l.empresa,
       l.natureza,
       l.vencimento,
       COALESCE(c.descricao, 'Sem categoria') AS categoria,
       l.contato_nome,
       l.saldo AS valor_em_aberto
  FROM vw_lancamento l
  LEFT JOIN categoria c ON c.empresa = l.empresa AND c.id = l.categoria_id
 WHERE l.situacao IN (1, 3, 7) AND COALESCE(l.saldo, 0) > 0;

CREATE VIEW vw_faturamento AS
SELECT empresa, data, numero, contato_nome, loja_id, situacao_id, total
  FROM pedido_venda
 WHERE situacao_id IS NULL OR situacao_id <> {cancelado};

CREATE VIEW vw_coleta_meta AS
SELECT empresa, coletado_em, ok, erros, resumo FROM coleta_meta;
"""

VISOES = _VISOES_TEMPLATE.format(cancelado=SITUACAO_PEDIDO_CANCELADO)

INDICES = """
CREATE INDEX IF NOT EXISTS idx_conta_receber_empresa_competencia
    ON conta_receber (empresa, competencia);
CREATE INDEX IF NOT EXISTS idx_conta_receber_empresa_vencimento
    ON conta_receber (empresa, vencimento);
CREATE INDEX IF NOT EXISTS idx_conta_pagar_empresa_competencia
    ON conta_pagar (empresa, competencia);
CREATE INDEX IF NOT EXISTS idx_conta_pagar_empresa_vencimento
    ON conta_pagar (empresa, vencimento);
CREATE INDEX IF NOT EXISTS idx_movimento_caixa_empresa_data
    ON movimento_caixa (empresa, data);
CREATE INDEX IF NOT EXISTS idx_pedido_venda_empresa_data
    ON pedido_venda (empresa, data);
"""

CHAVES = {
    "categoria": ("empresa", "id"),
    "conta_financeira": ("empresa", "id"),
    "forma_pagamento": ("empresa", "id"),
    "contato": ("empresa", "id"),
    "conta_receber": ("empresa", "id"),
    "conta_pagar": ("empresa", "id"),
    "movimento_caixa": ("empresa", "bordero_id", "conta_id", "sequencia"),
    "pedido_venda": ("empresa", "id"),
    "coleta_meta": ("empresa",),
}

# Suba este número quando mudar tabelas/visões para forçar migração única (sem DROP a cada boot).
ESQUEMA_VERSAO = 3


def versao_da_conta(situacao: Any, valor: Any, vencimento: Any) -> tuple[Any, ...]:
    """Identidade usada para saber se a conta mudou desde a última coleta."""
    try:
        valor_normalizado = round(float(valor), 2)
    except (TypeError, ValueError):
        valor_normalizado = None
    situacao_normalizada = int(situacao) if situacao is not None else None
    return (situacao_normalizada, valor_normalizado, str(vencimento or ""))


class Armazem:
    """Escreve as tabelas financeiras no banco configurado por uma URL de conexão.

    `postgresql://usuario:senha@host:5432/banco` usa PostgreSQL; qualquer outro valor é
    tratado como caminho de um arquivo SQLite.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        self.placeholder = "%s" if self.postgres else "?"
        self._criar_esquema()

    @contextmanager
    def conexao(self) -> Iterator[Any]:
        if self.postgres:
            import psycopg

            conn = psycopg.connect(self.url)
        else:
            conn = sqlite3.connect(self.url, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _criar_esquema(self) -> None:
        comandos_visao = [c.strip() for c in VISOES.split(";") if c.strip()]
        nomes_visao = [c.split("VIEW", 1)[1].split("AS", 1)[0].strip() for c in comandos_visao]
        with self.conexao() as conn:
            cursor = conn.cursor()
            self._assegurar_meta(cursor)
            for comando in TABELAS.split(";"):
                if comando.strip():
                    cursor.execute(comando)
            self._migrar_movimento_caixa(cursor)
            for comando in INDICES.split(";"):
                if comando.strip():
                    cursor.execute(comando)
            versao = self._ler_versao(cursor)
            if versao < ESQUEMA_VERSAO:
                for nome in reversed(nomes_visao):
                    cursor.execute(f"DROP VIEW IF EXISTS {nome}")
                for comando in comandos_visao:
                    cursor.execute(comando)
                self._gravar_versao(cursor, ESQUEMA_VERSAO)
            else:
                for comando, nome in zip(comandos_visao, nomes_visao, strict=True):
                    if not self._visao_existe(cursor, nome):
                        cursor.execute(comando)

    def _assegurar_meta(self, cursor: Any) -> None:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS esquema_meta ("
            "chave TEXT NOT NULL PRIMARY KEY, valor TEXT NOT NULL)"
        )

    def _ler_versao(self, cursor: Any) -> int:
        cursor.execute(
            f"SELECT valor FROM esquema_meta WHERE chave = {self.placeholder}",
            ("versao",),
        )
        linha = cursor.fetchone()
        if linha is None:
            return 0
        try:
            return int(linha[0])
        except (TypeError, ValueError):
            return 0

    def _gravar_versao(self, cursor: Any, versao: int) -> None:
        cursor.execute(
            f"INSERT INTO esquema_meta (chave, valor) VALUES ({self.placeholder}, {self.placeholder}) "
            "ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
            ("versao", str(versao)),
        )

    def _visao_existe(self, cursor: Any, nome: str) -> bool:
        if self.postgres:
            cursor.execute(
                "SELECT 1 FROM information_schema.views "
                "WHERE table_schema = 'public' AND table_name = %s",
                (nome,),
            )
        else:
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?", (nome,)
            )
        return cursor.fetchone() is not None

    def _colunas_da_tabela(self, cursor: Any, tabela: str) -> set[str]:
        if self.postgres:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (tabela,),
            )
            return {str(linha[0]) for linha in cursor.fetchall()}
        cursor.execute(f"PRAGMA table_info({tabela})")
        return {str(linha[1]) for linha in cursor.fetchall()}

    def _migrar_movimento_caixa(self, cursor: Any) -> None:
        """Garante a coluna sequencia e a PK (empresa, bordero_id, conta_id, sequencia)."""
        colunas = self._colunas_da_tabela(cursor, "movimento_caixa")
        if not colunas:
            return
        if "sequencia" in colunas:
            return
        if self.postgres:
            cursor.execute(
                "ALTER TABLE movimento_caixa ADD COLUMN sequencia INTEGER NOT NULL DEFAULT 0"
            )
            cursor.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'movimento_caixa'::regclass AND contype = 'p'"
            )
            pk = cursor.fetchone()
            if pk is not None:
                cursor.execute(f'ALTER TABLE movimento_caixa DROP CONSTRAINT "{pk[0]}"')
            cursor.execute(
                "ALTER TABLE movimento_caixa "
                "ADD PRIMARY KEY (empresa, bordero_id, conta_id, sequencia)"
            )
            return
        cursor.execute(
            "CREATE TABLE movimento_caixa_nova ("
            "empresa TEXT NOT NULL, bordero_id BIGINT NOT NULL, conta_id BIGINT NOT NULL, "
            "sequencia INTEGER NOT NULL DEFAULT 0, tipo TEXT NOT NULL, data DATE, "
            "valor_pago DOUBLE PRECISION, juros DOUBLE PRECISION, desconto DOUBLE PRECISION, "
            "acrescimo DOUBLE PRECISION, tarifa DOUBLE PRECISION, categoria_id BIGINT, "
            "portador_id BIGINT, contato_id BIGINT, contato_nome TEXT, historico TEXT, "
            "PRIMARY KEY (empresa, bordero_id, conta_id, sequencia))"
        )
        cursor.execute(
            "INSERT INTO movimento_caixa_nova ("
            "empresa, bordero_id, conta_id, sequencia, tipo, data, valor_pago, juros, "
            "desconto, acrescimo, tarifa, categoria_id, portador_id, contato_id, "
            "contato_nome, historico) "
            "SELECT empresa, bordero_id, conta_id, 0, tipo, data, valor_pago, juros, "
            "desconto, acrescimo, tarifa, categoria_id, portador_id, contato_id, "
            "contato_nome, historico FROM movimento_caixa"
        )
        cursor.execute("DROP TABLE movimento_caixa")
        cursor.execute("ALTER TABLE movimento_caixa_nova RENAME TO movimento_caixa")

    def gravar(self, tabela: str, linhas: Sequence[dict[str, Any]]) -> int:
        """Insere ou atualiza as linhas pela chave primária da tabela."""
        if not linhas:
            return 0
        colunas = list(linhas[0])
        chave = CHAVES[tabela]
        atualizacoes = [c for c in colunas if c not in chave]
        valores = ", ".join(self.placeholder for _ in colunas)
        sql = f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({valores})"
        if atualizacoes:
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in atualizacoes)
            sql += f" ON CONFLICT ({', '.join(chave)}) DO UPDATE SET {sets}"
        else:
            sql += f" ON CONFLICT ({', '.join(chave)}) DO NOTHING"
        with self.conexao() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, [tuple(linha[c] for c in colunas) for linha in linhas])
        return len(linhas)

    def ler(self, sql: str, parametros: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        with self.conexao() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(parametros))
            return [tuple(linha) for linha in cursor.fetchall()]

    def versoes_das_contas(self, tabela: str, empresa: str) -> dict[int, tuple[Any, ...]]:
        """Situação, valor e vencimento já gravados, para pular o detalhe do que não mudou."""
        linhas = self.ler(
            f"SELECT id, situacao, valor, vencimento FROM {tabela} "
            f"WHERE empresa = {self.placeholder}",
            (empresa,),
        )
        return {int(linha[0]): versao_da_conta(linha[1], linha[2], linha[3]) for linha in linhas}

    def borderos_conhecidos(self, empresa: str) -> set[int]:
        linhas = self.ler(
            f"SELECT DISTINCT bordero_id FROM movimento_caixa WHERE empresa = {self.placeholder}",
            (empresa,),
        )
        return {int(linha[0]) for linha in linhas}

    def contatos_sem_nome(self, empresa: str) -> list[int]:
        """Contatos das contas cujo nome o Bling não mandou e que ainda não estão no cadastro."""
        linhas = self.ler(
            "SELECT DISTINCT l.contato_id FROM vw_lancamento l "
            f"WHERE l.empresa = {self.placeholder} AND l.contato_id IS NOT NULL "
            "AND l.contato_nome IS NULL ORDER BY 1",
            (empresa,),
        )
        return [int(linha[0]) for linha in linhas]

    def registrar_coleta(
        self, empresa: str, *, ok: bool, erros: int, resumo: str, coletado_em: str
    ) -> None:
        """Grava o resultado da última coleta financeira da empresa (lido pelos painéis)."""
        self.gravar(
            "coleta_meta",
            [
                {
                    "empresa": empresa,
                    "coletado_em": coletado_em,
                    "ok": 1 if ok else 0,
                    "erros": erros,
                    "resumo": resumo[:2000] if resumo else None,
                }
            ],
        )

    def ultima_coleta(self, empresa: str | None = None) -> list[tuple[Any, ...]]:
        if empresa is None:
            return self.ler(
                "SELECT empresa, coletado_em, ok, erros, resumo FROM coleta_meta ORDER BY empresa"
            )
        return self.ler(
            "SELECT empresa, coletado_em, ok, erros, resumo FROM coleta_meta "
            f"WHERE empresa = {self.placeholder}",
            (empresa,),
        )
