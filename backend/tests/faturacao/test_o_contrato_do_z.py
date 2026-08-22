"""**As duas metades do Z, e as duas mutações que sobreviveram à ronda passada.**

O fecho de caixa produz duas coisas diferentes com o mesmo nome:

- o que se **GRAVA** na sessão (`$set` de `fechar_caixa`) — o registo permanente
  do turno, que o gestor lê dias depois;
- o que se **DEVOLVE** ao ecrã — o Z de papel que a operadora assina.

Os dois têm regras opostas, e nenhuma delas tinha guarda.

**1. O que se GRAVA não pode crescer.** `pagamentos`, `mapa_imposto`,
`base_tributavel`, … derivam-se inteiras das vendas emitidas da sessão, que
ficam no Mongo para sempre e já não podem mudar; gravar uma cópia é criar uma
segunda verdade para amanhã alguém encontrar diferente da primeira. E, pior:
nenhum turno antigo pode passar a ter campos que não tinha. Movê-las para o
`$set` era uma mutação que a suite inteira não via.

**2. O que se DEVOLVE não pode encolher.** A resposta do Z enumera os campos do
resumo um a um, e o Ponto de Caixa devolve o resumo inteiro. Um campo NOVO do
resumo — lido pelo ecrã, que é o mesmo componente nos dois — entrava no Ponto de
Caixa e ficava de fora do Z, em silêncio: a operadora via o número às 15h e não
o via no papel que assinou às 23h. Foi a segunda mutação que sobreviveu.
"""
from faturacao import caixa as caixa_mod
from faturacao.caixa import (
    PedidoFecharCaixa,
    _resumo_do_turno,
    fechar_caixa,
)
from faturacao.db import COLECOES

from .test_venda import (  # noqa: F401
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _sessao,
    _venda,
)

# O que o `$set` do fecho grava, e mais nada. Um turno de 2026 não pode ganhar
# campos que não tinha em 2026.
_O_QUE_SE_GRAVA = {
    "estado", "fechada_por", "fechada_em", "contado", "esperado", "diferenca",
    "contas_abertas",
}


def _venda_emitida(**over):
    v = _venda(
        id="paga", estado="emitida",
        linhas=[_linha(id="l1", produto_preco=10.20, produto_tax_id="INT"),
                _linha(id="l2", produto_preco=1.15, produto_tax_id="NOR")],
        criada_em="2026-08-21T10:00:00+00:00",
    )
    v["pagamentos"] = [{
        "tipo_pagamento_id": "tp-1", "nome": "Dinheiro", "tipo_fiscal": "DH",
        "valor": 11.35,
    }]
    v.update(over)
    return v


def _monta(monkeypatch, vendas=None):
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao()],
        vendas=vendas if vendas is not None else [_venda_emitida()],
        produtos=[_produto()], refs=[],
    )
    db[COLECOES["movimentos_caixa"]]  # `DbFalsa.__getitem__` cria-a vazia
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    async def _sem_vendus(_db, _sessao, _valor):
        return {"nao_verificado": "desligado no teste"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", _sem_vendus)
    return db


def test_o_que_assina_o_z_nao_ganha_campos(monkeypatch):
    """A mutação que sobreviveu: mover o mapa de imposto (ou o desdobramento
    por pagamento) para o `$set` que assina o Z."""
    db = _monta(monkeypatch)

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=61.35), operador=_operador()))

    sessao = db[COLECOES["sessoes_caixa"]]._documentos[0]
    gravados = set(sessao) - set(_sessao())
    assert gravados == _O_QUE_SE_GRAVA - set(_sessao()) | {"fecho_iniciado_em"}, (
        "O que o fecho GRAVA na sessão mudou: %s. Estes números derivam-se "
        "inteiros das vendas emitidas do turno — gravar uma cópia é criar uma "
        "segunda verdade, e um turno antigo passa a ter campos que não tinha."
        % sorted(gravados)
    )


def test_tudo_o_que_o_resumo_calcula_chega_ao_z_assinado(monkeypatch):
    """A outra mutação: um campo novo do resumo, lido pelo ecrã, esquecido na
    resposta do Z.

    O `PosResumoDoTurno` é o MESMO componente no Ponto de Caixa (que devolve o
    resumo inteiro) e no Z (que enumera os campos um a um). Um campo que só
    chegue a um dos dois é um número que a operadora vê às 15h e não encontra
    no papel que assina às 23h."""
    _monta(monkeypatch)

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=61.35), operador=_operador()))

    resumo = _resumo_do_turno(_sessao(), [], [_venda_emitida()])
    # `fundo` sai na mesma, com o nome que o Z sempre lhe deu.
    em_falta = set(resumo) - set(z)
    assert not em_falta, (
        "O resumo do turno calcula %s e a resposta do Z não o traz. O Ponto de "
        "Caixa devolve o resumo inteiro e o Z enumera campo a campo: o que se "
        "acrescenta a um tem de chegar ao outro." % sorted(em_falta)
    )


def test_o_z_e_o_ponto_de_caixa_dao_os_mesmos_numeros(monkeypatch):
    """A razão de haver uma só `_resumo_do_turno`, posta a correr: o `esperado`
    das 15h e o das 23h são o mesmo cálculo."""
    _monta(monkeypatch)

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=61.35), operador=_operador()))
    resumo = _resumo_do_turno(_sessao(), [], [_venda_emitida()])

    for campo in ("esperado", "vendas_dinheiro", "pagamentos", "mapa_imposto",
                  "base_tributavel", "iva_total", "total_faturado",
                  "quantos_documentos", "pagamentos_por_registar"):
        assert z[campo] == resumo[campo], campo


# --- O dinheiro facturado que não tem pagamento nenhum por baixo ---------------


def test_uma_venda_emitida_sem_pagamentos_nao_desaparece_da_coluna(monkeypatch):
    """**1,15 € desapareciam sem uma palavra.** Uma venda emitida SEM
    `pagamentos` não entra em linha nenhuma de `por_tipo_de_pagamento`: a
    coluna "Por tipo de pagamento" somava 10,20 € debaixo de um "Total cobrado
    11,35 €", e o ecrã não pode somar a coluna para dar por isso (a aritmética
    de dinheiro é do servidor).

    O que falta passa a ter nome e um euro — somado aqui, nunca no browser."""
    sem_pagamentos = _venda_emitida(id="sem-pagamento")
    sem_pagamentos.pop("pagamentos")
    _monta(monkeypatch, vendas=[sem_pagamentos])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["pagamentos"] == []
    assert z["total_faturado"] == 11.35
    assert z["pagamentos_por_registar"] == 11.35, (
        "A coluna dos pagamentos voltou a não somar o rodapé — e sem uma "
        "palavra que o dissesse.")


def test_com_tudo_cobrado_nao_ha_nada_por_registar(monkeypatch):
    """O caso normal, que é toda a gente: a coluna soma o rodapé e o campo sai
    a 0,00 — presente na mesma, para o ecrã não ter de adivinhar se a ausência
    quer dizer "está tudo cobrado" ou "esta versão não sabe responder"."""
    _monta(monkeypatch)

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=61.35), operador=_operador()))

    assert z["pagamentos_por_registar"] == 0.0
    assert sum(l["total"] for l in z["pagamentos"]) == z["total_faturado"]


def test_um_pagamento_a_menos_do_que_o_documento_tambem_aparece(monkeypatch):
    """Metade em dinheiro e a outra metade por registar — os valores escolhidos
    entre os que EXPÕEM a diferença (11,35 − 10,20 = 1,15)."""
    parcial = _venda_emitida(id="parcial")
    parcial["pagamentos"] = [{
        "tipo_pagamento_id": "tp-1", "nome": "Dinheiro", "tipo_fiscal": "DH",
        "valor": 10.20,
    }]
    _monta(monkeypatch, vendas=[parcial])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["pagamentos_por_registar"] == 1.15
