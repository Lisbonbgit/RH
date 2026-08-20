"""A conta do balcão — Plano 2B, Task 2 (spec §7.3/§7.4, `fat_vendas`).

A operadora vai tocando em produtos no ecrã; cada toque junta uma linha a
esta conta. Uma venda nasce `aberta` e sai daqui por um de dois caminhos:
`emitida` (Plano 2B Task 3, `fiscal.py`) — depois disso, nenhuma alteração é
aceite aqui: emitir corta a fatura, e alterar uma conta já faturada é
exactamente o tipo de coisa que obriga a uma nota de crédito — ou
`cancelada`, a conta que o cliente desistiu de levar.

Regras que não se negoceiam (brief da Task 2):

- **A sessão e o operador vêm SEMPRE do token, nunca do corpo.** Os modelos
  de entrada nem sequer declaram esses campos — mesmo padrão de
  `faturacao/caixa.py` (ver a docstring desse módulo). A venda resolve a
  sessão a partir da caixa indicada + a loja do operador autenticado,
  reutilizando `_obter_caixa_da_loja`/`_sessao_aberta` de `caixa.py` — a
  MESMA resolução, não uma segunda implementação que podia divergir.
- **Os totais derivam sempre de `precos.linha_de_venda`** — a mesma função
  que vai construir as linhas que saem para o Vendus na Task 3. Este módulo
  NUNCA soma preços "por fora": cada linha guardada é um conjunto de
  ingredientes brutos (produto, quantidade, opções, overrides), e o total é
  sempre recalculado chamando `linha_de_venda` sobre eles. Uma só fonte de
  verdade — senão o que a operadora vê no ecrã e o que sai no papel
  divergiam ao cêntimo, sem ninguém perceber porquê.
- **Um produto sem IVA (ou sem preço) definido não entra na conta.** Erro
  claro (422, reaproveitando `precos.erros_do_produto` — a mesma função que
  já avisa disto no ecrã "Produtos sem IVA" do catálogo), nunca um valor
  assumido. Isto é verificado no PRODUTO do catálogo, antes de qualquer
  override: um override é para ajustar uma linha excepcionalmente, não para
  contornar um artigo mal configurado.
- **Uma venda já emitida (ou cancelada) recusa qualquer alteração.** Todas as
  rotas que escrevem confirmam `estado == "aberta"` antes de tocar em nada.
"""
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .caixa import _obter_caixa_da_loja, _quem, _sessao_aberta
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais, erros_do_produto, linha_de_venda

router = APIRouter()

_MSG_VENDA_INEXISTENTE = "Venda não encontrada."
_MSG_VENDA_NAO_ABERTA = "Esta venda já foi emitida ou cancelada — não aceita alterações."
_MSG_LINHA_INEXISTENTE = "Linha não encontrada nesta venda."
_MSG_PRODUTO_INEXISTENTE = "Produto não encontrado."
# A MESMA mensagem para as cinco rotas de escrita (juntar/editar/remover
# linha, desconto global, cancelar): o que a operadora precisa de saber é
# igual nas cinco — esta conta está TRAVADA e quem a destranca é o gestor,
# depois de olhar para o Vendus. Deixou de dizer "não pode ser cancelada"
# porque deixou de ser só sobre o cancelamento.
_MSG_VENDA_COM_EMISSAO = (
    "Esta conta tem uma emissão de fatura em curso ou por confirmar — está "
    "travada e não aceita alterações nem cancelamento. Chame o gestor: só "
    "depois de se confirmar no Vendus se a Fatura Simplificada chegou a sair "
    "é que se sabe o que fazer a esta conta."
)
# O choque de duas alterações à MESMA conta (ver `_aplicar_as_linhas`). Não é
# um erro para chamar o gestor — é uma conta que mudou por baixo e que se relê.
_MSG_CONTA_MUDOU_DEBAIXO = (
    "Esta conta foi alterada noutro sítio ao mesmo tempo (outro separador do "
    "POS, ou o ecrã recarregado a meio) e esta alteração não foi gravada, "
    "para não apagar a outra. Olhe para a conta como ela está agora e repita "
    "só o que faltar."
)
# As duas mensagens do cancelamento COMPENSADO (ver `_porque_nao_foi_cancelada`):
# o 409 tem de descrever a conta como ela está no instante em que a operadora
# o lê, e não como estava quando a compensação começou.
_MSG_VENDA_EMITIDA_ENTRETANTO = (
    "Esta conta NÃO foi cancelada: a fatura saiu mesmo, mesmo agora — a "
    "Fatura Simplificada está entregue à Autoridade Tributária. Uma venda "
    "faturada não se cancela; o que estiver errado nela corrige-se com uma "
    "nota de crédito."
)
_MSG_CANCELAMENTO_ABORTADO_SEM_EMISSAO = (
    "Esta conta NÃO foi cancelada: estava a decorrer uma emissão, que "
    "entretanto foi abortada sem chegar a emitir — NÃO saiu nenhuma Fatura "
    "Simplificada e a conta está outra vez aberta. Carregue em Cancelar "
    "outra vez."
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recusa_mais_de_2_casas(v):
    """Mesmo crivo de precos.py, reutilizado e não reescrito — usado aqui só
    para os campos que `linha_de_venda` NÃO valida por si (o desconto
    GLOBAL, que actua sobre a venda inteira, não sobre uma linha)."""
    if v is not None and _tem_mais_de_2_casas_decimais(v):
        raise ValueError(
            "O valor %s tem mais de 2 casas decimais — a conta recusa-o "
            "para não perder um cêntimo no arredondamento." % v
        )
    return v


class PedidoNovaVenda(BaseModel):
    caixa_id: str = Field(min_length=1)


class RespostaTexto(BaseModel):
    """A resposta a um grupo de tipo texto — hoje, o nome que se escreve no
    copo. Guarda-se também o `nome_grupo` (um retrato, como o `produto_nome`)
    para o talão da cozinha poder ser lido daqui a um mês sem ir buscar o
    grupo, que pode ter mudado de nome ou desaparecido."""

    grupo_id: str = Field(min_length=1)
    nome_grupo: Optional[str] = None
    texto: str = Field(max_length=120)


class PedidoJuntarLinha(BaseModel):
    produto_id: str = Field(min_length=1)
    quantidade: int = Field(default=1, ge=1)
    opcoes: List[Dict] = Field(default_factory=list)
    respostas_texto: List[RespostaTexto] = Field(default_factory=list)
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)


class PedidoEditarLinha(BaseModel):
    # Tudo opcional: só os campos PRESENTES no pedido são alterados (lidos
    # com model_dump(exclude_unset=True)) — permite, por exemplo, limpar um
    # preco_override de volta a None sem ter de repetir o resto da linha.
    quantidade: Optional[int] = Field(default=None, ge=1)
    opcoes: Optional[List[Dict]] = None
    respostas_texto: Optional[List[RespostaTexto]] = None
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)


class PedidoDescontoGlobal(BaseModel):
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)

    @field_validator("desconto_eur")
    @classmethod
    def _valida_eur(cls, v):
        return _recusa_mais_de_2_casas(v)


async def _obter_venda_da_loja(db, venda_id: str, loja_id: str) -> Dict:
    """Confirma que a venda existe E pertence à loja do operador autenticado
    — mesmo raciocínio de `_obter_caixa_da_loja` em caixa.py: o âmbito nunca
    é só o id."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if not venda or venda.get("loja_id") != loja_id:
        raise HTTPException(status_code=404, detail=_MSG_VENDA_INEXISTENTE)
    return venda


def _garante_aberta(venda: Dict) -> None:
    if venda.get("estado") != "aberta":
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)


async def _tem_reserva_fiscal(db, venda_id: str) -> bool:
    """Existe uma reserva de emissão para esta venda?

    O `estado` da venda não conta a história toda: `fiscal.py::_reservar`
    insere um documento em `fat_refs_fiscais` ANTES de falar com o Vendus, e
    a venda só passa a `emitida` no fim (`_gravar_documento`). Entre as duas
    coisas — que são segundos de espera pela resposta do Vendus, ou horas se
    a reserva ficar `incerta` — a venda continua a dizer `aberta` enquanto
    pode estar a nascer uma Fatura Simplificada real do outro lado.

    A pergunta é pelo `venda_id` e NÃO pela `ext_ref`: a fórmula da ext_ref é
    a chave da idempotência e não pode ter uma segunda fonte (uma cópia dela
    aqui divergia no dia em que a original mudasse, e a idempotência morria
    em silêncio); e importar `ext_ref_determinista` de `fiscal.py` fechava um
    ciclo, porque é o `fiscal.py` que importa deste módulo. O campo
    `venda_id` é gravado em toda a reserva desde sempre, e é por ele que a
    gestão já liga as reservas às vendas (`fiscal.py::listar_reservas_presas`).
    """
    reserva = await db[COLECOES["refs_fiscais"]].find_one({"venda_id": venda_id})
    return reserva is not None


async def _garante_sem_emissao(db, venda_id: str) -> None:
    """**Uma venda com reserva fiscal fica CONGELADA** — nenhuma das rotas de
    escrita lhe toca até a reserva desaparecer ou a venda ficar `emitida`.

    `_garante_aberta` sozinho é o critério insuficiente que a docstring de
    `_tem_reserva_fiscal` descreve, e não era só o cancelamento que decidia
    por ele: `juntar_linha`, `editar_linha`, `remover_linha` e
    `aplicar_desconto_global` decidiam TODAS só com ele. O estrago, medido
    num guião de reprodução: o Vendus dá timeout, a verificação também falha,
    a reserva fica `incerta` e a venda fica `aberta` (é o desenho, ver
    `fiscal.py::VerificacaoFiscalIncerta`) — a FS de 8,99 € até pode ter
    saído. A conta continua no ecrã, aceita um segundo açaí (201) e um
    desconto de 10 % (200), e mais tarde a retoma encontra o documento
    original e liga-lhe a venda: fica no sistema uma venda `emitida` de
    16,18 € contra um documento fiscal real de 8,99 €. O Z não apanha a
    divergência (soma os `pagamentos`, não os `_totais`) e ela não aparece em
    lado nenhum.

    Factorizada, e não copiada cinco vezes, por uma razão concreta: no dia em
    que este critério mudar (uma reserva com idade, uma reserva de outra
    sessão), tem de mudar nos cinco sítios ao mesmo tempo — quatro em cinco
    era exactamente o estado que isto veio corrigir."""
    if await _tem_reserva_fiscal(db, venda_id):
        raise HTTPException(status_code=409, detail=_MSG_VENDA_COM_EMISSAO)


async def _porque_nao_foi_cancelada(db, venda_id: str) -> str:
    """A mensagem do 409 do cancelamento compensado — escolhida pelo estado
    que a conta tem NO MOMENTO EM QUE A MENSAGEM É ENVIADA, e não pelo que
    ela tinha quando a compensação começou.

    A3 (achado desta ronda, sem estrago fiscal mas com estrago humano): o
    cancelar escrevia `cancelada`, a releitura do `finalizar` via-a, libertava
    a reserva e abortava sem emitir, e a compensação repunha `aberta`. A conta
    acabava `aberta`, sem reserva e sem emissão nenhuma — e a operadora ouvia
    "esta conta tem uma emissão de fatura em curso... Chame o gestor". Bastava
    voltar a carregar em Cancelar. Chamar o gestor a uma loja cheia por causa
    de uma conta perfeitamente boa é o mesmo tipo de erro que dizer "tente
    novamente" onde não se pode tentar — só que ao contrário.

    As três saídas possíveis, todas verdadeiras no instante em que se lêem:
    1. a venda ficou `emitida` — a emissão ganhou mesmo, e o que a operadora
       precisa de saber é que a fatura SAIU (nota de crédito, nunca cancelar);
    2. a reserva ainda lá está — a emissão continua viva ou ficou por
       confirmar: é o caso em que o gestor faz falta, e a mensagem de sempre
       (`_MSG_VENDA_COM_EMISSAO`) está certa;
    3. nem uma coisa nem outra — a emissão abortou sem emitir e a conta está
       outra vez aberta: carregar de novo resolve."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    estado = (venda or {}).get("estado")
    if estado == "emitida":
        return _MSG_VENDA_EMITIDA_ENTRETANTO
    if await _tem_reserva_fiscal(db, venda_id):
        return _MSG_VENDA_COM_EMISSAO
    if estado == "aberta":
        return _MSG_CANCELAMENTO_ABORTADO_SEM_EMISSAO
    # Estado inesperado (a venda desapareceu, ou ficou num estado que este
    # módulo não escreve): não se inventa um diagnóstico — vale a mensagem
    # mais conservadora, a que manda confirmar antes de mexer.
    return _MSG_VENDA_COM_EMISSAO


async def _escrever_se_ainda_aberta(db, venda_id: str, atualizacao: Dict) -> None:
    """A escrita do DESCONTO GLOBAL, sempre CONDICIONADA a
    `{"estado": "aberta"}` — e é o `matched_count`, não o `_garante_aberta`
    lá de cima, que decide.

    Era também a das três rotas de LINHA, e deixou de o ser: essas escrevem o
    array `linhas` inteiro, lido no princípio do pedido, e para isso a
    condição do estado não chega — ver `_aplicar_as_linhas`, que prende
    também a VERSÃO do que foi lido. O desconto global fica aqui porque
    escreve dois campos escalares e mais nada: duas escritas sobrepostas dão
    o valor de uma delas (a última), nunca um valor que ninguém pediu, e não
    apagam linha nenhuma.

    As cinco rotas de escrita já tinham todas a PERGUNTA
    (`_garante_sem_emissao`); só o `cancelar_venda` é que tinha também a
    escrita condicional. As outras quatro escreviam
    `update_one({"id": venda_id}, ...)` sem condição nenhuma, e entre a
    pergunta e a escrita ainda há `await`s (o `find_one` do produto em
    `juntar_linha`, o próprio I/O da escrita) — janela estreita, mas
    suficiente: reproduzido em processo, com a emissão a correr INTEIRA
    nessa janela, ficava no Mongo uma venda `emitida` com 2 linhas e
    17,98 € contra um documento fiscal REAL de 8,99 €. E ninguém dava por
    isso: o Z soma os `pagamentos`, não os `_totais`.

    A mensagem é a de sempre (`_MSG_VENDA_NAO_ABERTA`) porque descreve
    exactamente o estado em que a conta ficou — emitida ou cancelada por
    quem chegou primeiro."""
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)


# Quantas vezes se volta a ler a conta e a repetir a alteração sobre ela antes
# de desistir e mandar reler o ecrã.
#
# **Não é folga — é um TECTO, e sabe-se qual.** Sob contenção em lock-step
# (todos a lerem antes de qualquer um gravar) cada ronda deixa passar
# exactamente UM escritor — o que tinha a versão certa —, por isso N escritores
# simultâneos precisam de N rondas e o (N+1)-ésimo esgota as tentativas.
# Medido, sobre a rota real, com um duplo que cede o controlo em cada operação:
# quatro toques ao mesmo tempo na mesma conta entram os quatro; ao quinto, um
# deles leva 409 (`_MSG_CONTA_MUDOU_DEBAIXO`). Os dois casos estão presos por
# teste (`test_venda.py`, secção "O TECTO das tentativas"), por isso mexer no
# número põe um deles vermelho — que é o que se quer.
#
# Chegar lá exige cinco separadores do POS a picar a MESMA conta ao mesmo
# tempo: a fila do `PosVenda.js` mantém uma escrita em voo por instância, logo
# cada separador só contribui com uma.
#
# E o que está no fim do tecto não é perda: o toque que esgota as tentativas é
# RECUSADO com um 409 que diz à operadora o que aconteceu, sem ter escrito
# nada. Não há aqui dinheiro a proteger com um número maior — há só a escolha
# entre repetir mais vezes (mais releituras e mais escritas falhadas contra uma
# conta já em contenção) e dizer a verdade mais cedo.
_TENTATIVAS_DE_ESCRITA_DAS_LINHAS = 4


async def _aplicar_as_linhas(
    db,
    venda_id: str,
    loja_id: str,
    aplicar: Callable[[Dict], List[Dict]],
    venda: Optional[Dict] = None,
) -> Dict:
    """A escrita das TRÊS rotas de linha (juntar/editar/remover), condicionada
    ao estado da conta **e à versão das linhas que foram lidas**.
    `aplicar(conta)` recebe a conta acabada de ler e devolve a lista de linhas
    nova (ou levanta 404/422, como as rotas já faziam).

    **O defeito que isto fecha.** As três rotas liam o array `linhas` inteiro,
    mexiam-lhe em memória e gravavam-no INTEIRO por cima com
    `_escrever_se_ainda_aberta` — que prende a identidade e o ESTADO da venda,
    mas não a versão do que foi lido. Duas escritas sobrepostas e a última
    apagava a primeira, com as duas respostas HTTP a dizer 200. Medido, sobre
    as rotas reais: A junta a água (lê [açaí], pára), B remove o açaí inteiro,
    A grava o que leu → «o que ficou MESMO no Mongo -> ['Açaí Regular',
    'Água 33cl']»: o açaí que a operadora removeu volta à conta e vai numa
    Fatura Simplificada REAL de 9,99 € em vez de 1,00 €. Pela ordem inversa é
    a água que desaparece do Mongo depois de o ecrã a mostrar na conta — e o
    cliente leva-a sem a pagar.

    Isto não é novo e a defesa existia: uma fila em `PosVenda.js` que
    serializa as escritas. Só que essa fila vive toda no CLIENTE e é POR
    INSTÂNCIA — um F5 a meio de um pedido lento, ou dois separadores do POS no
    mesmo PC (partilham o `dispositivo_id`, logo recuperam a MESMA conta pela
    `GET /pos/venda/aberta`), passam-lhe ao lado. Uma defesa que o cliente
    pode contornar sem dar por isso não defende a conta: tem de estar aqui.

    **O contador, e porque não os operadores atómicos do Mongo.** A versão é
    um `linhas_versao` na própria venda, exigido no filtro e incrementado na
    mesma escrita: quem gravar sobre uma leitura já ultrapassada não casa com
    nada e não escreve NADA. A alternativa era não ter contador nenhum e usar
    `$push` para juntar e `$pull` para remover — o Mongo aplica-os sobre o
    array como ele está, e as duas alterações sobreviviam sem se pisarem, sem
    releituras. Não se escolheu por três razões, e a terceira é a que decide:
    (1) `editar_linha` não se exprime assim (mudar campos de UM elemento de um
    array exige `arrayFilters`, que é outra história e não cobre a validação
    que a rota faz à linha inteira antes de gravar); (2) as três rotas
    respondem com a conta e os totais recalculados, e um operador atómico
    devolve a lista de ANTES — a resposta e o que ficou gravado divergiam;
    (3) um só mecanismo para as três rotas é o que faz com que a próxima
    alteração ao ficheiro não tenha de acertar qual delas está protegida —
    "quatro em cinco" foi exactamente o estado que `_garante_sem_emissao` veio
    corrigir.

    **E porque é que se RELÊ e se repete em vez de responder logo 409.** A
    alteração que a operadora pediu é um DELTA sobre a conta ("junta uma
    água", "tira esta linha", "põe quantidade 2 nesta"), e um delta aplica-se
    tal e qual à conta como ela está agora — que é precisamente o que a fila
    do cliente faz, e o que a operadora esperava que acontecesse. Mandá-la
    repetir um toque que o sistema sabe repetir sozinho é fazer-lhe perder
    tempo com o cliente à frente. O que NÃO se repete às cegas é o que deixou
    de fazer sentido: se a linha a editar ou a remover desapareceu, o
    `aplicar` levanta 404 e ninguém inventa nada.

    Esgotadas as tentativas (uma conta a ser martelada de dois sítios ao mesmo
    tempo), o 409 diz à operadora o que se passou — nunca um 200 sobre uma
    escrita que não aconteceu."""
    for _ in range(_TENTATIVAS_DE_ESCRITA_DAS_LINHAS):
        if venda is None:
            # A releitura traz as MESMAS guardas de entrada da rota, e não só
            # a conta: entre duas tentativas pode ter nascido uma reserva
            # fiscal, e uma conta com emissão em curso está congelada
            # (`_garante_sem_emissao`) — repetir por cima dela era escrever
            # numa venda que pode estar a virar Fatura Simplificada.
            venda = await _obter_venda_da_loja(db, venda_id, loja_id)
            _garante_aberta(venda)
            await _garante_sem_emissao(db, venda_id)

        linhas = aplicar(venda)
        versao = venda.get("linhas_versao")
        resultado = await db[COLECOES["vendas"]].update_one(
            # `linhas_versao` ausente (uma conta aberta antes desta correcção)
            # casa com `None`, tal como no Mongo: não é preciso migração
            # nenhuma, e a primeira escrita põe-lhe a versão 1.
            {"id": venda_id, "estado": "aberta", "linhas_versao": versao},
            {"$set": {"linhas": linhas, "linhas_versao": (versao or 0) + 1}},
        )
        if resultado.matched_count == 1:
            venda["linhas"] = linhas
            venda["linhas_versao"] = (versao or 0) + 1
            return venda

        # Não casou por uma de duas razões: ou a conta deixou de estar
        # `aberta` (emitida ou cancelada por quem chegou primeiro), ou mudou
        # de versão por baixo. Não se decide aqui qual foi — relê-se, e são as
        # guardas de entrada, refeitas no topo do ciclo, que respondem: uma
        # conta que já não está aberta apanha o 409 de `_garante_aberta`
        # (`_MSG_VENDA_NAO_ABERTA`) e não chega a repetir nada; uma que só
        # mudou de linhas repete a alteração sobre o que se leu agora. Ter
        # aqui uma segunda leitura só para distinguir os dois casos era
        # escrever um ramo que responde exactamente o mesmo que o ciclo já
        # responde — e que nenhum teste consegue separar do ciclo.
        venda = None

    raise HTTPException(status_code=409, detail=_MSG_CONTA_MUDOU_DEBAIXO)


async def _emissao_por_confirmar(db, venda: Dict) -> bool:
    """O travão desta conta, tal como o ecrã do POS tem de o ver: existe uma
    reserva fiscal E a venda ainda não está `emitida` — exactamente o estado
    em que `_garante_sem_emissao` recusa qualquer escrita.

    A venda `emitida` responde `False` de propósito: a reserva de uma venda
    emitida NÃO desaparece (é ela que sustenta a idempotência, ver
    `fiscal.py::_gravar_documento`), por isso "tem reserva" sozinho marcaria
    para sempre como "por confirmar" toda a conta que correu bem.

    Isto vai à base de dados; `_venda_publica` é síncrono e não tem `db`, por
    isso a resposta compõe-se dos dois (ver o parâmetro
    `emissao_por_confirmar` lá em baixo)."""
    if venda.get("estado") == "emitida":
        return False
    return await _tem_reserva_fiscal(db, venda["id"])


def _produto_snapshot(linha: Dict) -> Dict:
    """O que `linha_de_venda` precisa de um "produto", tirado do retrato
    gravado na própria linha (nome/preço/tax_id/vendus_ref no momento em que
    foi adicionada) — não do catálogo ao vivo, que pode ter mudado ou ter
    sido apagado entretanto.

    O `vendus_ref` viaja no retrato como os outros três, e pela mesma razão:
    é ele que sai na linha do Vendus como `id` e impede que cada venda crie
    lá um produto novo (ver `precos.id_vendus_do_produto`), e ir buscá-lo ao
    catálogo aqui era voltar a consultar um artigo que pode já não existir.

    As linhas de contas abertas ANTES desta alteração não têm o campo: o
    `.get` devolve `None` e a linha sai sem `id`, exactamente como saía —
    nada rebenta."""
    return {
        "nome": linha.get("produto_nome"),
        "preco": linha.get("produto_preco"),
        "tax_id": linha.get("produto_tax_id"),
        "vendus_ref": linha.get("produto_vendus_ref"),
    }


def _linha_vendus(linha: Dict) -> Dict:
    """A linha no formato do Vendus, sempre construída por
    `precos.linha_de_venda` — nunca calculada aqui à parte (ver a docstring
    do módulo). Um `ValueError` de `linha_de_venda` (produto sem preço/IVA,
    override inválido, mais de 2 casas decimais) vira um 422 claro."""
    try:
        return linha_de_venda(
            _produto_snapshot(linha),
            linha.get("quantidade", 1),
            linha.get("opcoes"),
            linha.get("preco_override"),
            linha.get("tax_override"),
            linha.get("desconto_pct"),
            linha.get("desconto_eur"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _bruto_da_linha(li_vendus: Dict) -> float:
    return round(li_vendus["qty"] * li_vendus["gross_price"], 2)


def _desconto_da_linha(li_vendus: Dict) -> float:
    """O desconto EM EUROS que esta linha, sozinha, já dá — seja ele
    guardado em euros ou em percentagem (o Vendus só aceita um dos dois por
    linha, ver precos.linha_de_venda)."""
    if "discount_amount" in li_vendus:
        return round(li_vendus["discount_amount"], 2)
    if "discount_percentage" in li_vendus:
        return round(_bruto_da_linha(li_vendus) * li_vendus["discount_percentage"] / 100, 2)
    return 0.0


def _desconto_global_eur(venda: Dict, base: float) -> float:
    """O desconto da conta TODA, em euros — o € tem precedência sobre a
    percentagem, mesma regra do desconto por linha. Incide sobre `base`
    (o líquido depois dos descontos por linha): é o ÚLTIMO passo, não um
    desconto em paralelo com os que já foram dados linha a linha."""
    eur = venda.get("desconto_global_eur")
    pct = venda.get("desconto_global_pct")
    if eur:
        return round(float(eur), 2)
    if pct:
        return round(base * float(pct) / 100, 2)
    return 0.0


def _totais(venda: Dict) -> Dict:
    linhas_vendus = [_linha_vendus(li) for li in venda.get("linhas", [])]
    subtotal = round(sum(_bruto_da_linha(li) for li in linhas_vendus), 2)
    desconto_linhas = round(sum(_desconto_da_linha(li) for li in linhas_vendus), 2)
    liquido_linhas = round(subtotal - desconto_linhas, 2)
    desconto_global = _desconto_global_eur(venda, liquido_linhas)
    total = round(liquido_linhas - desconto_global, 2)
    return {
        "subtotal": subtotal,
        "desconto_linhas": desconto_linhas,
        "desconto_global": desconto_global,
        "total": total,
    }


def _venda_publica(venda: Dict, emissao_por_confirmar: bool = False) -> Dict:
    """A conta como o ecrã a vê.

    `emissao_por_confirmar` é o TRAVÃO desta conta (ver
    `_emissao_por_confirmar`) e chega aqui já calculado, em vez de ser lido
    aqui dentro: esta função é SÍNCRONA e não tem `db` — e continua a ser,
    porque `fiscal.py` também a usa e `_totais` (que ela chama) é o núcleo
    puro dos totais, que nenhum I/O tem de atravessar.

    O `False` por omissão nunca é uma adivinha; é verdade em cada um dos
    sítios que o usam:
    - as quatro rotas de escrita só chegam aqui DEPOIS de
      `_garante_sem_emissao` ter confirmado que não existe reserva;
    - `abrir_venda` acabou de gerar o `id` da venda neste instante — nenhuma
      reserva pode existir para um uuid que ainda ninguém viu;
    - a resposta de `fiscal.finalizar` traz a venda já `emitida`, que por
      definição responde `False` (ver `_emissao_por_confirmar`).
    Quem NÃO está nesse caso — `GET /pos/venda/aberta`, que é por onde o ecrã
    recupera uma conta que pode ter ficado travada — calcula-o e passa-o.

    O campo está SEMPRE na resposta, mesmo `False`: o ecrã não pode ter de
    adivinhar se a ausência da chave quer dizer "não há emissão pendente" ou
    "versão antiga da API" (mesma regra de `cancelada_em`/`cancelada_por`)."""
    return {
        "id": venda["id"],
        "loja_id": venda["loja_id"],
        "caixa_id": venda["caixa_id"],
        "sessao_id": venda["sessao_id"],
        "operador_id": venda["operador_id"],
        "linhas": venda.get("linhas", []),
        "desconto_global_pct": venda.get("desconto_global_pct"),
        "desconto_global_eur": venda.get("desconto_global_eur"),
        "estado": venda["estado"],
        "criada_em": venda["criada_em"],
        # O cancelamento também se mostra: sem isto, `cancelada_em` era
        # escrito e nunca lido por ninguém — um dado cego. Quem cancelou é a
        # primeira pergunta quando falta dinheiro na gaveta ao fim do dia
        # (picar, receber, cancelar a conta é o esquema clássico ao balcão), e
        # a resposta não pode viver só dentro do Mongo. `None` nas contas que
        # não foram canceladas, que é a esmagadora maioria.
        "cancelada_em": venda.get("cancelada_em"),
        "cancelada_por": venda.get("cancelada_por"),
        # O travão, para o ecrã o poder MOSTRAR em vez de o guardar só na
        # memória do browser: até aqui o POS só sabia da emissão incerta pelo
        # 503 que tinha acabado de receber, e dois toques (um F5, a tela de
        # descanso, o browser a ir abaixo) apagavam essa memória — a conta
        # voltava a parecer normal e a operadora continuava a picar por cima
        # de uma fatura que podia ter saído. Agora vem do SERVIDOR em todas
        # as respostas de venda.
        "emissao_por_confirmar": emissao_por_confirmar,
        "totais": _totais(venda),
    }


@router.post("/pos/venda", status_code=201)
async def abrir_venda(dados: PedidoNovaVenda, operador: Dict = Depends(operador_atual)) -> dict:
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    venda = {
        "id": str(uuid.uuid4()),
        "loja_id": operador["loja_id"],
        "caixa_id": dados.caixa_id,
        "sessao_id": sessao["id"],
        "operador_id": operador.get("operador_id"),
        # Do TOKEN, nunca do corpo — como tudo o resto neste módulo. É o que
        # dá a `GET /pos/venda/aberta` o segundo âmbito que lhe faltava: ver
        # a docstring dessa rota, e `pos_auth.py::entrar`, que põe o
        # `dispositivo_id` no token do operador.
        "dispositivo_id": operador.get("dispositivo_id"),
        "linhas": [],
        # A versão do array `linhas`: sobe a cada alteração e é exigida no
        # filtro de quem escreve (ver `_aplicar_as_linhas`). Sempre presente,
        # como os outros campos deste documento — uma conta anterior a este
        # campo casa com `None` e a primeira alteração põe-lhe a 1.
        "linhas_versao": 0,
        "desconto_global_pct": None,
        "desconto_global_eur": None,
        "estado": "aberta",
        "criada_em": _agora(),
    }
    await db[COLECOES["vendas"]].insert_one(dict(venda))
    return _venda_publica(venda)


# Declarada ANTES de todas as rotas com {venda_id}: o FastAPI serve a
# PRIMEIRA rota que casa com o caminho, e uma `GET /pos/venda/{venda_id}`
# acrescentada acima desta engolia "aberta" como se fosse um id de venda — a
# operadora apanhava um 404 e voltava a picar a conta toda. Deixou de ser uma
# precaução hipotética: essa rota existe agora (`obter_venda`, no FIM deste
# ficheiro), e é só esta ordem que as separa — as duas casam com um caminho de
# três segmentos, e a de `{venda_id}` casa com QUALQUER um. Provado em
# test_venda.py, no router montado de verdade.
@router.get("/pos/venda/aberta")
async def venda_aberta(
    caixa_id: str, operador: Dict = Depends(operador_atual)
) -> Optional[dict]:
    """A conta em curso deste PC — ou `null`, se não houver nenhuma.

    Sem isto, `POST /pos/venda` era a única entrada e criava SEMPRE uma conta
    nova: a tela de descanso ao fim de 5 minutos, um F5 no PC da loja ou um
    browser que vai abaixo faziam a operadora perder o que já tinha picado
    (com o cliente à frente) e deixavam para trás uma venda `aberta` órfã em
    fat_vendas por cada recarregamento, para sempre.

    O âmbito é a sessão aberta da caixa **e o dispositivo**, e NÃO o operador
    — as duas coisas são decisões, não esquecimentos:

    - Não é o operador, porque ao balcão a conta é do posto, não da pessoa.
      Se a Rafaela picar três artigos e a Ana entrar a seguir com o PIN dela
      (a tela de descanso caiu, é o cliente que está à espera), a conta tem de
      continuar lá. Quem fez a venda continua registado em `operador_id`.
    - É também o dispositivo, porque a sessão de caixa sozinha não chega. Uma
      loja com UMA caixa e dois PCs emparelhados (o "PC Balcão" e o "PC
      Drive-Thru" — é para isso que o `nome` do dispositivo existe, e
      `caixa.estado_caixa` resolve automaticamente essa única caixa para os
      dois) tinha os dois PCs a recuperar a MESMA conta: o cliente do balcão
      pagava o açaí do drive-thru. Não era uma corrida de milissegundos — era
      o estado estável dessa configuração, o dia inteiro.

    Sem sessão aberta, o 409 de `_sessao_aberta` está certo: sem caixa aberta
    não há conta nenhuma para recuperar. Sem venda aberta, 200 com `null` —
    é o estado normal do início do dia, não um erro.
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, caixa_id)

    # A MAIS RECENTE. Uma sessão pode ter várias contas abertas ao mesmo
    # tempo (o `POST /pos/venda` cria sempre uma nova, e as órfãs de antes
    # desta rota continuam lá); a que a operadora tem à frente é sempre a
    # última que abriu, nunca a primeira que o Mongo calhar devolver.
    #
    # `dispositivo_id` vem do token (pos_auth.py::entrar), nunca da query.
    #
    # Um token emitido ANTES desta alteração não o traz, e as vendas abertas
    # com ele também não têm o campo. Filtrar por `None` casa, no Mongo, com
    # o campo AUSENTE e com o campo a `null` — é a semântica da igualdade a
    # null, e é o que faz esta mudança não precisar de migração nenhuma:
    # token antigo só encontra conta antiga, token novo só encontra conta
    # nova, e os dois nunca se cruzam. Não é suposição: os quatro
    # cruzamentos estão provados em test_venda.py.
    abertas = await (
        db[COLECOES["vendas"]]
        .find({
            "sessao_id": sessao["id"],
            "estado": "aberta",
            "dispositivo_id": operador.get("dispositivo_id"),
        })
        .sort("criada_em", -1)
        .to_list(1)
    )
    if not abertas:
        return None

    # Mesmo formato de `_venda_publica` (com `totais`) das outras rotas: o
    # ecrã não pode ter dois formatos diferentes da mesma conta, um para
    # quando a abre e outro para quando a recupera.
    #
    # É a ÚNICA rota de venda que tem mesmo de ir perguntar pelo travão à
    # base de dados, e é a que mais precisa dele: é por aqui que o ecrã
    # recupera a conta depois da tela de descanso, de um F5 ou de o browser
    # ir abaixo — precisamente os três acidentes que apagavam do browser a
    # memória de que a emissão desta conta ficou por confirmar.
    conta = abertas[0]
    return _venda_publica(conta, emissao_por_confirmar=await _emissao_por_confirmar(db, conta))


async def _carimbar_sai_na_fatura(
    db, opcoes: List[Dict], preservar_carimbo: bool = False
) -> List[Dict]:
    """Tira o retrato do `sai_na_fatura` de cada grupo referenciado em
    `opcoes`, pela mesma razão que a linha já guarda `produto_preco`: o
    gestor pode desligar o interruptor amanhã, e o que saiu no papel não
    muda. Sem isto, o título de uma fatura reimpressa mudava consoante a
    configuração de hoje.

    Partilhada por `juntar_linha` (a linha nasce) e por `editar_linha`
    quando o pedido reenvia `opcoes` (a linha é reescrita do zero) — as
    DUAS escritas que decidem o conteúdo de `opcoes`. Antes desta função
    existir, só `juntar_linha` carimbava: `editar_linha` aplicava o delta
    em cru (`alvo.update(alteracoes)`) sem voltar a consultar os grupos, e
    uma edição que reenviasse as opções de uma linha já gravada — como
    `PosDialogoProduto.js` faz sempre que reabre uma linha — apagava o
    carimbo. Um "Levar" de um grupo com `sai_na_fatura=False` reaparecia
    no título e na Fatura Simplificada real, que é exactamente o que o
    interruptor existe para impedir.

    **`preservar_carimbo` é o que faz do retrato um retrato.** Sem ele, uma
    edição voltava a LER a configuração de hoje e escrevia por cima do
    carimbo tirado quando a linha nasceu: bastava o gestor ligar o
    interruptor do grupo entre a gravação e a correcção da linha para o
    "Levar" grátis voltar ao título e à Fatura Simplificada — o retrato
    prometido aqui em cima não era retrato nenhum, era a configuração de
    hoje outra vez. É o mesmo raciocínio do `produto_preco`: numa edição,
    uma opção que JÁ TRAZ o carimbo mantém o que trouxe, e só uma opção
    NOVA (uma que a operadora acabou de escolher) é que o vai buscar à
    configuração actual.

    Como se distingue uma da outra: os dois diálogos do POS abrem com as
    opções TAL COMO O SERVIDOR AS DEVOLVEU (`linha.opcoes`, já carimbadas),
    e só as opções em que a operadora toca é que são construídas de raiz —
    `{id, grupo_id, nome, preco}`, sem `sai_na_fatura`
    (`PosPedidoGuiado.juntarDose`, `PosPersonalizacoes.tocar`). A presença
    da chave é, por isso, exactamente a pergunta "esta opção já vinha da
    linha?".

    O que isto custa, dito por inteiro: numa EDIÇÃO passamos a aceitar o
    carimbo que o cliente reenvia. Quem falasse à rota à mão podia esconder
    do título uma opção GRÁTIS (ou mostrar uma que o gestor escondeu) — o
    mesmo que o interruptor do gestor faz, e nunca um cêntimo: uma opção com
    preço sai no título de qualquer maneira (`precos._descricao_das_opcoes`).
    Ao NASCER a linha não se preserva nada — todas as opções são novas, e o
    carimbo vem sempre da configuração, que também é o que impede uma linha
    de nascer com um carimbo inventado pelo cliente."""
    # `isinstance(..., bool)` e não `"sai_na_fatura" in o`: só um booleano a
    # sério é um carimbo. Um `None` (ou um `"false"` em texto) vindo de um
    # cliente distraído não diz nada sobre o grupo, e aceitá-lo como carimbo
    # era gravar "escondido" — ou "visível" — por engano; sem carimbo válido,
    # a opção vai à configuração como qualquer outra opção nova.
    def falta_carimbo(o: Dict) -> bool:
        return not (preservar_carimbo and isinstance(o.get("sai_na_fatura"), bool))

    grupos_da_linha = {}
    ids = [o.get("grupo_id") for o in opcoes if o.get("grupo_id") and falta_carimbo(o)]
    if ids:
        for g in await db[COLECOES["grupos_personalizacao"]].find(
            {"id": {"$in": ids}}, {"_id": 0, "id": 1, "sai_na_fatura": 1}
        ).to_list(len(ids)):
            grupos_da_linha[g["id"]] = g.get("sai_na_fatura", True)

    carimbadas = []
    for o in opcoes:
        o = dict(o)
        if falta_carimbo(o):
            o["sai_na_fatura"] = grupos_da_linha.get(o.get("grupo_id"), True)
        # Senão fica o carimbo que a opção já trazia, tal e qual — é o
        # retrato do dia em que a linha nasceu.
        carimbadas.append(o)
    return carimbadas


@router.post("/pos/venda/{venda_id}/linhas", status_code=201)
async def juntar_linha(
    venda_id: str, dados: PedidoJuntarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    produto = await db[COLECOES["produtos"]].find_one({"id": dados.produto_id}, {"_id": 0})
    if not produto:
        raise HTTPException(status_code=404, detail=_MSG_PRODUTO_INEXISTENTE)

    # A regra que não se negoceia (brief da Task 2): sem preço/IVA no
    # PRÓPRIO produto do catálogo, nem entra na conta — independentemente de
    # a operadora vir a dar um override a seguir. Reaproveita a mesma função
    # que já avisa disto no ecrã "Produtos sem IVA" do catálogo.
    erros = erros_do_produto(produto)
    if erros:
        raise HTTPException(status_code=422, detail="; ".join(erros))

    opcoes = await _carimbar_sai_na_fatura(db, dados.opcoes)

    linha = {
        "id": str(uuid.uuid4()),
        "produto_id": produto["id"],
        "produto_nome": produto.get("nome"),
        "produto_preco": produto.get("preco"),
        "produto_tax_id": produto.get("tax_id"),
        # O quarto campo do retrato, gravado no momento em que a linha nasce
        # como os três de cima: é ele que sai para o Vendus como `id` da
        # linha e evita que cada venda crie lá um produto novo (ver
        # `precos.id_vendus_do_produto`). Um produto criado à mão no nosso
        # backoffice não tem `vendus_ref` — fica `None` aqui e a linha sai
        # sem `id`, que é o caso normal e não um erro: recusar a venda por
        # causa disto deixava a operadora com o cliente à frente sem poder
        # cobrar.
        "produto_vendus_ref": produto.get("vendus_ref"),
        "quantidade": dados.quantidade,
        "opcoes": opcoes,
        "respostas_texto": [r.model_dump() for r in dados.respostas_texto],
        "preco_override": dados.preco_override,
        "tax_override": dados.tax_override,
        "desconto_pct": dados.desconto_pct,
        "desconto_eur": dados.desconto_eur,
    }
    _linha_vendus(linha)  # valida (levanta 422 antes de gravar, se algo bater mal)

    # A linha (com o `id` dela) constrói-se UMA vez, fora do ciclo: uma
    # repetição por conta alterada volta a juntá-la à conta relida, nunca cria
    # uma linha nova. E se dois toques no mesmo produto se cruzarem, ficam as
    # DUAS linhas — que é o que a operadora pediu, e o que já acontecia quando
    # os pedidos chegavam em fila; antes desta correcção uma delas era
    # silenciosamente apagada pela outra.
    def juntar(conta):
        return list(conta.get("linhas") or []) + [linha]

    return _venda_publica(
        await _aplicar_as_linhas(db, venda_id, operador["loja_id"], juntar, venda)
    )


@router.put("/pos/venda/{venda_id}/linhas/{linha_id}")
async def editar_linha(
    venda_id: str, linha_id: str, dados: PedidoEditarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    alteracoes = dados.model_dump(exclude_unset=True)
    if alteracoes.get("opcoes") is not None:
        # Mesmo carimbo do `juntar_linha` (ver `_carimbar_sai_na_fatura`):
        # sem isto, reenviar `opcoes` numa edição perdia o `sai_na_fatura`
        # que a linha já tinha, porque o `alvo.update(alteracoes)` abaixo
        # grava o delta em cru. `None` explícito (limpar as opções) não
        # entra aqui — não há grupo nenhum para consultar.
        #
        # `preservar_carimbo=True`, e é o que distingue esta escrita da do
        # `juntar_linha`: aqui a linha JÁ EXISTE, e uma opção que volta com
        # o carimbo que levou fica com esse — não com o que a configuração
        # do grupo diz hoje. Só as opções novas (as que a operadora acabou
        # de escolher, e que chegam sem a chave) é que a vão consultar.
        alteracoes["opcoes"] = await _carimbar_sai_na_fatura(
            db, alteracoes["opcoes"], preservar_carimbo=True
        )

    if alteracoes.get("respostas_texto") is not None:
        # O `exclude_unset=True` propaga-se aos modelos ANINHADOS: uma
        # resposta que chegue sem `nome_grupo` sai deste `model_dump` sem a
        # chave, e a linha ficava com um `respostas_texto` de forma
        # diferente do que o `juntar_linha` grava (esse faz `r.model_dump()`
        # por resposta, sempre com os três campos). O mesmo campo com duas
        # formas conforme a escrita por onde passou — e quem a leia pela
        # chave (o talão da cozinha há-de fazê-lo, é a promessa da docstring
        # do `RespostaTexto`) apanha um `KeyError` só nas linhas que passaram
        # por uma edição, e não nas outras: o tipo de defeito que aparece
        # numas linhas e não noutras e que ninguém consegue repetir. Um
        # `model_dump()` sem `exclude_unset` por resposta devolve a MESMA
        # forma das duas vezes, com o `nome_grupo` a None quando não foi dado.
        alteracoes["respostas_texto"] = [r.model_dump() for r in dados.respostas_texto]

    # A edição é um DELTA (só os campos presentes no pedido) e aplica-se à
    # linha como ela está na conta relida — nunca à cópia que a rota leu à
    # entrada. Se a linha desapareceu entretanto (outro sítio removeu-a), é
    # 404 e não se ressuscita nada.
    def editar(conta):
        linhas = list(conta.get("linhas") or [])
        alvo = next((li for li in linhas if li["id"] == linha_id), None)
        if alvo is None:
            raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)
        candidata = dict(alvo)
        candidata.update(alteracoes)
        _linha_vendus(candidata)  # valida a versão editada ANTES de gravar
        alvo.update(alteracoes)
        return linhas

    return _venda_publica(
        await _aplicar_as_linhas(db, venda_id, operador["loja_id"], editar, venda)
    )


@router.delete("/pos/venda/{venda_id}/linhas/{linha_id}")
async def remover_linha(
    venda_id: str, linha_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    def remover(conta):
        linhas = list(conta.get("linhas") or [])
        restantes = [li for li in linhas if li["id"] != linha_id]
        if len(restantes) == len(linhas):
            raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)
        return restantes

    return _venda_publica(
        await _aplicar_as_linhas(db, venda_id, operador["loja_id"], remover, venda)
    )


@router.put("/pos/venda/{venda_id}/desconto")
async def aplicar_desconto_global(
    venda_id: str, dados: PedidoDescontoGlobal, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    atualizacao = {
        "desconto_global_pct": dados.desconto_pct,
        "desconto_global_eur": dados.desconto_eur,
    }
    venda.update(atualizacao)
    await _escrever_se_ainda_aberta(db, venda_id, atualizacao)
    return _venda_publica(venda)


@router.post("/pos/venda/{venda_id}/cancelar")
async def cancelar_venda(venda_id: str, operador: Dict = Depends(operador_atual)) -> dict:
    """Deita fora uma conta aberta: o cliente desistiu, ou a operadora
    começou a picar na caixa errada.

    Passa-a a `cancelada`, e é isso que a tira da frente — deixa de ser
    devolvida por `GET /pos/venda/aberta` e nenhuma rota deste módulo volta a
    aceitar alterações nela (`_garante_aberta`).

    Só se cancela o que está ABERTO. Uma venda `emitida` tem uma Fatura
    Simplificada REAL entregue à AT: mudar-lhe o estado à socapa apagava do
    nosso sistema um documento que continua a existir lá fora — isso
    corrige-se com uma nota de crédito, nunca aqui. Cancelar uma já
    cancelada cai no mesmo 409 de propósito: a idempotência não interessa a
    ninguém ao balcão, mas dizer à operadora que aquela conta já estava
    cancelada interessa.

    **"Aberta" não chega para decidir isto.** A emissão reserva em
    `fat_refs_fiscais` ANTES de falar com o Vendus (`fiscal.py::_reservar`) e
    só marca a venda `emitida` no fim — enquanto essa reserva existir, uma
    venda que diz `aberta` pode ter uma Fatura Simplificada real a nascer, ou
    já nascida e por confirmar. Eram dois estragos concretos:

    - A operadora carrega em FINALIZAR, a emissão fica à espera do Vendus, e
      ela carrega em Cancelar. Respondia-se "cancelada" — e a seguir o
      `_gravar_documento` punha `emitida` por cima (o $set dele não tem
      condição de estado nenhuma). Ela foi informada de que a conta tinha
      sido deitada fora enquanto saía uma FS com ATCUD, voltava a picar
      tudo, e o cliente levava DUAS faturas.
    - Pior: o Vendus dá timeout, a verificação também falha, e a reserva fica
      `incerta` com a venda `aberta` (é o desenho — ver
      VerificacaoFiscalIncerta). É essa conta que aparece como "conta em
      curso"; cancelá-la fazia desaparecer a última venda `aberta` ligada a
      uma FS que pode ter saído mesmo: o Z fecha curto
      (`caixa_math.soma_vendas_dinheiro` só soma as `emitida`) e a reserva
      incerta fica presa para sempre, só resolúvel com Mongo à mão.

    Por isso: reserva presente → 409 e o gestor. Nunca um "tente novamente",
    que só convidava a operadora a carregar outra vez no mesmo botão.
    """
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    await _garante_sem_emissao(db, venda_id)

    # A escrita é CONDICIONADA a {"estado": "aberta"} — a mesma técnica de I2
    # em caixa.py, e aqui pela pior das razões: entre o `_garante_aberta`
    # acima e esta linha, o `finalizar` (fiscal.py) pode ter emitido esta
    # mesma venda. Um $set incondicional carimbava "cancelada" por cima de
    # uma venda que ACABOU de receber uma Fatura Simplificada real, e ela
    # sumia-se do fecho de caixa (`caixa_math.soma_vendas_dinheiro` só soma
    # as `emitida`): o dinheiro ficava na gaveta sem nada que o explicasse.
    # É o `matched_count`, não a leitura de cima, que decide esta corrida.
    #
    # `cancelada_por` fica gravado com o MESMO `_quem` do resto do módulo
    # (caixa.py, reutilizado e não reescrito): sem ele, o único nome na venda
    # era o `operador_id` de quem a ABRIU. A Rafaela abria e picava 24 €, a
    # Ana entrava com o PIN dela e cancelava, e ficava lá o nome da Rafaela —
    # a atribuição não estava só ausente, estava ERRADA, no vector de fraude
    # mais banal que há ao balcão (picar, receber o dinheiro, cancelar a
    # conta).
    atualizacao = {
        "estado": "cancelada",
        "cancelada_em": _agora(),
        "cancelada_por": _quem(operador),
    }
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)

    # A janela que a verificação lá de cima não fecha: entre ela e a escrita
    # acima, o `finalizar` pode ter reservado. Por isso pergunta-se OUTRA VEZ,
    # depois de escrever — e, se entretanto apareceu uma reserva, desfaz-se o
    # cancelamento.
    #
    # É uma compensação, não uma transacção (não temos transacções
    # multi-documento aqui), e é segura por três razões:
    # 1. A escrita é condicionada a {"estado": "cancelada"} — o único estado
    #    que a NOSSA escrita pode ter deixado. Se o `_gravar_documento` já
    #    tiver posto `emitida` por cima dela (o $set dele é incondicional),
    #    o filtro não casa e não lhe tocamos: uma compensação incondicional
    #    ressuscitava como `aberta` uma venda com FS real e ATCUD, que é
    #    precisamente o estrago que este código existe para evitar.
    # 2. Ninguém mais neste módulo escreve "cancelada", por isso a conta que
    #    reabrimos é a que nós próprios acabámos de fechar.
    # 3. `aberta` é o estado em que ela estava um segundo antes, e nada se
    #    perde: os carimbos do cancelamento voltam a `None` na mesma escrita.
    #
    # Em qualquer dos desfechos a operadora ouve o MESMO 409 — a conta não
    # foi cancelada, e é isso que ela precisa de saber antes de mexer em mais
    # alguma coisa. (No desfecho raro em que a venda já ficou `emitida`, os
    # carimbos do cancelamento ficam colados a ela; ficam à VISTA em
    # `_venda_publica`, e a venda conta como emitida no Z, que é o que
    # fiscalmente interessa — nenhuma escrita nossa pode limpá-los sem voltar
    # a correr o risco de mexer num documento fiscal real.)
    if await _tem_reserva_fiscal(db, venda_id):
        await db[COLECOES["vendas"]].update_one(
            {"id": venda_id, "estado": "cancelada"},
            {"$set": {"estado": "aberta", "cancelada_em": None, "cancelada_por": None}},
        )
        raise HTTPException(
            status_code=409, detail=await _porque_nao_foi_cancelada(db, venda_id)
        )

    venda.update(atualizacao)
    return _venda_publica(venda)


async def _documento_da_venda(db, venda_id: str) -> Optional[Dict]:
    """O documento fiscal desta venda, como o ecrã o mostra — ou `None`
    quando ainda não existe nenhum (conta `aberta`, ou `cancelada`), o que
    não é erro nenhum.

    A selecção de campos é a de `fiscal.py::_resposta_documento`,
    REUTILIZADA e não copiada: uma segunda cópia divergia no dia em que o
    documento ganhasse (ou perdesse) um campo, e o ecrã passava a mostrar
    coisas diferentes conforme tivesse chegado ao documento pela resposta do
    `finalizar` ou por esta releitura — sendo que a releitura é exactamente o
    caminho de quem NÃO chegou a ver a resposta do `finalizar`. O `modo` faz
    parte dessa selecção de propósito: um documento emitido em `tests` não
    tem valor fiscal nenhum, e o ecrã tem de o avisar.

    **A importação é local a esta função, e não no topo do módulo**, por um
    ciclo real e não teórico: `fiscal.py` importa oito nomes daqui
    (`_venda_publica`, `_totais`, `_obter_venda_da_loja`, ...). Um
    `from .fiscal import _resposta_documento` lá em cima rebentava o arranque
    do módulo com ImportError, seja qual for o dos dois que entre primeiro —
    quem começa fica meio construído em sys.modules, e o outro vai lá buscar
    nomes que ainda não existem. Adiada para dentro da função, corre com os
    dois módulos já inteiros. É a mesma razão pela qual `_tem_reserva_fiscal`
    pergunta pelo `venda_id` em vez de importar a `ext_ref_determinista`.

    A pergunta é pelo `venda_id` — o campo que `fiscal.py::_gravar_documento`
    grava em todo o documento — e não pelo `documento_id` que a venda passa a
    ter: são duas escritas separadas (`_ligar_venda_ao_documento`), e a conta
    que fica pelo meio delas (documento fiscal gravado, venda ainda `aberta`
    e sem `documento_id`, porque o processo morreu entre as duas) é
    precisamente uma das que alguém vai querer reler aqui.
    """
    from .fiscal import _resposta_documento

    documento = await db[COLECOES["documentos"]].find_one({"venda_id": venda_id})
    if documento is None:
        return None
    return _resposta_documento(documento)


# Declarada no FIM do ficheiro, DEPOIS de `GET /pos/venda/aberta` — ver o
# comentário dessa rota. Esta casa com qualquer caminho de três segmentos,
# "aberta" incluído; acima dela, a operadora perdia a conta em curso e
# apanhava um 404.
@router.get("/pos/venda/{venda_id}")
async def obter_venda(venda_id: str, operador: Dict = Depends(operador_atual)) -> dict:
    """Relê uma venda pelo id, em QUALQUER estado — e com o documento fiscal,
    quando já existe.

    É a metade que falta ao pior defeito do ecrã do POS. A operadora carrega
    em EMITIR; o pedido chega ao servidor, a Fatura Simplificada SAI mesmo, e
    a resposta perde-se (o Wi-Fi do balcão pisca, ou o proxy corta aos 30 s
    porque o Vendus demorou). Ela carrega outra vez, apanha o 409 de "esta
    venda já foi emitida" — e fica sem nada: sem talão (o agente de impressão
    ainda não existe), sem número nem ATCUD no ecrã, e com a conta esvaziada
    por um aviso que passa. O gesto natural a seguir é picar tudo outra vez, e
    sai uma SEGUNDA Fatura Simplificada REAL, que a idempotência do servidor
    não apanha — é uma venda nova, com uma referência nova. Com esta rota, o
    ecrã vai buscar a venda pelo id que já tem em mãos e mostra o documento
    que saiu.

    `GET /pos/venda/aberta` não serve para isto, e é por desenho: filtra
    `estado: "aberta"` e devolve `null` assim que a venda passa a `emitida` —
    que é exactamente o caso a tratar. Daí o "em qualquer estado": `emitida` é
    o caso central, `cancelada` responde à outra pergunta da operadora ("a
    conta foi mesmo deitada fora?"), e `aberta` é a conta que ela tinha à
    frente.

    O âmbito é o de sempre, `_obter_venda_da_loja`: a venda tem de ser da loja
    do token, e a de outra loja é 404 como em todo o módulo — reler não é uma
    permissão mais fraca do que escrever, e este id vem do browser.

    Não escreve nada, por isso não há aqui travão nenhum a fazer cumprir: o
    `emissao_por_confirmar` vem na resposta porque é ele que diz ao ecrã que
    esta conta está congelada, mas quem o impõe continuam a ser as cinco rotas
    de escrita (`_garante_sem_emissao`).
    """
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    resposta = _venda_publica(
        venda, emissao_por_confirmar=await _emissao_por_confirmar(db, venda)
    )
    # A chave está SEMPRE presente, mesmo a `None` — mesma regra do
    # `emissao_por_confirmar` e do `cancelada_em`: o ecrã não pode ter de
    # adivinhar se a ausência quer dizer "esta venda não tem documento" ou
    # "esta versão da API não sabe responder a isso". E a diferença aqui não é
    # cosmética: é entre mostrar o número da fatura que saiu e mandar a
    # operadora picar tudo outra vez.
    resposta["documento"] = await _documento_da_venda(db, venda_id)
    return resposta
