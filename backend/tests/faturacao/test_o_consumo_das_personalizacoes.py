"""**O que cada personalização gasta** — o degrau que faltava para o stock
descer sozinho com as vendas.

O dono: «quero que as personalizações tenham o valor que aquilo vai no açaí
quando alguém clica na faturação. Para depois eu ter esses dados para ir
tirando do estoque automático à medida que vai saindo pelas vendas.»

Três campos numa opção — quanto (`consumo`), de quê (`consumo_unidade`) e de
QUAL artigo do Estoque (`estoque_produto_id`) — e nada mais nesta fase: aqui
não se desconta stock nenhum, escreve-se o que se há-de descontar. A baixa
automática vem depois, e vem depois de propósito: uma gramagem errada com
baixa automática ligada faz o stock mentir com autoridade, e ninguém dá por
isso até à contagem do mês.

**Porque é que a unidade é obrigatória junto com o número.** Um `30` sozinho
não quer dizer nada — 30 gramas de granola e 30 mililitros de leite condensado
escrevem-se com o mesmo algarismo e descontam coisas diferentes. Ou se
escrevem os dois, ou não se escreve nenhum.

**Porque é que o `estoque_produto_id` não é o `vendus_ref`.** O `vendus_ref`
já existe na opção e era a tentação óbvia. O próprio catálogo recusa essa
ideia por escrito em `precos.id_vendus_da_variante`: só uma opção de um grupo
de VARIANTE pode desviar o artigo do Vendus, «sem ela, ligar um topping ao
artigo dele no Vendus para efeitos de stock passava a facturar o açaí inteiro
como Nutella». São dois espaços de identificadores diferentes a servir dois
sistemas diferentes, e confundi-los custava dinheiro na fatura.

**E a guarda que dá nome à segunda metade deste ficheiro.** O PUT do grupo faz
`$set` do modelo INTEIRO e substitui o array `opcoes` por completo. O ecrã do
backoffice monta cada opção campo a campo. Junte-se as duas coisas e um
backend que soubesse do consumo, com um ecrã que não soubesse, apagava as
gramagens de TODAS as opções de um grupo à primeira vez que alguém carregasse
em Guardar — sem erro nenhum, sem aviso nenhum. É a repetição exacta do
defeito que obrigou à guarda `model_fields_set` no PUT do produto (o
`vendus_ref` que se apagava sozinho e pôs 36 artigos-lixo na conta do Vendus).
A defesa não pode viver no browser: um curl, um script, ou um ecrã novo que
reutilize este endpoint desligavam-na em silêncio.
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import catalogo as catalogo_mod
from faturacao.catalogo import (
    UNIDADES_DE_CONSUMO,
    GrupoPersonalizacaoEntrada,
    OpcaoEntrada,
    editar_grupo,
)

from .test_catalogo import ColeccaoFalsa, DbFalsa


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- O modelo: quanto, de quê, e de qual artigo -------------------------------


def test_uma_opcao_sem_consumo_continua_valida():
    """A esmagadora maioria das opções não gasta nada de medido, e as que já
    estão gravadas não têm estes campos de todo. Nenhuma delas pode passar a
    ser recusada por causa desta obra."""
    opcao = OpcaoEntrada(nome="Nutella", preco=0.95)
    assert opcao.consumo is None
    assert opcao.consumo_unidade is None
    assert opcao.estoque_produto_id is None


def test_uma_opcao_com_consumo_unidade_e_artigo_e_aceite():
    opcao = OpcaoEntrada(
        nome="Granola",
        preco=0.80,
        consumo=30,
        consumo_unidade="g",
        estoque_produto_id="est-granola",
        estoque_unidade_medida="kg",
    )
    assert opcao.consumo == 30
    assert opcao.consumo_unidade == "g"
    assert opcao.estoque_produto_id == "est-granola"


def test_um_consumo_sem_unidade_e_recusado():
    """`30` sozinho não diz se são gramas, mililitros ou unidades — e quem o
    lesse a seguir tinha de adivinhar."""
    with pytest.raises(ValidationError) as excinfo:
        OpcaoEntrada(nome="Granola", consumo=30)
    assert "unidade" in str(excinfo.value).lower()


def test_uma_unidade_sem_consumo_e_recusada():
    """O contrário do teste acima, pela mesma razão: «gramas» sem número não
    desconta nada. Ou os dois campos, ou nenhum."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Granola", consumo_unidade="g")


@pytest.mark.parametrize("unidade", sorted(UNIDADES_DE_CONSUMO))
def test_as_unidades_conhecidas_sao_aceites(unidade):
    opcao = OpcaoEntrada(nome="Granola", consumo=1, consumo_unidade=unidade)
    assert opcao.consumo_unidade == unidade


def test_uma_unidade_inventada_e_recusada():
    """Escrever «colheres» aqui não é um erro de escrita — é uma medida que
    ninguém do outro lado sabe converter."""
    with pytest.raises(ValidationError) as excinfo:
        OpcaoEntrada(nome="Granola", consumo=2, consumo_unidade="colheres")
    assert "colheres" in str(excinfo.value)


def test_um_consumo_negativo_e_recusado():
    """Um consumo negativo ACRESCENTAVA stock a cada venda."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Granola", consumo=-30, consumo_unidade="g")


def test_um_consumo_infinito_e_recusado():
    """Mesma guarda que o preço já tem: `Infinity` não é negativo e passa por
    todas as outras validações, e o json do Python aceita o literal."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Granola", consumo=float("inf"), consumo_unidade="g")


def test_um_consumo_de_zero_e_aceite():
    """Zero é uma resposta legítima e diferente de «não sei»: é o topping que
    não pesa nada de medível (um palito, um guardanapo)."""
    opcao = OpcaoEntrada(nome="Palito", consumo=0, consumo_unidade="un")
    assert opcao.consumo == 0


def test_o_consumo_pode_ficar_escrito_antes_de_haver_artigo_do_estoque():
    """A gramagem escreve-se de uma assentada, olhando para a ficha; ligar
    cada opção ao artigo do Estoque é outro trabalho, feito a seguir. Obrigar
    aos dois ao mesmo tempo obrigava a deixar o ecrã a meio."""
    opcao = OpcaoEntrada(nome="Granola", consumo=30, consumo_unidade="g")
    assert opcao.estoque_produto_id is None


# --- A guarda: gravar um grupo não pode apagar o que não se falou -------------


def _db_com_grupo(registo, grupo):
    return DbFalsa(
        {
            "fat_grupos_personalizacao": ColeccaoFalsa(
                registo, update_one_matched=1, find_one_devolve=grupo
            )
        }
    )


_GRUPO_GRAVADO = {
    "id": "g1",
    "nome": "Toppings",
    "min_select": 0,
    "max_select": 0,
    "ativo": True,
    "opcoes": [
        {
            "id": "opt-granola",
            "nome": "Granola",
            "preco": 0.80,
            "ativa": True,
            "consumo": 30,
            "consumo_unidade": "g",
            "estoque_produto_id": "est-granola",
            "estoque_unidade_medida": "kg",
        }
    ],
}


def _opcoes_escritas(registo):
    escrita = next(c for c in registo if c[0] == "update_one")
    return escrita[2]["$set"]["opcoes"]


def test_gravar_um_grupo_sem_falar_do_consumo_nao_apaga_o_que_la_estava(monkeypatch):
    """O ecrã antigo — ou um curl, ou um script — manda a opção com nome,
    preço e `ativa`, e mais nada. Isso NÃO é «põe o consumo a nulo»: é «não
    falei do consumo». Sem esta guarda, uma ida ao ecrã das Personalizações
    para corrigir um preço levava consigo, em silêncio, a gramagem de todas as
    opções do grupo."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.90)],
    )
    _corre(editar_grupo("g1", dados, _={}))

    escrita = _opcoes_escritas(registo)[0]
    assert escrita["preco"] == 0.90, "o preço que veio no pedido tem de mudar"
    assert escrita["consumo"] == 30
    assert escrita["consumo_unidade"] == "g"
    assert escrita["estoque_produto_id"] == "est-granola"


def test_quem_fala_do_consumo_muda_mesmo_o_consumo(monkeypatch):
    """A outra metade da guarda. Preservar o que não se fala não pode
    transformar-se em congelar o campo para sempre — senão corrigir uma
    gramagem errada tornava-se impossível pelo ecrã."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[
            OpcaoEntrada(
                id="opt-granola",
                nome="Granola",
                preco=0.80,
                consumo=45,
                consumo_unidade="g",
                estoque_produto_id="est-granola",
                estoque_unidade_medida="kg",
            )
        ],
    )
    _corre(editar_grupo("g1", dados, _={}))

    assert _opcoes_escritas(registo)[0]["consumo"] == 45


def test_mandar_o_consumo_a_nulo_de_propria_vontade_apaga_o_consumo(monkeypatch):
    """Desligar a medição de uma opção tem de ser possível — e distingue-se de
    «não falei do assunto» por o campo vir escrito no pedido."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[
            OpcaoEntrada(
                id="opt-granola",
                nome="Granola",
                preco=0.80,
                consumo=None,
                consumo_unidade=None,
                estoque_produto_id=None,
            )
        ],
    )
    _corre(editar_grupo("g1", dados, _={}))

    escrita = _opcoes_escritas(registo)[0]
    assert escrita["consumo"] is None
    assert escrita["estoque_produto_id"] is None


def test_apagar_SO_o_numero_nao_deixa_a_unidade_orfa(monkeypatch):
    """A guarda preserva o consumo EM BLOCO, e é por isto.

    O `_valida_consumo` promete que nunca se grava número sem unidade — mas
    valida o PEDIDO, e a preservação corre depois. Campo a campo, este pedido
    (`consumo: null`, unidade não mencionada) passava a validação — no pedido
    os dois estão a None — e saía com `consumo=None, consumo_unidade="g"`,
    exactamente o par que o validador existe para recusar."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.80, consumo=None)],
    )
    _corre(editar_grupo("g1", dados, _={}))

    escrita = _opcoes_escritas(registo)[0]
    assert escrita["consumo"] is None
    assert escrita["consumo_unidade"] is None, "a unidade ficou órfã do número"


def test_apagar_SO_a_unidade_nao_deixa_o_numero_orfao(monkeypatch):
    """O contrário, e o mais perigoso dos dois: `consumo=30` com a unidade a
    nulo era carimbado na linha pelo `venda.py` (que só pergunta se o consumo
    existe) e depois o relatório deitava-o fora em silêncio, por não saber
    converter a unidade. Uma gramagem escrita que nunca aparecia em lado
    nenhum, sem um erro pelo caminho."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.80,
                             consumo_unidade=None)],
    )
    _corre(editar_grupo("g1", dados, _={}))

    escrita = _opcoes_escritas(registo)[0]
    assert escrita["consumo_unidade"] is None
    assert escrita["consumo"] is None, "o número ficou órfão da unidade"


def test_gravar_sem_falar_do_vendus_ref_tambem_nao_o_apaga(monkeypatch):
    """O buraco que a docstring desta guarda invocava como precedente — e que
    continuava aberto ao lado dela. O `vendus_ref` é o campo que decide em nome
    de que ARTIGO do Vendus a linha é facturada; um PUT que não fale dele
    gravava-o a nulo, e as cinco lojas voltavam a facturar todos os tamanhos
    no mesmo artigo. O backoffice reenvia-o sempre, mas essa defesa vive no
    browser: um curl ou um script desligavam-na sem deixar rasto."""
    registo = []
    gravado = dict(_GRUPO_GRAVADO)
    gravado["opcoes"] = [dict(_GRUPO_GRAVADO["opcoes"][0], vendus_ref="145268982")]
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, gravado))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.90)],
    )
    _corre(editar_grupo("g1", dados, _={}))

    assert _opcoes_escritas(registo)[0]["vendus_ref"] == "145268982"


def test_quem_manda_o_vendus_ref_a_nulo_DESLIGA_mesmo_a_ligacao(monkeypatch):
    """A outra metade: desligar um tamanho tem de continuar a ser possível, e
    é o que o ecrã faz — manda o campo explicitamente a nulo."""
    registo = []
    gravado = dict(_GRUPO_GRAVADO)
    gravado["opcoes"] = [dict(_GRUPO_GRAVADO["opcoes"][0], vendus_ref="145268982")]
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, gravado))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.90, vendus_ref=None)],
    )
    _corre(editar_grupo("g1", dados, _={}))

    assert _opcoes_escritas(registo)[0]["vendus_ref"] is None


def test_um_consumo_absurdo_e_recusado_a_entrada():
    """Escrever 30000 em vez de 30 gravava 30 kg de granola por dose. Não é um
    limite físico — é o apanha-zeros."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Granola", consumo=30000, consumo_unidade="g")


def test_uma_opcao_nova_nao_herda_o_consumo_de_ninguem(monkeypatch):
    """Uma opção sem id é nova: recebe um id novo e nasce sem consumo. Herdar
    pela POSIÇÃO na lista era o erro fácil — a Banana acrescentada a seguir à
    Granola passava a descontar granola."""
    registo = []
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: _db_com_grupo(registo, _GRUPO_GRAVADO))

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[
            OpcaoEntrada(nome="Banana", preco=0.50),
            OpcaoEntrada(id="opt-granola", nome="Granola", preco=0.80),
        ],
    )
    _corre(editar_grupo("g1", dados, _={}))

    nova, granola = _opcoes_escritas(registo)
    assert nova["nome"] == "Banana"
    assert nova["consumo"] is None
    assert nova["estoque_produto_id"] is None
    assert granola["consumo"] == 30, "e a que já existia mantém o que era dela"


def test_editar_um_grupo_que_nao_existe_continua_a_dar_404(monkeypatch):
    """A guarda passa a ler o grupo ANTES de escrever. Esse passo novo não
    pode mudar a resposta a quem edita um grupo apagado entretanto."""
    registo = []
    db = DbFalsa(
        {"fat_grupos_personalizacao": ColeccaoFalsa(registo, update_one_matched=0)}
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_grupo("nao-existe", GrupoPersonalizacaoEntrada(nome="Toppings"), _={}))
    assert excinfo.value.status_code == 404


# --- O carimbo: a gramagem viaja com a linha da venda -------------------------
#
# Porque é que se carimba em vez de a ir buscar à configuração na altura de
# ler: o relatório de consumo tem de ser reproduzível. Sem carimbo, corrigir
# hoje a gramagem da granola mudava sozinho o que o relatório disse do mês
# passado — e é contra o relatório do mês passado que se confere uma contagem
# do armazém. É a mesma doutrina que a linha já aplica ao `produto_preco`, ao
# `nome_grupo` e ao `vendus_ref`: a linha é o retrato do dia em que nasceu.

from faturacao.venda import PedidoJuntarLinha, juntar_linha  # noqa: E402
from faturacao import venda as venda_mod  # noqa: E402

from .test_venda import _db, _operador, _produto, _venda  # noqa: E402

_GRUPO_COM_CONSUMO = {
    "id": "g1",
    "nome": "Toppings",
    "sai_na_fatura": True,
    "opcoes": [
        {
            "id": "o1",
            "nome": "Granola",
            "preco": 0.80,
            "consumo": 30,
            "consumo_unidade": "g",
            "estoque_produto_id": "est-granola",
            "estoque_unidade_medida": "kg",
        }
    ],
}


def _junta_com_a_opcao(monkeypatch, grupo, opcao_do_balcao):
    registo = []
    db = _db(registo, vendas=[_venda()], produtos=[_produto()], grupos=[grupo])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    resultado = _corre(
        juntar_linha(
            "venda-1",
            PedidoJuntarLinha(produto_id="prod-1", quantidade=1, opcoes=[opcao_do_balcao]),
            operador=_operador(),
        )
    )
    return resultado["linhas"][0]["opcoes"][0]


def test_juntar_linha_carimba_o_consumo_da_opcao(monkeypatch):
    opcao = _junta_com_a_opcao(
        monkeypatch,
        _GRUPO_COM_CONSUMO,
        {"id": "o1", "grupo_id": "g1", "nome": "Granola", "preco": 0.80},
    )
    assert opcao["consumo"] == 30
    assert opcao["consumo_unidade"] == "g"
    assert opcao["estoque_produto_id"] == "est-granola"
    assert opcao["estoque_unidade_medida"] == "kg", (
        "sem a unidade do artigo o desconto adivinha, e erra por mil")


def test_o_consumo_vem_SEMPRE_da_configuracao_e_nunca_do_balcao(monkeypatch):
    """A mesma regra dura do `vendus_ref`, e pela mesma razão: aceitar isto do
    cliente era deixar escolher, de fora, quanto se desconta do armazém. Quem
    falasse à rota à mão esvaziava o stock de granola com uma venda."""
    opcao = _junta_com_a_opcao(
        monkeypatch,
        _GRUPO_COM_CONSUMO,
        {
            "id": "o1", "grupo_id": "g1", "nome": "Granola", "preco": 0.80,
            "consumo": 9999, "consumo_unidade": "kg", "estoque_produto_id": "est-caviar",
        },
    )
    assert opcao["consumo"] == 30
    assert opcao["consumo_unidade"] == "g"
    assert opcao["estoque_produto_id"] == "est-granola"


def test_uma_opcao_sem_consumo_na_configuracao_nao_leva_carimbo_nenhum(monkeypatch):
    """E limpa o que o pedido trouxesse — senão uma medição desligada no
    backoffice continuava a descontar até alguém dar por isso, que é
    exactamente o que o `vendus_ref` já aprendeu a fazer aqui ao lado."""
    grupo_sem_consumo = {
        "id": "g1", "nome": "Toppings", "sai_na_fatura": True,
        "opcoes": [{"id": "o1", "nome": "Granola", "preco": 0.80}],
    }
    opcao = _junta_com_a_opcao(
        monkeypatch,
        grupo_sem_consumo,
        {
            "id": "o1", "grupo_id": "g1", "nome": "Granola", "preco": 0.80,
            "consumo": 30, "consumo_unidade": "g", "estoque_produto_id": "est-granola",
        },
    )
    assert "consumo" not in opcao
    assert "consumo_unidade" not in opcao
    assert "estoque_produto_id" not in opcao
    assert "estoque_unidade_medida" not in opcao


# --- A ficha e o artigo têm de medir a mesma coisa ---------------------------


def test_uma_ficha_em_gramas_ligada_a_um_artigo_contado_em_UNIDADES_e_recusada():
    """Sem esta guarda, «30 g» ligado a um artigo que conta unidades descontava
    TRINTA pacotes de granola por copo — e o movimento de stock não leva
    unidade nenhuma, portanto o Estoque não tinha como recusar."""
    with pytest.raises(ValidationError) as excinfo:
        OpcaoEntrada(nome="Granola", consumo=30, consumo_unidade="g",
                     estoque_produto_id="est-granola", estoque_unidade_medida="un")
    assert "medidas de coisas diferentes" in str(excinfo.value)


def test_um_artigo_contado_em_CAIXAS_nao_se_deixa_ligar():
    """Uma caixa de quê, com quantos? Deixar ligar e nunca descontar era pior:
    uma ficha preenchida que não faz nada."""
    with pytest.raises(ValidationError) as excinfo:
        OpcaoEntrada(nome="Granola", consumo=30, consumo_unidade="g",
                     estoque_produto_id="est-granola", estoque_unidade_medida="caixa")
    assert "caixa" in str(excinfo.value)


def test_um_artigo_SEM_a_unidade_dele_continua_a_ser_aceite():
    """É o que está gravado desde a Fase 1: artigo ligado, unidade do artigo
    por saber (o campo ainda não existia).

    Recusar aqui fechava o ecrã à chave — a mensagem mandava escolher o artigo
    outra vez, o ecrã reenviava o mesmo pedido, e falhava na mesma. A guarda
    que interessa é a do DESCONTO, que salta uma ficha por acertar em vez de
    adivinhar: nunca desconta errado, e diz porquê no registo."""
    opcao = OpcaoEntrada(nome="Granola", consumo=30, consumo_unidade="g",
                         estoque_produto_id="est-granola")
    assert opcao.estoque_unidade_medida is None


def test_mililitros_ligam_se_a_um_artigo_contado_em_litros():
    opcao = OpcaoEntrada(nome="Leite condensado", consumo=20, consumo_unidade="ml",
                         estoque_produto_id="est-leite", estoque_unidade_medida="L")
    assert opcao.estoque_unidade_medida == "L"


def test_uma_gramagem_SEM_artigo_nao_precisa_de_unidade_de_artigo():
    """Escrever as gramagens de uma assentada e ligar os artigos depois tem de
    continuar a ser possível — era isso que evitava deixar o ecrã a meio."""
    opcao = OpcaoEntrada(nome="Granola", consumo=30, consumo_unidade="g")
    assert opcao.estoque_unidade_medida is None
