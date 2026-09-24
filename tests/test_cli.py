from datetime import datetime, timedelta

from bling_trello_sync import cli
from bling_trello_sync.storage import Storage


def _args(**kwargs):
    padrao = {
        "desde": None,
        "ate": None,
        "dias": None,
        "data_inicial": None,
        "data_final": None,
        "tudo": False,
    }
    padrao.update(kwargs)
    return type("Args", (), padrao)()


def test_normaliza_data_simples():
    assert cli._normalizar_momento("2026-01-12") == "2026-01-12 00:00:00"
    assert cli._normalizar_momento("2026-01-12 10:30:00") == "2026-01-12 10:30:00"


def test_primeira_execucao_usa_ultimos_30_dias(settings):
    storage = Storage(settings.database_path)

    inicio, fim = cli._janela_de_alteracao(_args(), storage)

    esperado = datetime.now() - timedelta(days=30)
    assert datetime.strptime(inicio, cli.FORMATO_ALTERACAO).date() == esperado.date()
    assert fim is None


def test_execucao_seguinte_parte_da_ultima_sincronizacao(settings):
    storage = Storage(settings.database_path)
    storage.salvar_ultima_sincronizacao("2026-01-10 08:00:00")

    inicio, _ = cli._janela_de_alteracao(_args(), storage)

    assert inicio == "2026-01-10 08:00:00"


def test_filtro_por_data_de_emissao_ignora_janela_de_alteracao(settings):
    storage = Storage(settings.database_path)
    storage.salvar_ultima_sincronizacao("2026-01-10 08:00:00")

    assert cli._janela_de_alteracao(_args(data_inicial="2026-01-01"), storage) == (None, None)
    assert cli._janela_de_alteracao(_args(tudo=True), storage) == (None, None)
