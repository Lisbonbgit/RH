"""**O GET de um documento por id** — o único sítio onde vivem o ATCUD e as
linhas.

Medido no Vendus a 2026-09-04: a lista (`GET documents/`), mesmo com
`view=detailed`, devolve 18 campos e NENHUM deles é `atcud` ou `items`. O
documento por id devolve 25, com os dois. E esse pedido NÃO aceita `view` —
responde 403 P001.
"""
import httpx
import pytest

from faturacao.vendus.emissao import ClienteEmissaoVendus


def _cliente(responder):
    return ClienteEmissaoVendus("chave-de-teste",
                                transport=httpx.MockTransport(responder),
                                dormir=lambda _s: None)


def test_traz_o_atcud_e_as_linhas():
    def responder(pedido):
        assert pedido.url.path.endswith("/documents/370665072/")
        return httpx.Response(200, json=[{
            "id": 370665072, "number": "FS 06P2026/446",
            "atcud": "J6SHGSNX-446", "type": "FS",
            "amount_gross": "6.85", "amount_net": "6.06",
            "items": [{"qty": 1, "title": "Açaí Mini",
                       "amounts": {"gross_total": "6.85", "net_total": "6.06"},
                       "tax": {"id": "INT", "rate": 13}}],
        }])
    with _cliente(responder) as c:
        doc = c.ler_documento(370665072)
    assert doc["atcud"] == "J6SHGSNX-446"
    assert doc["items"][0]["title"] == "Açaí Mini"


def test_nunca_manda_o_parametro_view():
    # O Vendus responde 403 P001 a um `view` num GET por id. O teste confronta
    # o pedido que sai, não a intenção de quem o escreveu.
    vistos = []

    def responder(pedido):
        vistos.append(str(pedido.url))
        return httpx.Response(200, json=[{"id": 1, "atcud": "X-1"}])
    with _cliente(responder) as c:
        c.ler_documento(1)
    assert "view" not in vistos[0]


def test_um_404_e_none_e_nao_uma_avaria():
    def responder(_pedido):
        return httpx.Response(404, json={"errors": [{"code": "A001"}]})
    with _cliente(responder) as c:
        assert c.ler_documento(999) is None


def test_um_corpo_que_nao_se_le_nao_vira_documento_vazio():
    from faturacao.vendus.emissao import VendusRespostaIlegivel

    def responder(_pedido):
        return httpx.Response(200, content=b"nao e json")
    with _cliente(responder) as c:
        with pytest.raises(VendusRespostaIlegivel):
            c.ler_documento(1)
