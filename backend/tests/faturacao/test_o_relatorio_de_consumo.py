"""**O que saiu do armazém** — a soma das gramagens, e as três maneiras de a
errar.

Este relatório é o que dá sentido às gramagens escritas nas personalizações:
é contra ele que se confere uma contagem do armazém, e é ele que diz se a
gramagem escrita bate com a granola que desaparece. Por isso a soma tem de
estar certa antes de haver desconto automático nenhum — uma gramagem errada
com o desconto ligado faz o stock mentir com autoridade.

As três armadilhas, todas presas aqui:

1. uma DOSE é uma entrada repetida na lista de opções, não uma quantidade —
   contar opções distintas perdia metade da granola;
2. a quantidade da linha é FRACCIONÁRIA (uma conta dividida por três grava
   0,3337 e as opções vão inteiras para cada parte) — somar por opção sem
   multiplicar triplicava o consumo;
3. as vendas da APP não trazem opções nenhumas — somá-las como zero dizia «a
   app não gasta granola», que é falso e parece verdade.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import consumo as consumo_mod
from faturacao import router as router_do_modulo
from faturacao.consumo import agregar_consumo, consumo_de_uma_venda, relatorio_de_consumo

from .test_catalogo import ColeccaoFalsa, DbFalsa


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _opcao(nome="Granola", consumo=30, unidade="g", estoque="est-granola", **over):
    o = {
        "id": "o-gra", "nome": nome, "preco": 0.8,
        "consumo": consumo, "consumo_unidade": unidade, "estoque_produto_id": estoque,
    }
    o.update(over)
    return o


def _venda(opcoes, quantidade=1):
    return {"id": "venda-1", "linhas": [{"quantidade": quantidade, "opcoes": opcoes}]}


def _doc(venda_id="venda-1", origem=None):
    d = {"venda_id": venda_id}
    if origem:
        d["origem"] = origem
    return d


def _uma(agregado):
    assert len(agregado["linhas"]) == 1, agregado["linhas"]
    return agregado["linhas"][0]


# --- O caminho da rota --------------------------------------------------------


def test_a_rota_do_consumo_esta_onde_o_ecra_a_vai_procurar():
    """Pergunta-se ao router, e não ao ficheiro. Afirmar o endereço que o
    código escreve nunca apanha um prefixo errado — e um prefixo errado já
    matou o POS três vezes neste repositório.

    E há aqui um cruzamento a sério: `/relatorios/{dimensao}` tem um parâmetro
    que come tudo o que lhe passe à frente. Um `/relatorios/consumo` não seria
    esta rota — seria aquela, a responder «Relatório desconhecido: consumo»."""
    caminhos = {r.path for r in router_do_modulo.routes}
    assert "/api/faturacao/consumo" in caminhos, sorted(caminhos)


# --- As três armadilhas -------------------------------------------------------


def test_uma_dose_DUPLA_conta_duas_vezes():
    """Cada toque na Granola acrescenta OUTRO dicionário igual à lista. Quem
    agrupasse por id — ou fizesse um `set()` — via uma dose onde há duas."""
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([_opcao(), _opcao()])})
    linha = _uma(agregado)
    assert linha["doses"] == 2
    assert linha["quantidade"] == 0.06, "duas doses de 30 g são 60 g"


def test_a_quantidade_da_linha_MULTIPLICA_o_consumo():
    """Dois açaís iguais com granola gastam o dobro da granola."""
    linha = _uma(agregar_consumo([_doc()], {"venda-1": _venda([_opcao()], quantidade=2)}))
    assert linha["quantidade"] == 0.06


def test_uma_conta_DIVIDIDA_por_tres_nao_triplica_o_consumo():
    """O caso que dói. `venda.dividir` grava quantidades como 0,3337 e copia
    as opções INTEIRAS para cada parte. Somar por opção sem multiplicar pela
    quantidade da parte dava 3× a granola de um açaí que foi um só."""
    partes = {
        "venda-1": {"id": "venda-1", "linhas": [
            {"quantidade": 0.3333, "opcoes": [_opcao()]},
            {"quantidade": 0.3333, "opcoes": [_opcao()]},
            {"quantidade": 0.3334, "opcoes": [_opcao()]},
        ]},
    }
    linha = _uma(agregar_consumo([_doc()], partes))
    assert linha["quantidade"] == 0.03, "a conta dividida gastou UM açaí de granola"


def test_as_vendas_da_APP_contam_se_a_parte_e_dizem_se():
    """A app não manda os toppings ao Vendus, portanto o documento não os tem
    e não os pode ter. Somá-los como zero dizia «a app não gasta granola» —
    falso, e com ar de verdade. Contam-se e diz-se quantos são."""
    agregado = agregar_consumo(
        [_doc(), _doc(venda_id=None, origem="app"), _doc(venda_id=None, origem="app")],
        {"venda-1": _venda([_opcao()])},
    )
    assert agregado["documentos_do_balcao"] == 1
    assert agregado["documentos_da_app"] == 2
    assert agregado["documentos_por_medir"] == 2
    assert _uma(agregado)["quantidade"] == 0.03


# --- As unidades --------------------------------------------------------------


def test_gramas_e_quilos_do_mesmo_artigo_somam_na_MESMA_linha():
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(consumo=500, unidade="g"),
        _opcao(consumo=1, unidade="kg"),
    ])})
    linha = _uma(agregado)
    assert linha["quantidade"] == 1.5
    assert linha["unidade"] == "kg"


def test_gramas_e_UNIDADES_do_mesmo_artigo_NAO_se_misturam():
    """Somar 30 g com 2 unidades dá um número que não quer dizer nada. São
    duas linhas — e a separação também serve de aviso de que alguém escreveu
    a mesma coisa de duas maneiras."""
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(consumo=30, unidade="g"),
        _opcao(consumo=2, unidade="un"),
    ])})
    assert len(agregado["linhas"]) == 2
    assert {l["unidade"] for l in agregado["linhas"]} == {"kg", "un"}


def test_mililitros_somam_em_litros():
    linha = _uma(agregar_consumo(
        [_doc()], {"venda-1": _venda([_opcao(nome="Leite condensado", consumo=20,
                                             unidade="ml", estoque="est-leite")])}))
    assert linha["quantidade"] == 0.02
    assert linha["unidade"] == "L"


# --- O que não entra ----------------------------------------------------------


def test_uma_opcao_SEM_gramagem_nao_entra_na_conta():
    """A esmagadora maioria das opções não tem medição nenhuma, e isso não é
    um erro — é o estado normal enquanto o dono não escreve as fichas."""
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        {"id": "o-nut", "nome": "Nutella", "preco": 1.0},
    ])})
    assert agregado["linhas"] == []
    assert agregado["documentos_do_balcao"] == 1


def test_uma_unidade_que_ninguem_sabe_converter_nao_entra():
    """O carimbo não a deixa passar hoje, mas uma linha gravada antes de uma
    mudança de regras pode trazê-la. Somar «2 colheres» a quilos era pior do
    que não somar."""
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(consumo=2, unidade="colheres"),
    ])})
    assert agregado["linhas"] == []


def test_um_consumo_de_zero_conta_a_dose_e_nao_soma_nada():
    """O palito: gasta-se um por copo e não pesa. A dose conta-se — é ela que
    diz quantos palitos saíram — e o peso somado é zero."""
    linha = _uma(agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(nome="Palito", consumo=0, unidade="un", estoque="est-palito"),
    ])}))
    assert linha["doses"] == 1
    assert linha["quantidade"] == 0


def test_um_documento_sem_venda_do_nosso_lado_nao_rebenta():
    agregado = agregar_consumo([_doc(venda_id="fantasma")], {})
    assert agregado["linhas"] == []
    assert agregado["documentos_por_medir"] == 1


# --- Ainda sem artigo do Estoque ----------------------------------------------


def test_sem_artigo_do_estoque_agrupa_pelo_NOME_e_diz_que_esta_por_ligar():
    """A gramagem escreve-se de uma assentada; ligar cada opção ao artigo é o
    passo seguinte. Entre as duas coisas o relatório tem de continuar a dizer
    alguma coisa — «Granola: 4,2 kg (por ligar)» é útil, uma linha em falta
    não é."""
    linha = _uma(agregar_consumo([_doc()], {"venda-1": _venda([_opcao(estoque=None)])}))
    assert linha["nome"] == "Granola"
    assert linha["estoque_produto_id"] is None
    assert linha["ligado_ao_estoque"] is False


def test_o_mesmo_nome_ligado_e_por_ligar_sao_linhas_diferentes():
    """Não se juntam: uma delas vai descontar do armazém e a outra não, e
    misturá-las escondia exactamente a que falta configurar."""
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(), _opcao(estoque=None),
    ])})
    assert len(agregado["linhas"]) == 2


# --- A ordem e o arredondamento ----------------------------------------------


def test_as_linhas_saem_do_que_mais_gasta_para_o_que_menos():
    agregado = agregar_consumo([_doc()], {"venda-1": _venda([
        _opcao(nome="Granola", consumo=30, estoque="est-gra"),
        _opcao(nome="Polpa", consumo=200, estoque="est-pol"),
    ])})
    assert [l["nome"] for l in agregado["linhas"]] == ["Polpa", "Granola"]


def test_arredonda_so_no_fim_e_nao_a_cada_dose():
    """Uma pitada não sobrevive a ser arredondada sozinha.

    O relatório sai com três casas — é o que se lê. Mas se cada DOSE fosse
    arredondada antes de somar, tudo o que pesa menos de meio grama virava
    zero à entrada: 2500 pitadas de 0,4 g são um grama, e a soma dose-a-dose
    dizia que não saiu nada. Arredonda-se uma vez, no fim.

    Escrito com um valor pequeno de propósito: com 1 g o teste ficava verde
    com as duas semânticas (0,001 kg arredondado a três casas é ele próprio)
    e não distinguia nada — foi assim que nasceu, e a mutação apanhou-o."""
    pitadas = _venda([_opcao(consumo=0.4) for _ in range(2500)])
    linha = _uma(agregar_consumo([_doc()], {"venda-1": pitadas}))
    assert linha["quantidade"] == 1.0, "2500 × 0,4 g = 1 kg"


def test_consumo_de_uma_venda_vazia_nao_rebenta():
    assert consumo_de_uma_venda(None) == []
    assert consumo_de_uma_venda({"linhas": []}) == []


# --- A rota: o que ela pergunta à base ---------------------------------------


def _db_de_documentos(registo, documentos, vendas):
    return DbFalsa({
        "fat_documentos": ColeccaoFalsa(registo, documentos),
        "fat_vendas": ColeccaoFalsa(registo, vendas),
    })


def test_a_rota_deixa_de_fora_o_que_foi_ANULADO(monkeypatch):
    """Mesmo `$ne` dos outros relatórios, e pela mesma razão: o campo é
    AUSENTE em toda a gente (`fiscal._gravar_documento` nunca o grava), e um
    `{"anulado": False}` exigia-o presente e devolvia o relatório vazio. Uma
    fatura anulada no Vendus não gastou granola nenhuma."""
    registo = []
    monkeypatch.setattr(
        consumo_mod, "obter_db",
        lambda: _db_de_documentos(registo, [_doc()], [_venda([_opcao()])]))

    _corre(relatorio_de_consumo(de="2026-09-01", ate="2026-09-07", _={}))

    filtro = next(c for c in registo if c[0] == "find" and "emitido_em" in c[1])[1]
    assert filtro["anulado"] == {"$ne": True}


def test_a_rota_filtra_por_loja_quando_lhe_pedem(monkeypatch):
    registo = []
    monkeypatch.setattr(
        consumo_mod, "obter_db",
        lambda: _db_de_documentos(registo, [_doc()], [_venda([_opcao()])]))

    _corre(relatorio_de_consumo(
        de="2026-09-01", ate="2026-09-07", loja_id="loja-1", _={}))

    filtro = next(c for c in registo if c[0] == "find" and "emitido_em" in c[1])[1]
    assert filtro["loja_id"] == "loja-1"


def test_a_rota_soma_mesmo_o_consumo(monkeypatch):
    registo = []
    monkeypatch.setattr(
        consumo_mod, "obter_db",
        lambda: _db_de_documentos(registo, [_doc()], [_venda([_opcao(), _opcao()])]))

    resposta = _corre(relatorio_de_consumo(de="2026-09-01", ate="2026-09-07", _={}))
    assert resposta["linhas"][0]["quantidade"] == 0.06
    assert resposta["de"] == "2026-09-01"


def test_uma_data_impossivel_devolve_422_e_nao_500(monkeypatch):
    registo = []
    monkeypatch.setattr(
        consumo_mod, "obter_db", lambda: _db_de_documentos(registo, [], []))
    with pytest.raises((HTTPException, ValueError)) as excinfo:
        _corre(relatorio_de_consumo(de="2026-09-30", ate="2026-09-01", _={}))
    if isinstance(excinfo.value, HTTPException):
        assert excinfo.value.status_code == 422
