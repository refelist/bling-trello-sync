import json
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    lojas_ignoradas: Annotated[list[str], NoDecode] = Field(default_factory=list)
    lojas_permitidas: Annotated[list[str], NoDecode] = Field(default_factory=list)

    database_path: str = "bling_trello_sync.db"

    @field_validator("trello_list_id_por_situacao", "nomes_situacoes", mode="before")
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

    def lista_para_situacao(self, situacao_id: int | None) -> str:
        if situacao_id is None:
            return self.trello_list_id_padrao
        return self.trello_list_id_por_situacao.get(str(situacao_id), self.trello_list_id_padrao)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
