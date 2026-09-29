import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .armazem import Armazem
from .bling import BlingClient, validar_assinatura
from .compras import SincronizadorCompras
from .config import Settings, get_settings
from .financeiro import ColetorFinanceiro
from .storage import Storage
from .sync import Sincronizador
from .trello import TrelloClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tarefas = [_iniciar_compras(), _iniciar_financeiro()]
    try:
        yield
    finally:
        for tarefa in tarefas:
            if tarefa is not None:
                tarefa.cancel()


app = FastAPI(
    title="Bling -> Trello",
    description="Cria cards no Trello a partir de pedidos de venda do Bling",
    lifespan=lifespan,
)


def get_storage(settings: Settings = Depends(get_settings)) -> Storage:
    return Storage(settings.database_path)


def get_bling(
    settings: Settings = Depends(get_settings), storage: Storage = Depends(get_storage)
) -> BlingClient:
    return BlingClient(settings, storage)


def get_trello(settings: Settings = Depends(get_settings)) -> TrelloClient:
    return TrelloClient(settings.trello_api_key, settings.trello_token)


def get_sincronizador_compras(
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    bling: BlingClient = Depends(get_bling),
    trello: TrelloClient = Depends(get_trello),
) -> SincronizadorCompras:
    return SincronizadorCompras(settings, storage, bling, trello)


def get_sincronizador(
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    bling: BlingClient = Depends(get_bling),
    trello: TrelloClient = Depends(get_trello),
) -> Sincronizador:
    return Sincronizador(settings, storage, bling, trello)


def extrair_id_pedido(data: Any) -> int | None:
    if isinstance(data, dict):
        for chave in ("id", "idPedidoVenda", "idPedido"):
            valor = data.get(chave)
            if isinstance(valor, (int, str)) and str(valor).isdigit():
                return int(valor)
        for aninhado in ("pedido", "order"):
            encontrado = extrair_id_pedido(data.get(aninhado))
            if encontrado is not None:
                return encontrado
    return None


def _iniciar_compras() -> "asyncio.Task[None] | None":
    settings = get_settings()
    if not settings.compras_ativo:
        return None
    if not settings.trello_board_id_compras:
        logger.warning("COMPRAS_ATIVO ligado sem TRELLO_BOARD_ID_COMPRAS; compras desativadas")
        return None
    logger.info(
        "Sincronização de pedidos de compra ativa (a cada %s min)",
        settings.compras_intervalo_minutos,
    )
    return asyncio.create_task(_loop_compras(settings))


async def _loop_compras(settings: Settings) -> None:
    """O Bling não tem webhook de pedido de compra, então o quadro é atualizado por consulta."""
    intervalo = max(1, settings.compras_intervalo_minutos) * 60
    storage = Storage(settings.database_path)
    compras = SincronizadorCompras(
        settings,
        storage,
        BlingClient(settings, storage),
        TrelloClient(settings.trello_api_key, settings.trello_token),
    )
    while True:
        try:
            resumo = await asyncio.to_thread(compras.sincronizar_lote)
            logger.info(
                "Compras: %s encontradas | %s criadas | %s atualizadas | %s erros",
                resumo.pedidos_encontrados,
                resumo.cards_criados,
                resumo.cards_atualizados,
                len(resumo.erros),
            )
        except Exception:  # noqa: BLE001 - o loop não pode morrer por uma falha pontual
            logger.exception("Falha ao sincronizar os pedidos de compra")
        await asyncio.sleep(intervalo)


def _iniciar_financeiro() -> "asyncio.Task[None] | None":
    settings = get_settings()
    if not settings.financeiro_ativo:
        return None
    logger.info(
        "Coleta financeira ativa (a cada %s min) gravando em %s",
        settings.financeiro_intervalo_minutos,
        settings.financeiro_database_url.split("@")[-1],
    )
    return asyncio.create_task(_loop_financeiro(settings))


async def _loop_financeiro(settings: Settings) -> None:
    """Atualiza o banco financeiro lido pelo Power BI; o Bling não avisa mudanças por webhook."""
    intervalo = max(1, settings.financeiro_intervalo_minutos) * 60
    storage = Storage(settings.database_path)
    coletor = ColetorFinanceiro(
        settings, BlingClient(settings, storage), Armazem(settings.financeiro_database_url)
    )
    while True:
        try:
            resumo = await asyncio.to_thread(coletor.coletar)
            logger.info("Financeiro: %s | %s erros", resumo, len(resumo.erros))
        except Exception:  # noqa: BLE001 - o loop não pode morrer por uma falha pontual
            logger.exception("Falha ao coletar os dados financeiros")
        await asyncio.sleep(intervalo)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/oauth/bling/autorizar")
def autorizar(bling: BlingClient = Depends(get_bling)) -> RedirectResponse:
    """Inicia o fluxo OAuth2 do Bling (abra no navegador e autorize o aplicativo)."""
    return RedirectResponse(bling.url_de_autorizacao(state=secrets.token_urlsafe(16)))


@app.get("/oauth/bling/callback")
def callback(code: str | None = None, bling: BlingClient = Depends(get_bling)) -> dict[str, str]:
    if not code:
        raise HTTPException(status_code=400, detail="Parâmetro 'code' ausente no callback")
    bling.trocar_codigo_por_token(code)
    return {"status": "autorizado", "mensagem": "Tokens do Bling armazenados com sucesso."}


@app.get("/trello/listas")
def listas_do_board(
    settings: Settings = Depends(get_settings), trello: TrelloClient = Depends(get_trello)
) -> list[dict[str, Any]]:
    """Auxiliar para descobrir os IDs das listas do board e montar o mapa de situações."""
    return trello.listar_listas(settings.trello_board_id)


@app.post("/sincronizar/{pedido_id}")
def sincronizar_manual(
    pedido_id: int, sincronizador: Sincronizador = Depends(get_sincronizador)
) -> dict[str, Any]:
    resultado = sincronizador.sincronizar_pedido(pedido_id)
    return resultado.__dict__


@app.post("/sincronizar-compra/{pedido_id}")
def sincronizar_compra_manual(
    pedido_id: int, compras: SincronizadorCompras = Depends(get_sincronizador_compras)
) -> dict[str, Any]:
    return compras.sincronizar_pedido(pedido_id).__dict__


@app.post("/webhooks/bling")
async def webhook_bling(
    request: Request,
    background_tasks: BackgroundTasks,
    x_bling_signature_256: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    sincronizador: Sincronizador = Depends(get_sincronizador),
) -> JSONResponse:
    corpo = await request.body()

    if settings.verificar_assinatura_webhook and not validar_assinatura(
        corpo, x_bling_signature_256, settings.bling_client_secret
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida")

    try:
        evento = await request.json()
    except ValueError as erro:
        raise HTTPException(status_code=400, detail="Payload não é um JSON válido") from erro

    nome_evento = str(evento.get("event", ""))
    event_id = str(evento.get("eventId", ""))
    if not nome_evento.startswith(("order.", "pedido.", "pedidoVenda.")):
        return JSONResponse({"status": "ignorado", "motivo": f"evento '{nome_evento}' não tratado"})

    pedido_id = extrair_id_pedido(evento.get("data"))
    if pedido_id is None:
        logger.warning("Webhook sem id de pedido identificável: %s", evento)
        return JSONResponse({"status": "ignorado", "motivo": "id do pedido não encontrado no payload"})

    if event_id and not storage.registrar_evento(event_id):
        return JSONResponse({"status": "ignorado", "motivo": "evento já processado"})

    acao = nome_evento.split(".", 1)[1]
    # O Bling exige resposta 2xx em até 5s, então a sincronização roda fora do ciclo da requisição.
    background_tasks.add_task(_processar, sincronizador, pedido_id, acao)
    return JSONResponse({"status": "recebido", "pedidoId": pedido_id, "acao": acao}, status_code=202)


def _processar(sincronizador: Sincronizador, pedido_id: int, acao: str) -> None:
    try:
        resultado = sincronizador.sincronizar_pedido(pedido_id)
        logger.info("Pedido %s (%s): %s", pedido_id, acao, resultado.acao)
    except Exception:  # noqa: BLE001 - background task não pode derrubar o servidor
        logger.exception("Falha ao sincronizar o pedido %s", pedido_id)
