import logging
import secrets
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .bling import BlingClient, validar_assinatura
from .config import Settings, get_settings
from .storage import Storage
from .sync import Sincronizador
from .trello import TrelloClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Bling -> Trello",
    description="Cria cards no Trello a partir de pedidos de venda do Bling",
)


def get_storage(settings: Settings = Depends(get_settings)) -> Storage:
    return Storage(settings.database_path)


def get_bling(
    settings: Settings = Depends(get_settings), storage: Storage = Depends(get_storage)
) -> BlingClient:
    return BlingClient(settings, storage)


def get_trello(settings: Settings = Depends(get_settings)) -> TrelloClient:
    return TrelloClient(settings.trello_api_key, settings.trello_token)


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
