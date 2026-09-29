import json
import unicodedata
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalizar(texto: str) -> str:
    """Compara nomes de situação e de lista sem depender de acentos ou maiúsculas."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).strip().casefold()


class Settings(BaseSettings):
    """Configuração da integração, lida de variáveis de ambiente ou de um arquivo .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bling_client_id: str
    bling_client_secret: str
    bling_redirect_uri: str = "http://localhost:8000/callback"
    bling_api_base: str = "https://api.bling.com.br/Api/v3"
    bling_auth_base: str = "https://www.bling.com.br/Api/v3"

    trello_api_key: str
    trello_token: str
    trello_board_id: str
    trello_list_id_padrao: str
    trello_list_id_por_situacao: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    trello_label_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)

    nomes_situacoes: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)

    compras_ativo: bool = False
    compras_dias: int = 30
    compras_intervalo_minutos: int = 5
    trello_board_id_compras: str = ""
    trello_list_id_padrao_compras: str = ""
    trello_list_id_por_situacao_compra: Annotated[dict[str, str], NoDecode] = Field(
        default_factory=dict
    )

    financeiro_ativo: bool = False
    financeiro_empresa: str = "Empresa"
    financeiro_database_url: str = "financeiro.db"
    financeiro_dias: int = 365
    financeiro_dias_futuros: int = 365
    financeiro_intervalo_minutos: int = 60

    lojas_ignoradas: Annotated[list[str], NoDecode] = Field(default_factory=list)
    lojas_permitidas: Annotated[list[str], NoDecode] = Field(default_factory=list)

    database_path: str = "bling_trello_sync.db"

    verificar_assinatura_webhook: bool = True

    @field_validator(
        "trello_list_id_por_situacao",
        "nomes_situacoes",
        "trello_list_id_por_situacao_compra",
        mode="before",
    )
    @classmethod
    def _parse_mapa_situacoes(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            if not valor.strip():
                return {}
            return json.loads(valor)
        return valor

    @field_validator("trello_label_ids", "lojas_ignoradas", "lojas_permitidas", mode="before")
    @classmethod
    def _parse_labels(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            if not valor.strip():
                return []
            if valor.strip().startswith("["):
                return json.loads(valor)
            return [item.strip() for item in valor.split(",") if item.strip()]
        if isinstance(valor, list):
            return [str(item).strip() for item in valor if str(item).strip()]
        return valor

    def loja_sincronizavel(self, loja_id: Any) -> bool:
        """Aplica a lista de lojas permitidas e a de ignoradas; sem configuração, tudo passa."""
        identificador = str(loja_id) if loja_id is not None else ""
        if self.lojas_permitidas:
            return identificador in self.lojas_permitidas
        return identificador not in self.lojas_ignoradas

    def nome_para_situacao(self, situacao_id: int | None) -> str | None:
        if situacao_id is None:
            return None
        return self.nomes_situacoes.get(str(situacao_id))

    def lista_para_situacao(self, situacao_id: int | None, nome_situacao: str | None = None) -> str:
        """Lista configurada para a situação; a chave pode ser o id ou o nome da situação.

        O valor pode ser o id da lista no Trello ou o nome dela, resolvido na hora de usar.
        """
        mapa = self.trello_list_id_por_situacao
        if situacao_id is not None and str(situacao_id) in mapa:
            return mapa[str(situacao_id)]
        if nome_situacao:
            alvo = normalizar(nome_situacao)
            for chave, valor in mapa.items():
                if normalizar(chave) == alvo:
                    return valor
        return self.trello_list_id_padrao

    def lista_para_situacao_compra(self, valor: int | None, nome_situacao: str | None = None) -> str:
        """Lista do quadro de compras para a situação (chave pelo valor 0-3 ou pelo nome)."""
        mapa = self.trello_list_id_por_situacao_compra
        if valor is not None and str(valor) in mapa:
            return mapa[str(valor)]
        if nome_situacao:
            alvo = normalizar(nome_situacao)
            for chave, lista in mapa.items():
                if normalizar(chave) == alvo:
                    return lista
        return self.trello_list_id_padrao_compras


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
