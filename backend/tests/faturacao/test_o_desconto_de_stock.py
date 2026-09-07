"""**O stock a descer quando a fatura sai** — Fase 2, e as maneiras de a estragar.

O que este ficheiro prende, por ordem de gravidade:

1. **nada aqui pode impedir uma fatura de sair.** Os `except` da rota
   `finalizar` nomeiam as excepções uma a uma e nenhuma é genérica: uma
   excepção que suba do desconto devolve 500 ao balcão com a fatura JÁ
   entregue à AT — e o ecrã lê um 500 como «não saiu nada» e convida a
   operadora a emitir outra vez;

2. **cobre TODOS os caminhos que acabam em «emitida»**, e não só o feliz. O
   sítio óbvio (ao lado do `enfileirar_venda_emitida`, que põe o talão na
   fila) tem um só chamador, dentro da rota `finalizar`, e deixava sem stock —
   em silêncio — toda a venda salva pela reconciliação de reservas presas. Foi
   um erro meu numa versão anterior deste trabalho, apanhado numa revisão;

3. **não desconta duas vezes.** `_ligar_venda_ao_documento` corre mais do que
   uma vez para a mesma venda (o retry que reencontra o documento por chave
   duplicada, e a reconciliação a passar por cima de uma emissão em voo) e o
   `POST /integ/movimento` não aceita chave de idempotência nenhuma;

4. **manda o número na unidade do ARTIGO.** O movimento não leva unidade: 30 g
   de um artigo contado em quilos são `0.03`, e mandar `30` esvazia o armazém.

Nenhum teste deste ficheiro toca na rede: `ESTOQUE_API_URL` cai por omissão na
produção do Estoque, e um teste distraído descontava stock a sério nas 5 lojas.
"""
import asyncio
import re
from pathlib import Path

import pytest

from faturacao import estoque_saida as saida_mod
from faturacao import fiscal as fiscal_mod
from faturacao.estoque_saida import (
    descontar_venda,
    desconto_ligado,
    saidas_de_uma_venda,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplos ------------------------------------------------------------------


class _Resultado:
    def __init__(self, matched, modified):
        self.matched_count = matched
        self.modified_count = modified


class _Coleccao:
    """Guarda documentos por id e responde como o Motor — incluindo o
    `modified_count`, que é o que distingue quem ganhou a reclamação."""

    def __init__(self, docs=None):
        self.docs = {d["id"]: dict(d) for d in (docs or [])}
        self.escritas = []

    async def find_one(self, filtro, projecao=None):
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def update_one(self, filtro, atualizacao):
        self.escritas.append((filtro, atualizacao))
        alvo = None
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filtro.items()):
                alvo = doc
                break
        if alvo is None:
            return _Resultado(0, 0)
        antes = dict(alvo)
        alvo.update(atualizacao.get("$set") or {})
        return _Resultado(1, 0 if antes == alvo else 1)


class _Db:
    def __init__(self, **colecoes):
        self._c = colecoes

    def __getitem__(self, nome):
        return self._c.setdefault(nome, _Coleccao())


class _EstoqueFalso:
    """Substitui o cliente do Estoque. Regista o que lhe pediram."""

    def __init__(self, rebenta=False):
        self.chamadas = []
        self.rebenta = rebenta

    async def __call__(self, unidade_id, produto_id, quantidade, actor, timeout=None):
        self.chamadas.append({
            "unidade_id": unidade_id, "produto_id": produto_id,
            "quantidade": quantidade, "actor": actor,
        })
        if self.rebenta:
            raise RuntimeError("O Estoque respondeu 502 a uma saída: sem detalhe")
        return {}


def _opcao(artigo="est-granola", consumo=30, unidade="g", medida="kg"):
    return {
        "id": "o-gra", "nome": "Granola", "preco": 0.8,
        "consumo": consumo, "consumo_unidade": unidade,
        "estoque_produto_id": artigo, "estoque_unidade_medida": medida,
    }


def _venda(opcoes=None, quantidade=1, **over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "estado": "emitida",
        # `opcoes is None` e nao `or`: uma lista VAZIA e uma resposta legitima
        # («esta linha nao leva nada») e o `or` trocava-a pelo valor por omissao.
        "linhas": [{"quantidade": quantidade,
                    "opcoes": [_opcao()] if opcoes is None else opcoes}],
    }
    v.update(over)
    return v


def _monta(monkeypatch, venda=None, loja=None, ligado=True, estoque=None):
    db = _Db(**{
        "fat_vendas": _Coleccao([venda or _venda()]),
        "fat_lojas": _Coleccao([loja if loja is not None else
                                {"id": "loja-1", "nome": "Belém",
                                 "estoque_unidade_id": "unid-belem"}]),
        "fat_definicoes": _Coleccao(
            [{"id": "desconto_stock", "ativo": True}] if ligado else []),
    })
    falso = estoque or _EstoqueFalso()
    import estoque_cliente
    monkeypatch.setattr(estoque_cliente, "descontar_saida", falso)
    return db, falso


# --- O interruptor ------------------------------------------------------------


def test_sem_definicao_nenhuma_o_desconto_esta_DESLIGADO():
    """Ausente = desligado, ao contrário do relatório diário (que devolve
    activo quando não há documento). Aquele manda um email a mais; este mexe
    no stock de cinco lojas — ligar-se sozinho no dia do deploy é a pior
    maneira de estrear isto."""
    db = _Db(fat_definicoes=_Coleccao([]))
    assert _corre(desconto_ligado(db)) is False


def test_o_interruptor_desligado_nao_telefona_ao_estoque(monkeypatch):
    db, estoque = _monta(monkeypatch, ligado=False)
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "desligado"
    assert estoque.chamadas == []


# --- A conta que vai para o Estoque ------------------------------------------


def test_a_quantidade_vai_na_unidade_do_ARTIGO_e_nao_na_da_ficha(monkeypatch):
    """O movimento não leva unidade nenhuma: o número é interpretado do lado
    de lá, na unidade do artigo. Mandar «30» para um artigo contado em quilos
    tira 30 kg de granola por dose — mil vezes a mais, sem um erro pelo
    caminho."""
    db, estoque = _monta(monkeypatch)
    _corre(descontar_venda(db, "venda-1"))
    assert len(estoque.chamadas) == 1
    assert estoque.chamadas[0]["quantidade"] == 0.03, "mandou gramas em vez de quilos"
    assert estoque.chamadas[0]["produto_id"] == "est-granola"
    assert estoque.chamadas[0]["unidade_id"] == "unid-belem"


def test_duas_doses_do_mesmo_artigo_sao_UMA_chamada(monkeypatch):
    """Um copo com três toppings do mesmo artigo é uma saída, não três
    chamadas de rede com a operadora à espera."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[_opcao(), _opcao()]))
    _corre(descontar_venda(db, "venda-1"))
    assert len(estoque.chamadas) == 1
    assert estoque.chamadas[0]["quantidade"] == 0.06


def test_a_quantidade_da_linha_multiplica_a_saida(monkeypatch):
    db, estoque = _monta(monkeypatch, venda=_venda(quantidade=2))
    _corre(descontar_venda(db, "venda-1"))
    assert estoque.chamadas[0]["quantidade"] == 0.06


def test_uma_conta_dividida_por_tres_nao_desconta_a_triplicar():
    """As três partes trazem a opção INTEIRA, cada uma com um terço da
    quantidade. Somar por opção sem multiplicar triplicava a granola."""
    partes = {"id": "v", "linhas": [
        {"quantidade": 0.3333, "opcoes": [_opcao()]},
        {"quantidade": 0.3333, "opcoes": [_opcao()]},
        {"quantidade": 0.3334, "opcoes": [_opcao()]},
    ]}
    saidas = saidas_de_uma_venda(partes)
    assert len(saidas) == 1
    assert saidas[0]["quantidade"] == 0.03


def test_uma_gramagem_SEM_artigo_do_estoque_nao_desconta_de_lado_nenhum(monkeypatch):
    """Conta no relatório (pelo nome) mas não tem de onde sair."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[_opcao(artigo=None, medida=None)]))
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "nada-a-descontar"
    assert estoque.chamadas == []


def test_um_consumo_de_ZERO_nao_gera_movimento(monkeypatch):
    """O palito conta-se como dose no relatório, mas um movimento de zero só
    faz lixo no histórico do Estoque."""
    db, estoque = _monta(
        monkeypatch, venda=_venda(opcoes=[_opcao(consumo=0, unidade="un", medida="un")]))
    _corre(descontar_venda(db, "venda-1"))
    assert estoque.chamadas == []


# --- Não descontar duas vezes -------------------------------------------------


def test_a_segunda_chamada_para_a_MESMA_venda_nao_desconta_outra_vez(monkeypatch):
    """`_ligar_venda_ao_documento` corre mais do que uma vez para a mesma
    venda — o retry que reencontra o documento por chave duplicada, e a
    reconciliação a passar por cima de uma emissão em voo. E o Estoque não
    aceita chave de idempotência nenhuma."""
    db, estoque = _monta(monkeypatch)
    primeira = _corre(descontar_venda(db, "venda-1"))
    segunda = _corre(descontar_venda(db, "venda-1"))
    assert primeira["estado"] == "descontado"
    assert segunda["estado"] == "ja-descontado"
    assert len(estoque.chamadas) == 1, "descontou o mesmo copo duas vezes"


def test_DUAS_chamadas_ao_MESMO_TEMPO_descontam_uma_so_vez(monkeypatch):
    """O teste que a reclamação atómica existe para passar — e que o teste
    sequencial aqui em cima NÃO prova.

    Descobri-o por mutação: com `_reclama_a_venda` a devolver sempre `True`,
    o caso sequencial continuava verde, porque a leitura no início da segunda
    chamada já vê a marca da primeira. Essa verificação é um atalho barato,
    não é a defesa. A defesa é para quando as duas chamadas LEEM antes de
    qualquer uma ESCREVER — que é exactamente o que acontece quando a
    reconciliação de reservas presas passa por cima de uma emissão em voo.

    Aqui as duas leituras acontecem primeiro (o duplo cede o controlo no
    `find_one`), as duas passam pelo atalho, e só a reclamação as separa."""
    db, estoque = _monta(monkeypatch)

    leitura_original = db["fat_vendas"].find_one

    async def _cede(filtro, projecao=None):
        # Cede o controlo DEPOIS de ler: dá à outra chamada a oportunidade de
        # ler o mesmo estado antes de qualquer uma escrever.
        resultado = await leitura_original(filtro, projecao)
        await asyncio.sleep(0)
        return resultado

    db["fat_vendas"].find_one = _cede

    async def _as_duas():
        return await asyncio.gather(
            descontar_venda(db, "venda-1"), descontar_venda(db, "venda-1"))

    resultados = _corre(_as_duas())
    estados = sorted(r["estado"] for r in resultados)
    assert estados == ["descontado", "ja-descontado"], estados
    assert len(estoque.chamadas) == 1, (
        "as duas chamadas descontaram: %s" % estoque.chamadas)


def test_a_marca_e_escrita_ANTES_de_telefonar(monkeypatch):
    """Se o processo morrer a meio, o erro tem de ser NÃO descontar — visível
    no relatório e recuperável à mão — e nunca descontar a dobrar, que é
    invisível e só aparece na contagem do mês."""
    ordem = []
    db, _ = _monta(monkeypatch, estoque=None)

    class _Regista(_EstoqueFalso):
        async def __call__(self, **kw):
            ordem.append("telefonou")
            return await super().__call__(**kw)

    import estoque_cliente
    monkeypatch.setattr(estoque_cliente, "descontar_saida", _Regista())
    escrita_original = db["fat_vendas"].update_one

    async def _espia(filtro, atualizacao):
        if "stock_descontado_em" in (atualizacao.get("$set") or {}):
            ordem.append("marcou")
        return await escrita_original(filtro, atualizacao)

    db["fat_vendas"].update_one = _espia
    _corre(descontar_venda(db, "venda-1"))
    assert ordem == ["marcou", "telefonou"], ordem


def test_uma_venda_SEM_nada_a_descontar_nao_fica_marcada(monkeypatch):
    """Senão, no dia em que as gramagens fossem escritas, uma reconciliação já
    não apanhava a venda — ficava marcada como descontada sem nunca o ter
    sido."""
    db, _ = _monta(monkeypatch, venda=_venda(opcoes=[]))
    _corre(descontar_venda(db, "venda-1"))
    gravada = _corre(db["fat_vendas"].find_one({"id": "venda-1"}))
    assert gravada.get("stock_descontado_em") is None


# --- A loja por ligar ---------------------------------------------------------


def test_uma_loja_sem_unidade_do_estoque_nao_desconta_e_nao_rebenta(monkeypatch):
    db, estoque = _monta(monkeypatch, loja={"id": "loja-1", "nome": "Belém"})
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "loja-sem-unidade"
    assert estoque.chamadas == []


def test_uma_loja_por_ligar_nao_fica_marcada_como_descontada(monkeypatch):
    """Para o dia em que o dono ligar a loja, a venda ainda poder ser
    recuperada — a marca é uma promessa de que o stock desceu."""
    db, _ = _monta(monkeypatch, loja={"id": "loja-1", "nome": "Belém"})
    _corre(descontar_venda(db, "venda-1"))
    gravada = _corre(db["fat_vendas"].find_one({"id": "venda-1"}))
    assert gravada.get("stock_descontado_em") is None


# --- Nada disto pode parar uma fatura -----------------------------------------


def test_o_estoque_em_baixo_NAO_levanta_para_quem_chamou(monkeypatch):
    """A regra que manda sobre todas as outras."""
    db, estoque = _monta(monkeypatch, estoque=_EstoqueFalso(rebenta=True))
    resultado = _corre(descontar_venda(db, "venda-1"))
    assert resultado["estado"] == "descontado"
    assert resultado["falhadas"] == 1


def test_o_desconto_a_rebentar_nao_impede_a_venda_de_ficar_EMITIDA(monkeypatch):
    """O teste do enganche, e o que prende a regra de ouro: mesmo que tudo no
    desconto exploda, `_ligar_venda_ao_documento` tem de acabar em silêncio e
    a venda tem de ficar emitida."""
    vendas = _Coleccao([{"id": "venda-1", "estado": "aberta", "linhas": []}])
    db = _Db(fat_vendas=vendas, fat_refs_fiscais=_Coleccao([]))

    async def _explode(*a, **kw):
        raise RuntimeError("tudo mal")

    monkeypatch.setattr(saida_mod, "descontar_venda", _explode)
    _corre(fiscal_mod._ligar_venda_ao_documento(
        db, "ext-1", "venda-1", {"id": "doc-1"}, reserva_id="ref-1"))

    gravada = _corre(vendas.find_one({"id": "venda-1"}))
    assert gravada["estado"] == "emitida"
    assert gravada["documento_id"] == "doc-1"


def test_o_enganche_dispara_o_desconto(monkeypatch):
    """E o contrário: no caminho normal, o desconto é mesmo chamado."""
    chamadas = []
    vendas = _Coleccao([{"id": "venda-1", "estado": "aberta", "linhas": []}])
    db = _Db(fat_vendas=vendas, fat_refs_fiscais=_Coleccao([]))

    async def _regista(db_, venda_id, **kw):
        chamadas.append(venda_id)
        return {"estado": "desligado"}

    monkeypatch.setattr(saida_mod, "descontar_venda", _regista)
    _corre(fiscal_mod._ligar_venda_ao_documento(
        db, "ext-1", "venda-1", {"id": "doc-1"}, reserva_id="ref-1"))
    assert chamadas == ["venda-1"]


# --- O guarda estrutural: o enganche continua a ser o ponto ÚNICO -------------


_FATURACAO = Path(__file__).resolve().parents[2] / "faturacao"


def test_so_ha_UM_sitio_a_marcar_uma_venda_como_emitida():
    """O desconto está pendurado em `_ligar_venda_ao_documento` porque é a
    única escrita de `estado: "emitida"` numa VENDA em todo o módulo. No dia
    em que alguém acrescentar uma segunda, o desconto deixa de cobrir esse
    caminho — em silêncio, que é como a primeira versão disto já falhou.

    Este teste é o alarme: se ficar vermelho, ou se pendura o desconto também
    no sítio novo, ou se faz o sítio novo passar por aqui.

    **Afirma UMA escrita em `fiscal.py`, e já não o número da linha.** Prender
    o número fazia isto ficar vermelho a cada edição ACIMA dela — e a resposta
    a um alarme desses é bater o número sem pensar, que é precisamente o
    hábito que desliga o alarme a sério. A propriedade é «uma só», não «na
    linha 1315»."""
    escritas = []
    for ficheiro in sorted(_FATURACAO.glob("*.py")):
        linhas = ficheiro.read_text(encoding="utf-8").splitlines()
        for numero, linha in enumerate(linhas, 1):
            if not re.search(r'"estado":\s*"emitida"', linha):
                continue
            # Só uma ESCRITA conta, e só na colecção das VENDAS: as outras
            # ocorrências são filtros de leitura (a caixa a somar as vendas
            # emitidas do turno) e uma escrita noutra colecção (a nota de
            # crédito). Nenhuma delas passa uma venda a emitida.
            volta_atras = "\n".join(linhas[max(0, numero - 6):numero])
            if "$set" in volta_atras and 'COLECOES["vendas"]' in volta_atras:
                escritas.append("%s:%d" % (ficheiro.name, numero))
    assert len(escritas) == 1, escritas
    assert escritas[0].startswith("fiscal.py:"), escritas


def test_o_enganche_esta_dentro_de_um_except_generico():
    """Um `except` que nomeasse excepções deixava passar as outras — e uma
    excepção que suba daqui devolve 500 ao balcão com a fatura já entregue à
    AT."""
    texto = (_FATURACAO / "fiscal.py").read_text(encoding="utf-8")
    bloco = texto[texto.index("from .estoque_saida import descontar_venda"):]
    bloco = bloco[:bloco.index("\n\nasync def")]
    assert "except Exception" in bloco, bloco[:400]


def test_nenhum_teste_desta_fase_fala_com_o_estoque_a_serio():
    """`ESTOQUE_API_URL` cai por omissão na PRODUÇÃO do Estoque. Um teste que
    não substitua o cliente desconta stock a sério nas cinco lojas."""
    import estoque_cliente
    assert estoque_cliente.ESTOQUE_API_URL.startswith("http")
    with pytest.raises(Exception):
        # Sem chave de serviço, nem sequer chega a sair da máquina.
        estoque_cliente.cabecalhos()


# --- A ponte da loja não se apaga sozinha ------------------------------------


def test_gravar_uma_loja_sem_falar_da_unidade_do_estoque_nao_a_desliga(monkeypatch):
    """O sintoma deste defeito é o pior de todos: o stock PARA de descer e não
    aparece erro nenhum.

    O PUT das lojas faz `$set` do modelo inteiro e o campo tem `= None` por
    omissão — um pedido que não o repita punha-o a nulo. A defesa existia, mas
    dentro do browser (o ecrã reenvia os campos, com a cicatriz escrita ao
    lado), e uma defesa que vive no Chrome desliga-se com um curl."""
    from faturacao import lojas as lojas_mod
    from faturacao.lojas import LojaEntrada, editar_loja

    gravada = {"id": "loja-1", "nome": "Belém", "estoque_unidade_id": "unid-belem",
               "empresa_id": "emp-1", "rh_location_id": "rh-1"}
    coleccao = _Coleccao([gravada])
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: _Db(fat_lojas=coleccao))

    _corre(editar_loja("loja-1", LojaEntrada(nome="Belém — Rua Nova"), _={}))

    depois = _corre(coleccao.find_one({"id": "loja-1"}))
    assert depois["estoque_unidade_id"] == "unid-belem"
    assert depois["empresa_id"] == "emp-1", "e os outros dois também não"
    assert depois["rh_location_id"] == "rh-1"
    assert depois["nome"] == "Belém — Rua Nova", "o que veio no pedido tem de mudar"


def test_quem_manda_a_unidade_a_NULO_desliga_mesmo_a_loja(monkeypatch):
    """Preservar o que não se fala não pode virar congelar o campo para
    sempre: o ecrã tem de conseguir desligar uma loja."""
    from faturacao import lojas as lojas_mod
    from faturacao.lojas import LojaEntrada, editar_loja

    coleccao = _Coleccao([{"id": "loja-1", "nome": "Belém",
                           "estoque_unidade_id": "unid-belem"}])
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: _Db(fat_lojas=coleccao))

    _corre(editar_loja("loja-1", LojaEntrada(nome="Belém", estoque_unidade_id=None), _={}))

    depois = _corre(coleccao.find_one({"id": "loja-1"}))
    assert depois["estoque_unidade_id"] is None


# --- O aviso das lojas por ligar, do lado do servidor ------------------------
#
# Descoberto por mutação: apagar este filtro deixava os testes de ECRÃ todos
# verdes, porque esses fabricam a resposta do servidor. O ecrã testa o ecrã; a
# conta tem de ser testada aqui.


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, limite):
        return [dict(d) for d in self._docs]


class _ColeccaoComFind(_Coleccao):
    def find(self, filtro, projecao=None):
        return _Cursor(list(self.docs.values()))


def _db_de_lojas(lojas, monkeypatch, ativo=False):
    from faturacao import estoque_saida as mod
    db = _Db(**{
        "fat_definicoes": _Coleccao(
            [{"id": "desconto_stock", "ativo": True}] if ativo else []),
        "fat_lojas": _ColeccaoComFind(lojas),
    })
    monkeypatch.setattr(mod, "obter_db", lambda: db)
    return db


def test_o_servidor_diz_quais_sao_as_lojas_por_ligar(monkeypatch):
    from faturacao.estoque_saida import ler_desconto_stock
    _db_de_lojas([
        {"id": "l1", "nome": "Belém", "ativa": True},
        {"id": "l2", "nome": "Oeiras", "ativa": True, "estoque_unidade_id": "u2"},
    ], monkeypatch)
    resposta = _corre(ler_desconto_stock(_={}))
    assert [l["nome"] for l in resposta["lojas_por_ligar"]] == ["Belém"]
    assert resposta["ativo"] is False


def test_uma_loja_FECHADA_nao_entra_no_aviso(monkeypatch):
    """Uma loja fechada não vende. Enchia o aviso de nomes que não importam
    até ninguém o ler."""
    from faturacao.estoque_saida import ler_desconto_stock
    _db_de_lojas([{"id": "l1", "nome": "Loja antiga", "ativa": False}], monkeypatch)
    assert _corre(ler_desconto_stock(_={}))["lojas_por_ligar"] == []


# --- A unidade do artigo, lida ONDE O DINHEIRO ESTÁ --------------------------
#
# A validação do catálogo só corre quando alguém grava um grupo. Tudo o que
# ficou gravado na Fase 1 tem artigo e não tem a unidade dele, e um artigo pode
# mudar de unidade no Estoque depois do carimbo. Sem ler isto no desconto, a
# defesa contra o factor de mil era uma frase numa docstring.


def test_uma_ficha_da_FASE_1_sem_a_unidade_do_artigo_NAO_desconta(monkeypatch):
    """Nunca desconta errado. Não desconta nada, e diz porquê no registo."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[_opcao(medida=None)]))
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "nada-a-descontar"
    assert estoque.chamadas == []


def test_uma_ficha_em_GRAMAS_ligada_a_um_artigo_contado_em_UNIDADES_nao_desconta(monkeypatch):
    """O erro que custa mais: 30 g contra um artigo em pacotes mandaria 0,03
    pacotes por copo — um subdesconto de trinta vezes, e o stock nunca desce
    até a ruptura chegar sem aviso. Ao contrário, mandaria quilos onde são
    unidades."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[_opcao(medida="un")]))
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "nada-a-descontar"
    assert estoque.chamadas == []


def test_um_artigo_contado_em_CAIXAS_nao_desconta(monkeypatch):
    """Uma caixa de quê, com quantos? Não há conversão, e inventar uma era
    pior do que não descontar."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[_opcao(medida="caixa")]))
    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "nada-a-descontar"
    assert estoque.chamadas == []


def test_o_mesmo_artigo_em_familias_diferentes_nao_se_soma(monkeypatch):
    """Somar quilos com unidades no mesmo artigo dava um número que não quer
    dizer nada. O relatório já os separa; o desconto tem de os separar
    também — e aqui a família que não bate com a do artigo cai fora."""
    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[
        _opcao(consumo=30, unidade="g", medida="kg"),
        _opcao(consumo=2, unidade="un", medida="kg"),
    ]))
    _corre(descontar_venda(db, "venda-1"))
    assert len(estoque.chamadas) == 1
    assert estoque.chamadas[0]["quantidade"] == 0.03, (
        "somou unidades com quilos: %s" % estoque.chamadas)


def test_uma_venda_ANTERIOR_a_ligar_o_interruptor_nao_desconta(monkeypatch):
    """Uma reconciliação de reserva presa pode salvar hoje uma venda de há
    semanas. Sem esta guarda, ligar o interruptor fazia sair do armazém um
    copo que já tinha saído — e o stock ficava a menos sem se perceber
    porquê."""
    from faturacao import estoque_saida as mod
    db = _Db(**{
        "fat_vendas": _Coleccao([_venda(criada_em="2026-08-01T10:00:00+00:00")]),
        "fat_lojas": _Coleccao([{"id": "loja-1", "nome": "Belém",
                                 "estoque_unidade_id": "unid-belem"}]),
        "fat_definicoes": _Coleccao([{"id": "desconto_stock", "ativo": True,
                                      "mudado_em": "2026-09-06T00:00:00+00:00"}]),
    })
    estoque = _EstoqueFalso()
    import estoque_cliente
    monkeypatch.setattr(estoque_cliente, "descontar_saida", estoque)
    monkeypatch.setattr(mod, "obter_db", lambda: db)

    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "anterior-ao-interruptor"
    assert estoque.chamadas == []


def test_uma_venda_POSTERIOR_a_ligar_o_interruptor_desconta(monkeypatch):
    """A outra metade: a guarda da data não pode travar o dia-a-dia."""
    from faturacao import estoque_saida as mod
    db = _Db(**{
        "fat_vendas": _Coleccao([_venda(criada_em="2026-09-06T11:00:00+00:00")]),
        "fat_lojas": _Coleccao([{"id": "loja-1", "nome": "Belém",
                                 "estoque_unidade_id": "unid-belem"}]),
        "fat_definicoes": _Coleccao([{"id": "desconto_stock", "ativo": True,
                                      "mudado_em": "2026-09-06T00:00:00+00:00"}]),
    })
    estoque = _EstoqueFalso()
    import estoque_cliente
    monkeypatch.setattr(estoque_cliente, "descontar_saida", estoque)
    monkeypatch.setattr(mod, "obter_db", lambda: db)

    assert _corre(descontar_venda(db, "venda-1"))["estado"] == "descontado"
    assert len(estoque.chamadas) == 1


def test_as_saidas_de_uma_venda_correm_em_PARALELO(monkeypatch):
    """O tecto de espera é por chamada. Em fila, um copo com quatro artigos
    ligados fazia a operadora esperar quatro vezes quatro segundos com o
    cliente à frente."""
    a_correr, maximo = [0], [0]

    class _Lento(_EstoqueFalso):
        async def __call__(self, **kw):
            a_correr[0] += 1
            maximo[0] = max(maximo[0], a_correr[0])
            await asyncio.sleep(0)
            a_correr[0] -= 1
            return await super().__call__(**kw)

    db, estoque = _monta(monkeypatch, venda=_venda(opcoes=[
        _opcao(artigo="est-a"), _opcao(artigo="est-b"), _opcao(artigo="est-c"),
    ]), estoque=_Lento())
    _corre(descontar_venda(db, "venda-1"))
    assert len(estoque.chamadas) == 3
    assert maximo[0] > 1, "as saídas correram uma a uma"
