from bling_trello_sync.checklist import NOME_CHECKLIST, sincronizar_checklist


class TrelloFake:
    def __init__(self) -> None:
        self.checklists: dict[str, list[dict]] = {}
        self.itens_criados: list[tuple[str, str]] = []
        self.itens_marcados: list[tuple[str, str]] = []
        self.itens_removidos: list[tuple[str, str]] = []

    def listar_checklists(self, card_id):
        return self.checklists.get(card_id, [])

    def criar_checklist(self, card_id, nome):
        checklist = {"id": f"chk-{len(self.checklists) + 1}", "name": nome, "checkItems": []}
        self.checklists.setdefault(card_id, []).append(checklist)
        return checklist

    def criar_item_checklist(self, checklist_id, nome, marcado=False):
        item = {
            "id": f"{checklist_id}-item-{len(self.itens_criados) + 1}",
            "name": nome,
            "state": "complete" if marcado else "incomplete",
        }
        self.itens_criados.append((checklist_id, nome))
        for checklists in self.checklists.values():
            for checklist in checklists:
                if checklist["id"] == checklist_id:
                    checklist["checkItems"].append(item)
        return item

    def marcar_item_checklist(self, card_id, item_id):
        self.itens_marcados.append((card_id, item_id))
        for checklist in self.checklists.get(card_id, []):
            for item in checklist["checkItems"]:
                if item["id"] == item_id:
                    item["state"] = "complete"

    def remover_item_checklist(self, checklist_id, item_id):
        self.itens_removidos.append((checklist_id, item_id))
        for checklists in self.checklists.values():
            for checklist in checklists:
                if checklist["id"] == checklist_id:
                    checklist["checkItems"] = [
                        item for item in checklist["checkItems"] if item["id"] != item_id
                    ]


def test_sincronizar_checklist_cria_e_marca():
    trello = TrelloFake()
    sincronizar_checklist(trello, "card-1", [("1 x A", False), ("2 x B", True)])

    assert trello.checklists["card-1"][0]["name"] == NOME_CHECKLIST
    itens = trello.checklists["card-1"][0]["checkItems"]
    assert [i["name"] for i in itens] == ["1 x A", "2 x B"]
    assert itens[0]["state"] == "incomplete"
    assert itens[1]["state"] == "complete"


def test_sincronizar_checklist_vazio_nao_faz_nada():
    trello = TrelloFake()
    sincronizar_checklist(trello, "card-1", [])
    assert trello.checklists == {}


def test_sincronizar_checklist_remove_itens_ausentes():
    trello = TrelloFake()
    sincronizar_checklist(trello, "card-1", [("A", False), ("B", False)])
    sincronizar_checklist(trello, "card-1", [("A", True)])

    itens = trello.checklists["card-1"][0]["checkItems"]
    assert [i["name"] for i in itens] == ["A"]
    assert itens[0]["state"] == "complete"
    assert len(trello.itens_removidos) == 1
