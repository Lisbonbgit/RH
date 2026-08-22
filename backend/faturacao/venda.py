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
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from .caixa import _obter_caixa_da_loja, _quem, _sessao_aberta
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais, erros_do_produto, linha_de_venda
from .reparticao import CASAS_DA_QUANTIDADE, quantidade_para, repartir_centimos

logger = logging.getLogger(__name__)

router = APIRouter()

_MSG_VENDA_INEXISTENTE = "Venda não encontrada."
_MSG_VENDA_NAO_ABERTA = "Esta venda já foi emitida ou cancelada — não aceita alterações."
# Uma conta DIVIDIDA está travada como uma emitida, mas por outra razão e com
# outra saída: a operadora não tem nenhuma fatura para procurar, tem partes
# para cobrar. O genérico mandava-a olhar para o Vendus à procura de um
# documento que não existe.
_MSG_VENDA_SEPARADA = (
    "Esta conta foi dividida; quem emite são as partes. Mexa em cada parte, "
    "não nesta — alterar a conta original punha as partes a faturar linhas "
    "que já não existem. Uma parte que ninguém pague cancela-se."
)
_MSG_CONTA_VAZIA_NAO_SE_DIVIDE = (
    "Esta conta ainda não tem nada — não há o que dividir. Pique primeiro o "
    "que o cliente leva."
)
# `separar_conta` (achado da revisão): uma parte cujas linhas somam 0,00 €
# nasceria `aberta` para sempre — `fiscal.finalizar` recusa um total que não
# seja positivo (`_MSG_TOTAL_NAO_POSITIVO`, fiscal.py) e a única saída é
# cancelar, não fechar. Recusa-se aqui, antes de gravar nada.
_MSG_PARTE_SEM_VALOR = (
    "Uma das partes não leva nenhum artigo com valor — ficaria aberta para "
    "sempre, sem forma de gerar fatura. Junte-lhe pelo menos um artigo com "
    "preço, ou junte-a a outra parte."
)
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
# As duas da SESSÃO (ver `_garante_sessao_desta_venda_aberta`). São duas e não
# uma porque a saída que a operadora tem à frente é diferente em cada uma —
# a mesma distinção que o núcleo fiscal já faz no FINALIZAR
# (`fiscal.py::SessaoEmFechoAgora`), com as palavras de quem está a PICAR e
# não a cobrar: aqui não há Fatura Simplificada nenhuma em jogo, só uma conta
# que ela está a tentar mudar.
_MSG_SESSAO_A_FECHAR_AGORA = (
    "A caixa desta conta está a FECHAR o turno neste momento — o Z está a ser "
    "calculado e, enquanto isso, esta sessão não aceita alterações às contas. "
    "Nada foi gravado: a conta continua aqui, tal como está. Espere alguns "
    "segundos e repita — um fecho demora um instante."
)
# Um fecho FEITO. O Z já está assinado e leva lá dentro esta conta, com o
# valor que ela tinha (`caixa.py::_contas_abertas_da_sessao`): mudá-la agora
# punha o retrato assinado a discordar da base de dados, e ninguém volta a
# olhar para a sessão depois do fecho para dar por isso.
_MSG_SESSAO_JA_FECHADA = (
    "A caixa desta conta já fechou o turno — o Z está assinado e esta conta "
    "ficou lá registada tal como está. Um turno fechado não aceita alterações "
    "às contas dele: se o cliente ainda quer levar, pique numa conta nova na "
    "caixa que está aberta agora; se esta conta já não vai ser paga, é o "
    "gestor que a arruma."
)
# O choque de duas alterações à MESMA conta (ver `_aplicar_as_linhas`). Não é
# um erro para chamar o gestor — é uma conta que mudou por baixo e que se relê.
_MSG_CONTA_MUDOU_DEBAIXO = (
    "Esta conta foi alterada noutro sítio ao mesmo tempo (outro separador do "
    "POS, ou o ecrã recarregado a meio) e esta alteração não foi gravada, "
    "para não apagar a outra. Olhe para a conta como ela está agora e repita "
    "só o que faltar."
)
# O mesmo choque, mas na DIVISÃO (ver `_a_mae_como_foi_lida`). Mensagem
# própria e não a de cima porque a saída é outra: nada foi gravado e não há
# "só o que faltar" para repetir — a divisão não é um delta sobre a conta, é
# uma decisão sobre a conta INTEIRA, e essa toma-se outra vez a olhar para ela
# como ela está agora (podem ter aparecido linhas, ou um desconto que muda o
# que cada pessoa paga).
_MSG_CONTA_MUDOU_ANTES_DE_DIVIDIR = (
    "Esta conta foi alterada noutro sítio ao mesmo tempo (outro separador do "
    "POS, ou o ecrã recarregado a meio) e a divisão NÃO foi feita — não ficou "
    "nada gravado. Veja a conta como ela está agora e divida outra vez."
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
# As duas mensagens da DIVISÃO DESFEITA (ver `_porque_nao_ficou_dividida`) — a
# mesma disciplina das duas de cima, com as palavras da divisão. As do
# cancelamento não servem aqui: a operadora carregou em DIVIDIR, e ouvir "esta
# conta NÃO foi cancelada" mandava-a procurar um cancelamento que ninguém pediu.
_MSG_DIVISAO_EMITIDA_ENTRETANTO = (
    "Esta conta NÃO foi dividida: a fatura saiu mesmo, mesmo agora — a Fatura "
    "Simplificada da conta INTEIRA está entregue à Autoridade Tributária, e as "
    "partes que estavam a nascer foram apagadas. Uma venda faturada não se "
    "divide; o que estiver errado nela corrige-se com uma nota de crédito."
)
_MSG_DIVISAO_ABORTADA_SEM_EMISSAO = (
    "Esta conta NÃO foi dividida: estava a decorrer uma emissão, que "
    "entretanto foi abortada sem chegar a emitir — NÃO saiu nenhuma Fatura "
    "Simplificada e a conta está outra vez aberta e inteira. Divida outra vez."
)
# A recusa de `abrir_venda` (ver `_contas_do_balcao`). Diz o que ela tem de
# fazer, e diz as DUAS saídas — cobrar e cancelar — porque a conta que está a
# prender o posto tanto pode ser um cliente que ainda vai pagar como um que
# desistiu. As partes de uma conta dividida contam: uma conta dividida só acaba
# quando TODAS as partes estiverem cobradas ou canceladas.
#
# **A frase mandava fazer o que não se conseguia, e essa era a metade humana
# do defeito da raiz.** Dizia «A única conta que não conta é a que está
# TRAVADA», e essa excepção era CALCULADA (existe reserva em
# `fat_refs_fiscais`?) e não gravada: deixava de ser verdade no instante em
# que o gestor libertasse a reserva, e a partir daí a conta contava outra vez
# sem que ninguém a visse. Pior: a frase aparecia com o ecrã vazio (depois de
# largar) e aparecia quando o que estava à frente era precisamente a travada
# que ela dizia não contar.
#
# Agora TODAS as contas por resolver deste posto contam — travadas
# incluídas —, e cada uma delas está mesmo à frente da operadora
# (`GET /pos/venda/aberta` devolve a mais recente do MESMO conjunto). Por isso
# a frase pode nomear as três saídas, e as três executam-se com os dedos:
# cobrar, cancelar, ou — só na travada, a única que ela não cobra nem cancela
# — entregá-la ao gestor no botão «Servir o cliente seguinte».
_MSG_CONTA_POR_RESOLVER = (
    "Este posto já tem uma conta por resolver — não se começa a do cliente "
    "seguinte por cima dela. Acabe a que está à frente: cobre-a ou cancele-a. "
    "Se a dividiu, ela só acaba quando todas as partes estiverem cobradas ou "
    "canceladas. E se ela estiver TRAVADA, com uma emissão de fatura por "
    "confirmar — essa não se cobra nem se cancela aqui —, toque em «Servir o "
    "cliente seguinte»: a conta passa a ser do gestor, que a resolve no "
    "backoffice, e o balcão fica livre."
)
# **E DIZ ONDE ELA FICOU**, quando ficou noutra caixa. A frase acima manda
# «acabe a que está à frente», e numa loja com duas caixas activas isso podia
# ser uma instrução impossível: a conta estava à frente noutra caixa e o ecrã
# não a mostrava. Agora mostra (`_contas_do_balcao` é um conjunto só), e a
# recusa acrescenta o nome da caixa — mas SÓ quando é outra: numa loja com uma
# caixa, «ela ficou na caixa Balcão» é ruído sobre a única caixa que existe.
_MSG_CONTA_NOUTRA_CAIXA = (
    " Ela foi aberta na caixa «%s» e é lá que continua — mas está à sua frente "
    "neste ecrã na mesma, e é aqui que a acaba."
)
# O beco que a mudança de chave do índice podia abrir, dito por extenso em vez
# de deixado a 409 mudo. Só se chega aqui se o índice recusar a conta nova e a
# leitura do posto não encontrar nada: uma conta `aberta` de um turno JÁ
# FECHADO que ficou com a etiqueta do posto porque o
# `caixa.py::_largar_o_posto_das_contas_abertas` não conseguiu tirá-la. Não é
# recuperável do balcão — a conta é de um turno fechado e é do gestor —, por
# isso a frase manda-a para quem a consegue arrumar, e diz onde.
_MSG_ETIQUETA_PRESA = (
    "Este PC ficou com uma conta por arrumar de um turno JÁ FECHADO, e é ela "
    "que está a impedir a conta nova. Não se resolve aqui: peça ao gestor para "
    "a arrumar no backoffice, em «Contas por cobrar de turnos fechados». "
    "Assim que ele o fizer, este posto volta a abrir contas — não é preciso "
    "reiniciar nada."
)
# **O MESMO beco, mas com o turno a MEIO de um fecho — e aí a frase de cima é
# falsa duas vezes.** O turno não está "já fechado" (está `a_fechar`), e o
# gestor NÃO o consegue arrumar: `caixa.arrumar_conta_esquecida` recusa
# precisamente com a sessão nesse estado, porque o Z está a somar a lista onde
# esta conta entra. Medido pelas rotas reais, com a caixa-1 a meio de um fecho
# e o mesmo PC a atender na caixa-2: `POST /pos/venda` -> 409
# `_MSG_ETIQUETA_PRESA` («peça ao gestor»), e `POST
# /caixa/contas-esquecidas/{id}/arrumar` -> 409 («a caixa está a FECHAR o turno
# neste momento»). As duas saídas nomeadas eram inexecutáveis, e a única que
# funciona — voltar a carregar em FECHAR CAIXA naquela caixa — não era nomeada
# por nenhuma delas.
#
# Na janela normal de um fecho isto dura milissegundos. **Num fecho que morra a
# meio — o caso para que `caixa._sessao_por_fechar` existe — é PERMANENTE**, e
# a etiqueta só é largada depois do Z estar escrito
# (`caixa._largar_o_posto_das_contas_abertas`). Por isso a recusa passa a
# escolher-se pelo estado da SESSÃO da conta que tem a etiqueta, e a nomear o
# gesto que a desfaz. O nome da caixa entra na frase: quem está ao balcão tem
# de saber QUAL fechar, e o PC pode estar a atender noutra.
_MSG_ETIQUETA_PRESA_COM_FECHO_A_MEIO = (
    "Este PC ficou com uma conta de um turno cujo fecho ficou a MEIO — o Z da "
    "caixa «%s» nunca chegou a sair, e é essa conta que está a impedir a conta "
    "nova. Resolve-se aqui e agora, sem chamar ninguém: escolha a caixa «%s» "
    "neste PC e carregue outra vez em FECHAR CAIXA para concluir esse turno. "
    "Assim que o Z sair, este posto volta a abrir contas."
)
# `POST /pos/venda/{id}/entregar-ao-gestor` — as três recusas.
#
# Só a TRAVADA se entrega. Uma conta normal cobra-se ou cancela-se, e deixar
# entregar essa era voltar a ter «pôr uma conta de lado e cobrar outra», que é
# exactamente o que o dono não quer: a marca passaria a ser a porta por onde
# uma conta sai da frente sem ser resolvida.
_MSG_PARTE_NAO_SE_DIVIDE = (
    "Esta conta já é uma PARTE de uma conta dividida — não se volta a dividir. "
    "O ecrã só tem lugar para uma conta repartida de cada vez, e a segunda "
    "levava com ela as pessoas que ainda faltavam cobrar da primeira. Quem não "
    "paga a sua parte cancela-a; o resto cobra-se."
)
_MSG_ENTREGAR_SO_A_TRAVADA = (
    "Esta conta não está travada — não há nada para entregar ao gestor. Uma "
    "conta normal acaba aqui: cobre-a ou cancele-a. Só a conta com uma "
    "emissão de fatura por confirmar é que passa para o gestor, porque é a "
    "única que a operadora não consegue fechar."
)
_MSG_ENTREGAR_DE_OUTRO_POSTO = (
    "Esta conta não é deste posto. Cada PC entrega as suas — a de outro "
    "balcão resolve-se lá, ou no backoffice."
)
_MSG_JA_ENTREGUE = (
    "Esta conta já foi entregue ao gestor e não volta ao balcão. Ela fica no "
    "backoffice, na lista das contas por resolver, até ele a arrumar."
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


def _recusa_quantidade_impossivel(v):
    """A quantidade ganha casas decimais para as contas divididas (uma parte
    de três de um açaí é 0.3337), mas não ganha resolução infinita: acima das
    casas que `reparticao` usa, o valor final deixa de ser previsível e o
    crivo passa a esconder o erro em vez de o apanhar. `gt=0` e não `ge=0`
    porque uma linha de quantidade zero não é uma venda — é uma linha que não
    devia existir, e deixá-la entrar dava uma fatura com um artigo a 0,00 €.
    """
    if v is None:
        return v
    if v <= 0:
        raise ValueError("A quantidade tem de ser maior do que zero.")
    casas = repr(float(v)).partition(".")[2]
    if len(casas) > CASAS_DA_QUANTIDADE:
        raise ValueError(
            "A quantidade %s tem mais de %d casas decimais."
            % (v, CASAS_DA_QUANTIDADE)
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
    quantidade: float = 1
    opcoes: List[Dict] = Field(default_factory=list)
    respostas_texto: List[RespostaTexto] = Field(default_factory=list)
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)

    @field_validator("quantidade")
    @classmethod
    def _valida_quantidade(cls, v):
        return _recusa_quantidade_impossivel(v)


class PedidoEditarLinha(BaseModel):
    # Tudo opcional: só os campos PRESENTES no pedido são alterados (lidos
    # com model_dump(exclude_unset=True)) — permite, por exemplo, limpar um
    # preco_override de volta a None sem ter de repetir o resto da linha.
    quantidade: Optional[float] = None
    opcoes: Optional[List[Dict]] = None
    respostas_texto: Optional[List[RespostaTexto]] = None
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)

    @field_validator("quantidade")
    @classmethod
    def _valida_quantidade(cls, v):
        return _recusa_quantidade_impossivel(v)


class PedidoDescontoGlobal(BaseModel):
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)

    @field_validator("desconto_eur")
    @classmethod
    def _valida_eur(cls, v):
        return _recusa_mais_de_2_casas(v)


class PedidoDividir(BaseModel):
    """Por quantas pessoas se divide esta conta.

    `ge=2` porque dividir por uma é não dividir: criava uma filha idêntica à
    mãe e travava a mãe por engano. `le=20` é o tecto de um dedo distraído —
    ninguém divide uma conta de balcão por mais de vinte, e sem tecto um
    `partes: 1000` criava mil vendas de uma vez."""

    partes: int = Field(ge=2, le=20)


class PedidoSepararLinha(BaseModel):
    """Quantas unidades desta linha vão para esta parte — sempre uma FATIA
    da quantidade que já estava na conta, atribuída pelo staff, nunca um
    valor novo.

    **Sempre um número INTEIRO de unidades — e isto é VERIFICADO, não só
    descrito.** Ao contrário do `dividir_conta` (que reparte um VALOR e por
    isso lida com fracções, 0.3337 de um açaí), aqui o staff atribui artigos
    físicos: nunca 0.6 de um açaí para uma pessoa e 1.4 para a outra. Um
    comentário a dizer "não há fracções" sem um crivo a impedi-las já
    escondeu um bloqueador nesta mesma secção do ficheiro — por isso a
    fracção é recusada aqui, com 422, e não silenciosamente aceite."""

    linha_id: str = Field(min_length=1)
    quantidade: float

    @field_validator("quantidade")
    @classmethod
    def _valida_quantidade(cls, v):
        v = _recusa_quantidade_impossivel(v)
        if v is not None and v != int(v):
            raise ValueError(
                "A quantidade %s não é um número inteiro de unidades. Ao "
                "separar a conta atribuem-se artigos inteiros a cada parte — "
                "as fracções ficam para o dividir_conta, que reparte por "
                "VALOR, não por artigo." % v
            )
        return v


class PedidoSepararParte(BaseModel):
    """Uma parte da separação — as linhas que o staff lhe atribuiu.

    **`min_length=1`: uma parte sem nenhuma linha nasce `aberta` a 0,00 €
    e fica presa lá para sempre** (achado da revisão) — `fiscal.finalizar`
    recusa um total que não seja positivo, e a única saída passa a ser
    cancelar, nunca fechar. Uma parte com `linhas: []` não é um erro de
    digitação inofensivo: é uma venda fantasma na lista de contas abertas
    da sessão. Recusada aqui, com 422, antes de chegar a `_partes_da_
    separacao`. (Uma parte cujas linhas somam 0,00 € — só artigos
    oferecidos — passa este crivo mas fica igualmente presa; essa recusa-se
    à frente, em `separar_conta`, depois de se saber o VALOR de cada
    parte.)"""

    linhas: List[PedidoSepararLinha] = Field(min_length=1)


class PedidoSeparar(BaseModel):
    """Quem leva o quê — ao contrário do `PedidoDividir` (que reparte um
    VALOR por N pessoas), aqui é o staff que atribui as linhas, uma a uma,
    a cada parte.

    **`max_length=20`, a MESMA razão do `le=20` no `PedidoDividir`: um dedo
    distraído.** Ninguém separa uma conta de balcão por mais de vinte
    pessoas, e sem tecto um `partes` com centenas de entradas cria
    centenas de vendas de uma só vez (achado da revisão — o comentário
    desta classe dizia "o número de partes é só o comprimento desta lista"
    sem impor nada sobre esse comprimento, a mesma lacuna que a Task 3 já
    tinha fechado com `ge`/`le` no `PedidoDividir`). `min_length=1` porque
    zero partes não separa nada — cairia de qualquer forma no "por
    atribuir" a seguir, mas dizê-lo aqui poupa a viagem até lá."""

    partes: List[PedidoSepararParte] = Field(min_length=1, max_length=20)


async def _obter_venda_da_loja(db, venda_id: str, loja_id: str) -> Dict:
    """Confirma que a venda existe E pertence à loja do operador autenticado
    — mesmo raciocínio de `_obter_caixa_da_loja` em caixa.py: o âmbito nunca
    é só o id."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if not venda or venda.get("loja_id") != loja_id:
        raise HTTPException(status_code=404, detail=_MSG_VENDA_INEXISTENTE)
    return venda


def _garante_aberta(venda: Dict) -> None:
    # `separada` ANTES do genérico: as duas recusam, mas só uma delas diz à
    # operadora o que fazer a seguir (ver `_MSG_VENDA_SEPARADA`).
    if venda.get("estado") == "separada":
        raise HTTPException(status_code=409, detail=_MSG_VENDA_SEPARADA)
    if venda.get("estado") != "aberta":
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)


def _garante_que_nao_e_ja_uma_parte(venda: Dict) -> None:
    """**Uma PARTE não se volta a dividir.** `POST /pos/venda/{id}/dividir`
    sobre uma parte era aceite (201) e criava um SEGUNDO grupo de repartição
    no mesmo posto — e o ecrã só tem lugar para um. O grupo que ficasse de
    fora levava consigo as pessoas por cobrar dele, sem nada no ecrã a
    dizê-lo (é o mesmo defeito que `PosVenda.js::abrirReparticao` já recusa
    do lado do ecrã, e é a rota que o tem de fechar).

    A saída é a de sempre e cabe numa frase: quem não paga a sua parte não a
    subdivide — cancela-se, e cobra-se o resto."""
    if venda.get("conta_mae_id"):
        raise HTTPException(status_code=409, detail=_MSG_PARTE_NAO_SE_DIVIDE)


def _garante_do_balcao(venda: Dict) -> None:
    """**Uma conta ENTREGUE AO GESTOR não volta a ser escrita pelo balcão.**

    A marca (`entregue_ao_gestor_em`) tira a conta dos dois conjuntos do posto
    ao mesmo tempo — a porta de `abrir_venda` e o ecrã de
    `GET /pos/venda/aberta` —, e é isso que faz dela a resposta à raiz. Mas os
    ecrãs do POS desenham-se sem servidor nenhum (regra 3 do cabeçalho): tirar
    a conta do ecrã não impede um pedido feito com o id dela na mão (a nota do
    painel mostra-o, um separador antigo ainda o tem, um bundle velho não sabe
    da marca). Quem recusa é a rota.

    **O `cancelar_venda` NÃO passa por aqui, e é uma decisão.** Cancelar é a
    saída que o GESTOR usa para arrumar exactamente estas contas
    (`caixa.py::arrumar_conta_esquecida` delega nele, para não haver uma
    segunda cópia da disciplina de escrita que lá está). Bloqueá-lo aqui
    deixava a conta entregue sem saída nenhuma — o problema oposto, e o mesmo
    beco que esta ronda veio abrir.

    Também não passa por aqui o `finalizar` (fiscal.py): o núcleo fiscal não
    é sobre de QUEM é a conta, é sobre o que foi facturado, e a conta entregue
    já não chega a nenhum ecrã de onde se possa carregar em EMITIR."""
    if venda.get("entregue_ao_gestor_em"):
        raise HTTPException(status_code=409, detail=_MSG_JA_ENTREGUE)


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


async def _garante_sessao_desta_venda_aberta(db, venda: Dict) -> None:
    """**A sessão de caixa DESTA venda tem de estar aberta para lhe mexer** —
    o mesmo raciocínio (e a mesma pergunta) de
    `fiscal.py::_garante_sessao_da_venda_aberta`, que o `finalizar` faz desde
    o defeito I1, agora também nas rotas que ESCREVEM na conta.

    **O que faltava, medido pelas rotas reais.** Havia um comentário no fecho
    (e outro no ecrã) a afirmar que, a partir da marca `a_fechar`, "nenhuma
    conta nova pode nascer nesta sessão, porque `abrir_venda` resolve a
    sessão por `_sessao_aberta`". A afirmação era verdadeira sobre o
    `abrir_venda` e falsa sobre tudo o resto: só ele passava por lá. Com a
    sessão em `a_fechar`, um `POST /pos/venda/{id}/dividir` passava e nasciam
    3 contas `aberta` nessa sessão; com a sessão já `fechada`, o `dividir`
    passava outra vez (2 partes novas com o `sessao_id` da sessão fechada) e
    o `POST /pos/venda/{id}/linhas` também — a conta subiu de 14,10 € para
    21,15 € numa sessão cujo Z já estava assinado.

    É o pior dos dois mundos: o Z é um retrato assinado de um turno (o
    `contas_abertas` que `caixa.py::_contas_abertas_da_sessao` grava lá dentro
    diz, com valor, o que ficou por cobrar) e o turno continuava a mudar por
    baixo dele. Ninguém volta a olhar para a sessão depois do fecho, por isso
    a divergência não aparecia em relatório nenhum.

    A pergunta é pela sessão DESTA venda (`venda["sessao_id"]`), nunca "há
    alguma sessão aberta nesta caixa" — a caixa pode ter reaberto entretanto
    com uma sessão nova, que não tem nada a ver com esta conta antiga. E é
    `venda.get(...)`, não `venda[...]`: uma venda sem `sessao_id` (dados
    corrompidos, uma migração incompleta) cai no MESMO 409, nunca num
    KeyError/500 — `find_one({"id": None})` não encontra nada e o `if not
    sessao` trata disso.

    Distingue os mesmos dois casos do núcleo fiscal, porque a saída que a
    operadora tem à frente é diferente em cada um: um fecho A DECORRER
    (`a_fechar`) é uma espera de segundos e a conta continua exactamente
    onde está; um fecho FEITO é o fim desta conta neste turno.

    **O `cancelar_venda` é a única rota de escrita que NÃO passa por aqui**,
    e é uma decisão, não um esquecimento — ver a docstring dela."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": venda.get("sessao_id")})
    if sessao and sessao.get("estado") == "a_fechar":
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_A_FECHAR_AGORA)
    if not sessao or sessao.get("estado") != "aberta":
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_JA_FECHADA)


async def _repor_aberta(db, filtro: Dict, atualizacao: Dict) -> None:
    """As COMPENSAÇÕES deste módulo que repõem o estado de partida de uma
    venda (o cancelamento desfeito e a divisão abortada), protegidas do índice
    único parcial que passou a existir em `fat_vendas`.

    O nome é de quando eram só duas e as duas repunham `aberta`. Desde que o
    gestor pode cancelar uma mãe `separada` sem partes
    (`caixa.py::arrumar_conta_esquecida`), o `estado` reposto é o que o
    chamador leu — e nesse caso é `separada`. Não muda nada aqui: o índice
    único é PARCIAL sobre `estado: "aberta"`, por isso repor `separada` não
    lhe toca sequer, e o ramo da colisão é o mesmo de sempre para o caso em
    que se repõe `aberta`.

    O índice trava DUAS contas em curso no mesmo posto, e uma venda que volta
    a `aberta` volta a entrar nele com a etiqueta `posto_em_curso` que nunca
    perdeu. Se, na janela de milissegundos entre o `cancelada` e a
    compensação, um segundo separador tiver começado a conta do cliente
    seguinte neste posto, a reposição colide — e um `DuplicateKeyError` a subir
    daqui virava um 500 no lugar do 409 que quem chama já tem preparado, e que
    é a única coisa que a operadora precisa de ouvir ("a conta NÃO foi
    cancelada").

    **E a colisão NÃO se engole — esse era o defeito.** A versão anterior
    apanhava o `DuplicateKeyError`, registava-o e desistia da reposição, com a
    promessa escrita aqui de que «a conta que sobrou aparece na lista do gestor
    e no Z do turno — nunca invisível». Medida pelas rotas reais, a promessa era
    falsa: a venda ficava no estado de que a compensação a queria TIRAR
    (`separada` na divisão abortada, `cancelada` no cancelamento desfeito), e
    esse estado não existe para conjunto nenhum — `_contas_do_balcao`,
    `caixa._contas_esquecidas` e `caixa._contas_abertas_da_sessao` filtram
    todos por `estado: "aberta"`. Reproduzido: uma conta de **11,64 €** ficava
    `separada` sem partes nenhumas, a lista do gestor vinha **vazia**, e o
    `POST /pos/caixa/fechar` respondia 200 com
    `contas_abertas={quantas:0, total_por_cobrar:0,00}` — 11,64 € apagados de
    um Z assinado.

    O que colide é a ETIQUETA DO POSTO, e não o `estado`: o índice único
    parcial só conta as `aberta` que TÊM `posto_em_curso`
    (`db.py`, `_etiqueta_do_posto`). Por isso a segunda tentativa repõe
    `aberta` **e larga a etiqueta na mesma escrita** — a mesma coisa que
    `entregar_ao_gestor` e `caixa._largar_o_posto_das_contas_abertas` fazem, e
    pela mesma razão: esta conta já não é a conta EM CURSO deste posto (a nova
    é), mas continua a ser dinheiro por receber. Fora do índice, a reposição
    não pode voltar a colidir — é o único índice único de `fat_vendas`.

    A partir daqui a conta acaba SEMPRE `aberta`, e é isso que a põe outra vez
    nos três conjuntos: no ecrã do posto (`_contas_do_balcao` não olha à
    etiqueta), na lista do gestor quando o turno fechar, e — o que interessa —
    no `contas_abertas` do Z. O registo continua a ser escrito: isto é um
    desfecho raro e quem for a ver amanhã tem de encontrar a linha."""
    try:
        await db[COLECOES["vendas"]].update_one(filtro, {"$set": atualizacao})
    except DuplicateKeyError:
        await db[COLECOES["vendas"]].update_one(
            filtro,
            {"$set": atualizacao, "$unset": {"posto_em_curso": ""}},
        )
        logger.warning(
            "[faturacao] a venda %s voltou a `aberta` SEM a etiqueta do posto: "
            "este posto já tem outra conta em curso (índice `posto_em_curso`). "
            "Ela continua no ecrã deste PC, entra no Z do turno como dinheiro "
            "por cobrar e aparece ao gestor; quem chamou recusa na mesma.",
            filtro.get("id"),
        )


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
            # numa venda que pode estar a virar Fatura Simplificada. Pela
            # mesma razão se repete a da SESSÃO: as tentativas duram
            # milissegundos, mas é exactamente nessa ordem de grandeza que
            # `caixa.py::fechar_caixa` marca a sessão `a_fechar` — repetir
            # sem voltar a perguntar era deixar a escrita entrar num turno
            # que já está a somar o Z.
            venda = await _obter_venda_da_loja(db, venda_id, loja_id)
            _garante_aberta(venda)
            _garante_do_balcao(venda)
            await _garante_sem_emissao(db, venda_id)
            await _garante_sessao_desta_venda_aberta(db, venda)

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
        # A conta de onde esta parte veio (`dividir_conta`), ou `None` na
        # esmagadora maioria das contas, que não são parte de nada. Sempre
        # presente pela mesma regra do `cancelada_em`: o ecrã não pode ter de
        # adivinhar se a ausência quer dizer "não é uma parte" ou "versão
        # antiga da API" — é por este campo que ele sabe que está a cobrar
        # uma pessoa de várias, e não a conta toda.
        "conta_mae_id": venda.get("conta_mae_id"),
        # O travão, para o ecrã o poder MOSTRAR em vez de o guardar só na
        # memória do browser: até aqui o POS só sabia da emissão incerta pelo
        # 503 que tinha acabado de receber, e dois toques (um F5, a tela de
        # descanso, o browser a ir abaixo) apagavam essa memória — a conta
        # voltava a parecer normal e a operadora continuava a picar por cima
        # de uma fatura que podia ter saído. Agora vem do SERVIDOR em todas
        # as respostas de venda.
        "emissao_por_confirmar": emissao_por_confirmar,
        # **A MARCA: de quem é esta conta.** Gravada na venda, e não deduzida
        # de mais nada — é ela que faz o conjunto que a PORTA conta
        # (`_contas_do_balcao`) e o conjunto que o ECRÃ mostra
        # (`GET /pos/venda/aberta`) serem o mesmo conjunto. Uma conta com esta
        # marca saiu do balcão e é do gestor: não prende o posto, não volta ao
        # ecrã da operadora, e não se destranca sozinha quando o gestor libertar
        # a reserva fiscal dela (era exactamente aí que a conta do cliente
        # anterior ressuscitava à frente do seguinte — ver a docstring de
        # `entregar_ao_gestor`).
        #
        # Sempre presente, mesmo a `None`, pela regra do `cancelada_em`: o ecrã
        # não pode ter de adivinhar se a ausência quer dizer "está no balcão" ou
        # "versão antiga da API".
        "entregue_ao_gestor_em": venda.get("entregue_ao_gestor_em"),
        "entregue_ao_gestor_por": venda.get("entregue_ao_gestor_por"),
        "totais": _totais(venda),
    }


# --- O CONJUNTO. UM. -----------------------------------------------------------
#
# **A raiz, e é a terceira vez que ela muda de sítio em vez de fechar.** Havia
# QUATRO respostas à pergunta "que contas tem este posto por resolver?":
# `_conta_por_resolver` (a porta) varria todas as sessões abertas da LOJA;
# `GET /pos/venda/aberta` (o ecrã) varria UMA sessão e trazia UMA conta;
# `GET /pos/venda/repartidas` varria a mesma sessão e só as partes; e a chave
# do índice único era `"{sessao_id}|{dispositivo_id}"`. Enquanto houvesse uma
# caixa e uma conta, os quatro concordavam — e foi por isso que passou três
# vezes.
#
# **Medido pelas rotas reais, numa loja com duas caixas activas.** 8,99 €
# picados na caixa Balcão; o PC passa para a caixa Drive (o ecrã «Qual caixa?»
# do `PosApp.js` é o caminho normal quando o localStorage não traz caixa)::
#
#     GET /pos/venda/aberta?caixa_id=caixa-2  -> None
#     GET /pos/venda/repartidas?caixa_id=...  -> []
#     GET /fiscal/reservas-presas             -> 0
#     GET /pos/caixa/contas-esquecidas        -> []
#     POST /pos/venda -> 409 «Acabe a que está à frente: cobre-a ou cancele-a»
#
# Sete toques até ficar sem saída, e as três saídas que a mensagem nomeia
# (cobrar, cancelar, entregar ao gestor) exigem todas uma conta no ecrã. E dois
# `POST /pos/venda` simultâneos em caixas diferentes davam **201 + 201**,
# porque as chaves do índice diferiam no `sessao_id` mas a porta era da loja.
#
# **A correcção não é alinhar dois conjuntos — já se tentou três vezes.** É
# haver UM: esta função, e o âmbito dela NÃO É UM PARÂMETRO. Quem a chama passa
# a loja e o dispositivo, os dois do token do operador, e não tem como pedir
# outra coisa — não há um `caixa_id`, nem um `sessao_ids`, que dois chamadores
# possam passar diferente. É a assinatura que impede a quarta divergência, e
# `test_um_posto_uma_conta.py` prende-a.
#
# **O âmbito é o POSTO, e a razão é a das duas pontas.** Um PC atende um
# cliente de cada vez (a regra do dono: «não existe isso de pôr uma conta de
# lado e cobrar outra»), seja qual for a caixa que o ecrã tenha escolhido no
# localStorage — por isso a recusa é do posto. E o ecrã tem de MOSTRAR o que a
# porta conta, incluindo a conta que ficou noutra caixa: é a única forma de as
# saídas se executarem com o dedo. O contrário — recusar a troca de caixa e
# mandá-la voltar à caixa de origem — parece mais arrumado e não é: basta o
# gestor DESACTIVAR essa caixa (o `GET /pos/caixa/estado` dela passa a 404)
# para o dinheiro ficar sem caminho nenhum. Aqui não fica: a leitura não passa
# pela caixa da conta, só pela sessão dela, e essa continua aberta.
#
# **E a sessão da conta é que manda no que se lhe pode fazer.** Cobrá-la emite
# na sessão em que ela nasceu (`fiscal.py`), e as escritas confirmam essa
# sessão (`_garante_sessao_desta_venda_aberta`) — trazer a conta ao ecrã de
# outra caixa não a muda de turno nem de Z.
async def _contas_do_balcao(db, loja_id: str, dispositivo_id: Optional[str]) -> List[Dict]:
    """**As contas que este POSTO tem por resolver**, da mais recente para a
    mais antiga — e é este o conjunto, o único, para a porta
    (`POST /pos/venda`) e para os dois ecrãs (`GET /pos/venda/aberta` e
    `GET /pos/venda/repartidas`).

    São as contas `aberta` deste dispositivo, em qualquer sessão AINDA ABERTA
    desta loja, e ainda não entregues ao gestor:

    - **`aberta`**: as emitidas, canceladas e separadas já estão resolvidas.
    - **deste dispositivo**: ao balcão a conta é do POSTO, não da pessoa (a
      Ana entra com o PIN dela e a conta da Rafaela continua lá) e não da
      caixa. Dois PCs na mesma caixa atendem dois clientes ao mesmo tempo, e
      é por isso que o `dispositivo_id` está aqui — sem ele, o cliente do
      balcão pagava o açaí do drive-thru, e isso não era uma corrida de
      milissegundos, era o estado estável dessa configuração o dia inteiro.
    - **numa sessão aberta desta loja**: uma conta de um turno já fechado é
      dinheiro do passado e é do gestor (`caixa.py::_contas_esquecidas`); o
      balcão pergunta pelo cliente que está à frente.
    - **não entregue ao gestor**: a marca (`entregue_ao_gestor_em`) é GRAVADA
      e tira a conta travada dos dois lados ao mesmo tempo. `None` casa, no
      Mongo, com o campo AUSENTE e com o campo a `null` — todas as contas
      gravadas antes desta marca são, por definição, contas do balcão, e por
      isso isto dispensou migração.

    As PARTES de uma conta dividida entram: `_nova_parte` herda-lhes a sessão e
    o dispositivo da mãe, e uma conta dividida só acaba quando todas as partes
    estiverem cobradas ou canceladas. **Mas só depois de a mãe estar
    `separada`** — as filhas nascem antes de a mãe travar (`_grava_as_partes`)
    e, enquanto a mãe não virou, elas não existem para ninguém. Ver
    `por_resolver._mae_ja_travou`: é essa pergunta que fecha a janela em que o
    ecrã mostrava uma PARTE de 3,78 € onde estava uma conta de 11,35 €.

    Uma loja tem duas ou três caixas com uma sessão aberta cada, por isso a
    primeira leitura são dois ou três documentos (há índice por `loja_id`); a
    segunda traz o punhado de contas abertas deste posto (índice parcial por
    `criada_em`, só sobre as `aberta`).

    `loja_id` é o do token do operador. A sessão de caixa grava sempre o
    `loja_id` (`caixa.py::abrir_caixa`, e o próprio Z lê-o sem recuo nenhum),
    por isso não há aqui o remendo que a versão anterior tinha para uma sessão
    sem esse campo — um remendo que, além de proteger de nada, era o único
    sítio por onde o âmbito voltava a entrar como argumento."""
    from .por_resolver import contas_por_resolver

    sessoes = await (
        db[COLECOES["sessoes_caixa"]]
        .find({"loja_id": loja_id, "estado": "aberta"}, {"_id": 0, "id": 1})
        .to_list(50)
    )
    sessao_ids = [s["id"] for s in sessoes if s.get("id")]
    if not sessao_ids:
        return []
    # **O predicado é de `por_resolver.contas_por_resolver` e já não daqui** —
    # ver o cabeçalho desse ficheiro. Isto filtra pelo FIM do balcão e não
    # volta a decidir o que conta: as que estão EM CURSO (o `estado: "aberta"`,
    # a marca do gestor e, desde esta ronda, a mãe que ainda não travou) e as
    # deste POSTO. `em_curso_no_balcao` já traz as três decisões lá dentro.
    #
    # Uma reserva órfã (sem venda) não tem `dispositivo_id` e cai neste filtro,
    # como tem de cair: o balcão pergunta pelo cliente que está à frente, e
    # essa é do gestor (`/fiscal/reservas-presas`).
    itens = await contas_por_resolver(db, sessao_ids)
    # A mais recente primeiro — a que a operadora tem à frente é sempre a
    # última que abriu.
    return [
        i["venda"] for i in reversed(itens)
        if i["em_curso_no_balcao"] and i["dispositivo_id"] == dispositivo_id
    ]


def _etiqueta_do_posto(loja_id: str, dispositivo_id: Optional[str]) -> str:
    """A chave do índice único parcial de `db.py` — **o mesmo âmbito de
    `_contas_do_balcao`**, e é essa igualdade que faz o índice fechar a corrida
    que a leitura não fecha.

    Era `"{sessao_id}|{dispositivo_id}"`, e por isso a corrida atravessava-a:
    dois `POST /pos/venda` simultâneos do mesmo PC em caixas diferentes liam os
    dois um balcão livre e inseriam os dois, porque as chaves diferiam no
    `sessao_id`. Medido: 201 + 201, duas contas abertas neste posto — uma delas
    invisível, que é o defeito inteiro outra vez.

    Sem a sessão na chave, uma conta que fique `aberta` quando o turno fecha
    continuaria a ocupar o posto no dia seguinte, e a porta — que só varre
    sessões ABERTAS — responderia "o balcão está livre" ao mesmo tempo que o
    índice recusava: um beco novo no lugar do velho. Por isso o fecho de caixa
    tira a etiqueta às contas que deixa abertas
    (`caixa.py::_largar_o_posto_das_contas_abertas`). São os dois lados da
    mesma decisão e não se separam."""
    return "%s|%s" % (loja_id, dispositivo_id)


async def _porque_a_etiqueta_esta_presa(db, etiqueta: str) -> str:
    """A recusa de `abrir_venda` quando o índice diz que o posto está ocupado e
    a leitura do balcão não encontra nada — escolhida pelo estado da SESSÃO da
    conta que tem a etiqueta, e não por um palpite.

    São dois becos diferentes com a mesma aparência, e só um deles é do gestor:

    - a sessão dessa conta está **fechada** (ou já não existe): a conta é de um
      turno arrumado, ninguém no POS lhe chega, e quem a resolve é mesmo o
      gestor — `_MSG_ETIQUETA_PRESA`, que é a frase de sempre;
    - a sessão está **`a_fechar`**: o fecho ficou a meio e o Z não saiu. O
      gestor não a pode arrumar (`caixa.arrumar_conta_esquecida` recusa-a de
      propósito, o Z está a somá-la), e quem a desbloqueia é quem está ao
      balcão, carregando outra vez em FECHAR CAIXA naquela caixa —
      `_MSG_ETIQUETA_PRESA_COM_FECHO_A_MEIO`.

    Três leituras no caminho do ERRO e nenhuma no caminho normal: quem chega
    aqui já levou um 409 e o que falta é dizer-lhe o que fazer a seguir."""
    conta = await db[COLECOES["vendas"]].find_one(
        {"posto_em_curso": etiqueta, "estado": "aberta"}
    )
    if not conta:
        return _MSG_ETIQUETA_PRESA
    sessao = await db[COLECOES["sessoes_caixa"]].find_one(
        {"id": conta.get("sessao_id")}
    )
    if not sessao or sessao.get("estado") != "a_fechar":
        return _MSG_ETIQUETA_PRESA
    caixa = await db[COLECOES["caixas"]].find_one({"id": conta.get("caixa_id")}) or {}
    # O nome, e o id como recuo: uma caixa apagada da base não pode deixar a
    # frase a falar de «None» ao balcão.
    nome = caixa.get("nome") or conta.get("caixa_id") or "que ficou a meio"
    return _MSG_ETIQUETA_PRESA_COM_FECHO_A_MEIO % (nome, nome)


async def _porque_nao_ha_cliente_seguinte(db, conta: Dict, caixa_pedida: str) -> str:
    """A recusa de `abrir_venda`, com a caixa da conta lá dentro quando ela não
    é a caixa em que o ecrã está.

    A frase base manda «acabe a que está à frente». Ela só é executável porque
    a conta está mesmo à frente — `GET /pos/venda/aberta` devolve a mais
    recente do MESMO conjunto que esta recusa conta —, e quando a conta vem de
    outra caixa deste posto a operadora precisa de ler de ONDE, senão olha para
    uma conta que não sabe de onde veio.

    O nome da caixa lê-se aqui e não se guarda na venda: o gestor pode
    renomear a caixa, e o que interessa é o nome de HOJE, que é o que está
    escrito no ecrã «Qual caixa?». Uma leitura, e só no caminho da recusa.
    Sem caixa encontrada (foi apagada), não se inventa nada — fica a frase
    base, que continua verdadeira."""
    if not conta.get("caixa_id") or conta.get("caixa_id") == caixa_pedida:
        return _MSG_CONTA_POR_RESOLVER
    caixa = await db[COLECOES["caixas"]].find_one({"id": conta["caixa_id"]})
    nome = (caixa or {}).get("nome")
    if not nome:
        return _MSG_CONTA_POR_RESOLVER
    return _MSG_CONTA_POR_RESOLVER + (_MSG_CONTA_NOUTRA_CAIXA % nome)


@router.post("/pos/venda", status_code=201)
async def abrir_venda(dados: PedidoNovaVenda, operador: Dict = Depends(operador_atual)) -> dict:
    """A conta nova do cliente seguinte — se não houver nenhuma por resolver
    neste posto.

    Esta rota criava SEMPRE uma venda nova, sem olhar às que já estavam
    abertas, e era essa porta que deixava uma conta ficar `aberta` no servidor
    e invisível no ecrã: o ecrã tem UM lugar para a conta em curso, e a conta
    anterior saía dele sem sair da base de dados. Só o fecho de caixa voltava a
    mencioná-la, horas depois (`caixa.py::_contas_abertas_da_sessao`). Medido,
    com a porta ainda aberta: picado um Açaí de 8,99 € e começada a conta
    seguinte com uma Embalagem de 0,15 €, ficavam **2 contas abertas neste PC e
    1 mostrável no ecrã — 8,99 € abertos e invisíveis**; com a mesma conta
    dividida em duas partes e a operadora a tocar em "Cobrar" numa delas, **3
    abertas e 2 no ecrã**.

    A porta fecha-se AQUI e não no ecrã: os ecrãs do POS desenham-se sem
    servidor nenhum, e um ecrã que evita o pedido não impede pedido nenhum — um
    segundo separador, um F5 a meio ou uma versão antiga do bundle voltavam a
    abri-la. O ecrã faz-lhe companhia (o cartão de produto fica morto com a
    razão à vista), mas quem recusa é a rota."""
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    # **O CONJUNTO, e é o mesmo que o ecrã mostra** — a MESMA função, com os
    # MESMOS argumentos (ver `_contas_do_balcao`). O `caixa_id` do corpo do
    # pedido não entra aqui: um PC atende um cliente de cada vez, seja qual for
    # a caixa que o localStorage tenha escolhido, e era a recusa por sessão que
    # deixava o mesmo PC abrir uma conta em cada caixa.
    por_resolver = await _contas_do_balcao(
        db, operador["loja_id"], operador.get("dispositivo_id"))
    if por_resolver:
        raise HTTPException(
            status_code=409,
            detail=await _porque_nao_ha_cliente_seguinte(
                db, por_resolver[0], dados.caixa_id),
        )

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
        # A marca de quem é a conta, presente desde o nascimento e a `None`:
        # esta acaba de nascer no balcão. Ver `_contas_do_balcao`.
        "entregue_ao_gestor_em": None,
        "entregue_ao_gestor_por": None,
        # A etiqueta do POSTO — o único campo deste documento que existe só
        # para um índice, e diz-se aqui porquê: é a chave do único parcial de
        # `db.py` que impede DUAS contas em curso no mesmo posto. Só a conta
        # que nasce no balcão a tem: `_nova_parte` não a copia (as partes são
        # várias por posto, de propósito) e `entregar_ao_gestor` tira-a.
        "posto_em_curso": _etiqueta_do_posto(
            operador["loja_id"], operador.get("dispositivo_id")),
    }
    # **A CORRIDA DO DUPLO TOQUE, e é o índice que a decide.** A verificação
    # acima é ler-e-depois-escrever: dois `POST /pos/venda` simultâneos do
    # mesmo PC lêem os dois um balcão livre e inserem os dois. Medido com o
    # duplo de Mongo a ceder o event loop em cada leitura (que é o que o Motor
    # faz contra o Mongo real): **201 e 201, duas contas abertas neste posto**.
    #
    # O predicado da porta é expressável num índice precisamente porque a
    # excepção da travada deixou de ser calculada: o índice único PARCIAL de
    # `db.py` (`fat_vendas`, `posto_em_curso`, só onde `estado: "aberta"`) tem
    # agora a chave do MESMO âmbito de `_contas_do_balcao` — o posto, e já não
    # a sessão (ver `_etiqueta_do_posto`). Era essa diferença que a corrida
    # atravessava: com a chave da sessão, dois toques em caixas diferentes
    # davam 201 + 201. Quem perde a corrida apanha `DuplicateKeyError` no
    # INSERT — nunca chega a gravar nada — e sai daqui com a MESMA recusa de
    # quem a perdeu pela leitura.
    #
    # Uma conta que muda de estado (emitida, cancelada, separada) ou que é
    # entregue ao gestor sai SOZINHA do índice. O único sítio que tem de tirar
    # a etiqueta À MÃO é o fecho de caixa
    # (`caixa.py::_largar_o_posto_das_contas_abertas`), e é o preço de a chave
    # já não ter a sessão: sem isso, uma conta esquecida num turno fechado
    # trancava este PC no dia seguinte. Se o índice não existir (uma base
    # antiga com órfãs que impedem a criação — `criar_indices` regista e
    # segue), fica a garantia de antes, que é a leitura acima.
    try:
        await db[COLECOES["vendas"]].insert_one(dict(venda))
    except DuplicateKeyError:
        # A leitura acima disse que o balcão estava livre e o índice diz que
        # não: ou perdemos a corrida do duplo toque (o caso normal, e a conta
        # que ganhou está mesmo à frente da operadora), ou ficou para trás uma
        # etiqueta de um turno fechado que o `_largar_o_posto_das_contas_
        # abertas` não conseguiu tirar. Relê-se para dizer QUAL — a recusa que
        # não sabe explicar-se é o beco que esta ronda veio fechar.
        ganhou = await _contas_do_balcao(
            db, operador["loja_id"], operador.get("dispositivo_id"))
        if ganhou:
            raise HTTPException(
                status_code=409,
                detail=await _porque_nao_ha_cliente_seguinte(
                    db, ganhou[0], dados.caixa_id),
            )
        raise HTTPException(
            status_code=409,
            detail=await _porque_a_etiqueta_esta_presa(db, venda["posto_em_curso"]),
        )
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
    # O `caixa_id` continua a ser exigido e a ser confirmado ABERTO, e não é
    # decoração: sem caixa aberta o POS não vende, e é o 409 daqui que manda o
    # ecrã para o `PosCaixaFechada`. O que ele já NÃO faz é escolher o
    # conjunto — ver a linha a seguir.
    await _sessao_aberta(db, caixa_id)

    # **O MESMO conjunto da porta — a MESMA função, com os MESMOS argumentos**
    # (`_contas_do_balcao`), e é essa identidade que é a correcção. Enquanto
    # esta rota tivesse um âmbito próprio, havia contas que prendiam o posto
    # sem aparecerem aqui: a que ressuscitava à frente do cliente errado, e
    # depois a que ficava presa noutra caixa com o ecrã a dizer que o balcão
    # estava livre.
    #
    # A MAIS RECENTE (a lista vem ordenada por `criada_em` descendente): a que
    # a operadora tem à frente é sempre a última que abriu. Ela pode ser de
    # OUTRA caixa deste posto, e é de propósito — a resposta traz o `caixa_id`
    # dela, e o ecrã diz-lhe onde ficou.
    #
    # `dispositivo_id` vem do token (pos_auth.py::entrar), nunca da query. Um
    # token emitido ANTES desse campo não o traz, e as vendas abertas com ele
    # também não têm o campo: filtrar por `None` casa, no Mongo, com o campo
    # ausente e com o campo a `null`, por isso token antigo só encontra conta
    # antiga e token novo só encontra conta nova. Os quatro cruzamentos estão
    # provados em test_venda.py.
    abertas = await _contas_do_balcao(
        db, operador["loja_id"], operador.get("dispositivo_id"))
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
    _garante_do_balcao(venda)
    await _garante_sem_emissao(db, venda_id)
    # DEPOIS da emissão, e não antes: uma conta travada é travada em qualquer
    # turno, e "chame o gestor" é a acção certa nos dois casos — dizer-lhe
    # primeiro "o turno já fechou" mandava-a ir picar noutra caixa uma conta
    # que pode ter uma Fatura Simplificada real a nascer.
    await _garante_sessao_desta_venda_aberta(db, venda)

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
    _garante_do_balcao(venda)
    await _garante_sem_emissao(db, venda_id)
    await _garante_sessao_desta_venda_aberta(db, venda)

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
    _garante_do_balcao(venda)
    await _garante_sem_emissao(db, venda_id)
    await _garante_sessao_desta_venda_aberta(db, venda)

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
    _garante_do_balcao(venda)
    await _garante_sem_emissao(db, venda_id)
    await _garante_sessao_desta_venda_aberta(db, venda)

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

    **A ÚNICA rota de escrita sem `_garante_sessao_desta_venda_aberta`, e é
    uma decisão.** As outras seis recusam numa sessão que já não está aberta
    porque MUDAM DINHEIRO — a conta que o Z registou por 14,10 € passava a
    valer 21,15 € debaixo de um Z assinado, ou nasciam partes novas num turno
    fechado. Cancelar não muda o valor de nada nem faz nascer conta nenhuma:
    escreve exactamente aquilo que o Z já diz — que esta conta nunca foi
    cobrada — e é a única forma de a arrumar. Bloqueá-la aqui era deixar as
    contas de um turno fechado presas em `aberta` para sempre, que é o
    problema oposto e não o mesmo.

    Quem chega a esta rota com a sessão já fechada é o gestor
    (`caixa.py::arrumar_conta_esquecida`, o ecrã das contas por cobrar de
    turnos fechados), e não a operadora: com a caixa fechada, nenhum ecrã do
    POS mostra estas contas — nem `GET /pos/venda/aberta` nem `GET
    /pos/venda/repartidas`, que resolvem a sessão por `_sessao_aberta`.
    """
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    return await _cancelar_conta(db, venda, operador)


async def _cancelar_conta(db, venda: Dict, operador: Dict) -> dict:
    """**A escrita do cancelamento, e é UMA só** — a do balcão
    (`cancelar_venda`) e a do gestor (`caixa.py::arrumar_conta_esquecida`).

    Quem decide SE se pode cancelar é o chamador, e são decisões diferentes: o
    balcão só cancela o que está `aberta` (`_garante_aberta`); o gestor cancela
    também a mãe `separada` a quem a divisão morreu a meio, porque essa não
    tem mais ninguém que lhe chegue (ver lá o porquê). O que não pode ser
    diferente — e é isto — é a DISCIPLINA da escrita: a condição de estado no
    `update_one`, a segunda pergunta pela reserva DEPOIS de escrever, e a
    compensação que repõe o estado de partida.

    **O estado de partida é o que se LEU**, e é ele que condiciona a escrita e
    a compensação. Estava aqui o literal `"aberta"` dos dois lados; com o
    gestor a poder cancelar uma `separada`, um literal ou carimbava
    `cancelada` por cima de uma venda que entretanto mudou (o filtro deixava
    de casar — esse era o lado seguro) ou, na compensação, ressuscitava como
    `aberta` uma mãe que nunca esteve aberta e voltava a pô-la à frente da
    operadora. Ler o estado e usá-lo nos dois sítios é a mesma técnica de
    sempre, escrita uma vez em vez de duas."""
    venda_id = venda["id"]
    estado_de_partida = venda.get("estado")

    await _garante_sem_emissao(db, venda_id)

    # A escrita é CONDICIONADA ao estado que se leu — a mesma técnica de I2
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
        {"id": venda_id, "estado": estado_de_partida}, {"$set": atualizacao}
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
    # 3. o estado de partida é aquele em que ela estava um segundo antes, e
    #    nada se perde: os carimbos do cancelamento voltam a `None` na mesma
    #    escrita.
    #
    # Em qualquer dos desfechos a operadora ouve o MESMO 409 — a conta não
    # foi cancelada, e é isso que ela precisa de saber antes de mexer em mais
    # alguma coisa. (No desfecho raro em que a venda já ficou `emitida`, os
    # carimbos do cancelamento ficam colados a ela; ficam à VISTA em
    # `_venda_publica`, e a venda conta como emitida no Z, que é o que
    # fiscalmente interessa — nenhuma escrita nossa pode limpá-los sem voltar
    # a correr o risco de mexer num documento fiscal real.)
    if await _tem_reserva_fiscal(db, venda_id):
        await _repor_aberta(
            db,
            {"id": venda_id, "estado": "cancelada"},
            {"estado": estado_de_partida, "cancelada_em": None,
             "cancelada_por": None},
        )
        raise HTTPException(
            status_code=409, detail=await _porque_nao_foi_cancelada(db, venda_id)
        )

    venda.update(atualizacao)
    return _venda_publica(venda)


# --- Entregar a conta travada ao GESTOR ----------------------------------------
#
# A saída que faltava, e a que fecha a raiz.


@router.post("/pos/venda/{venda_id}/entregar-ao-gestor")
async def entregar_ao_gestor(
    venda_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """A conta TRAVADA sai do balcão e passa a ser do gestor — com a marca
    GRAVADA na venda, e não deduzida de mais nada.

    **O defeito que isto fecha, medido pelas rotas reais.** A operadora
    largava a conta travada só no ECRÃ (o botão "Servir o cliente seguinte"
    não falava com o servidor), e a porta de `abrir_venda` deixava-a começar a
    seguinte por causa de uma excepção CALCULADA: "não conta a que tiver
    reserva fiscal viva". Depois o gestor libertava a reserva
    (`fiscal.py::libertar_reserva_presa`, que por desenho não toca na venda) —
    e nesse instante a excepção deixava de ser verdade sem que ninguém
    escrevesse nada. A conta ficava `aberta`, sem marca, e sem aparecer em
    lado nenhum: nem em `/pos/venda/aberta` (não era a mais recente), nem em
    `/repartidas` (não tem `conta_mae_id`), nem em `/fiscal/reservas-presas`
    (a reserva foi-se), nem em `/caixa/contas-esquecidas` (a sessão ainda
    estava aberta). Só o fecho de caixa a mencionava, horas depois.

    Reproduzido no processo, com as rotas reais e os números que saíram::

        1. cliente A: 8.99 EUR
        2. A travada (reserva fiscal viva): emissao_por_confirmar=True
        3. cliente B aberto por cima da travada: 2.00 EUR
           abertas neste PC: 2   no ecrã: 1
        4. o gestor liberta a reserva de A -> a venda A fica ['aberta']
        5. B emitida
        6. o ecrã põe à frente: A   emissao_por_confirmar=False
           conta_mae_id=None   total=8.99   linhas=['Açaí Regular']
        7. o cliente seguinte pede uma Coca-Cola:
           conta = ['Açaí Regular', 'Coca-Cola']   total: 10.99 EUR
           a Fatura Simplificada que sairia:
             [('Açaí Regular', 1.0, 8.99), ('Coca-Cola', 1.0, 2.0)]

    A Fatura Simplificada do cliente novo levava o açaí do cliente anterior.

    **Porquê uma marca gravada, e não outra excepção mais esperta.** Porque
    uma excepção calculada é uma frase sobre o MUNDO (existe uma reserva?) e o
    que faz falta é uma frase sobre a CONTA (de quem ela é). A marca é a
    segunda: fica escrita, sobrevive ao gestor libertar a reserva, tira a
    conta da porta e do ecrã ao MESMO tempo (`_contas_do_balcao`, uma função
    só, chamada pelos três sítios), e torna o predicado da porta expressável num
    índice único parcial — que é o que fecha a corrida do duplo toque sem lock
    nenhum (ver `abrir_venda`).

    **As três recusas, e o que cada uma protege:**

    1. **Só a TRAVADA se entrega** (`_MSG_ENTREGAR_SO_A_TRAVADA`). Uma conta
       normal a operadora cobra ou cancela; deixar entregar essa era criar
       exactamente o que o dono proíbe — «pôr uma conta de lado e cobrar
       outra» — só que agora com uma marca oficial por cima. A pergunta é a
       mesma de `_garante_sem_emissao` (`_emissao_por_confirmar`), e não uma
       segunda definição de "travada".
    2. **Só a deste POSTO** (`_MSG_ENTREGAR_DE_OUTRO_POSTO`). O
       `dispositivo_id` vem do TOKEN, como em todo o módulo: o PC Drive-Thru
       não entrega a conta do PC Balcão, senão a conta desaparecia do ecrã de
       quem a tem à frente.
    3. **Não se entrega duas vezes** (`_MSG_JA_ENTREGUE`), e quem decide é o
       `matched_count` da escrita CONDICIONADA — nunca a leitura de cima.
       Entre as duas há `await`s (a pergunta pela reserva), e nessa janela a
       venda pode ter sido emitida pelo `finalizar` ou entregue por um segundo
       separador. Marcar `entregue_ao_gestor_em` numa venda que ACABOU de
       receber uma Fatura Simplificada real era escondê-la do balcão sem
       razão nenhuma.

    **O que NÃO acontece aqui, de propósito:** a venda não muda de `estado`.
    Ela continua `aberta` porque é a verdade — não foi cobrada nem cancelada,
    e o dinheiro dela continua por receber. É por isso que ela continua a
    contar no Z do turno (`caixa.py::_contas_abertas_da_sessao`) e continua a
    travar o fecho enquanto a reserva fiscal estiver viva
    (`caixa.py::_venda_com_emissao_viva`, e está certo que trave: fechar a
    caixa a meio de uma emissão é fechar as contas antes de o dinheiro estar
    contado). O que muda é só de quem ela é — e a partir daqui ela aparece na
    lista do gestor (`GET /caixa/contas-esquecidas`), mesmo com a sessão
    aberta, que é o único sítio onde alguém a vai procurar."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    if venda.get("dispositivo_id") != operador.get("dispositivo_id"):
        raise HTTPException(status_code=409, detail=_MSG_ENTREGAR_DE_OUTRO_POSTO)
    _garante_do_balcao(venda)
    if not await _emissao_por_confirmar(db, venda):
        raise HTTPException(status_code=409, detail=_MSG_ENTREGAR_SO_A_TRAVADA)

    atualizacao = {
        "entregue_ao_gestor_em": _agora(),
        # Quem a entregou, com o MESMO `_quem` do resto do módulo (caixa.py,
        # reutilizado e não reescrito): é a primeira pergunta do gestor quando
        # abrir a lista e encontrar uma conta lá — a quem é que ele vai
        # perguntar o que aconteceu àquele cliente.
        "entregue_ao_gestor_por": _quem(operador),
    }
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta", "entregue_ao_gestor_em": None},
        # O `$unset` da etiqueta do posto vai na MESMA escrita da marca, e tem
        # de ir: enquanto ela lá estiver, o índice único parcial de `db.py`
        # continua a contar esta conta como "a conta em curso deste posto" e o
        # `abrir_venda` seguinte apanhava um DuplicateKeyError — o balcão
        # ficava trancado por uma conta que já é do gestor. É o único sítio do
        # módulo que tira a etiqueta (as outras saídas da conta tiram-na pelo
        # `estado`, que sai do filtro parcial sozinho).
        {"$set": atualizacao, "$unset": {"posto_em_curso": ""}},
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_JA_ENTREGUE)

    venda.update(atualizacao)
    # Devolve-se a conta ENTREGUE, e não a seguinte: quem quer saber o que
    # fica à frente da operadora pergunta a `GET /pos/venda/aberta` — que é
    # exactamente o que o ecrã faz a seguir, e é isso que o faz voltar a
    # mostrar a conta que estava escondida atrás desta.
    return _venda_publica(venda, emissao_por_confirmar=True)


# --- Dividir a conta: N partes que somam SEMPRE o total ------------------------
#
# Três amigos, dois açaís e uma Coca-Cola: ou dividem por igual, ou cada um
# paga o que consumiu — e cada um quer a SUA fatura.
#
# **A decisão que mantém o núcleo fiscal intacto: cada parte é uma venda
# normal.** Dividir cria N contas-filhas a partir da conta-mãe, e daí em diante
# cada uma é exactamente como qualquer outra venda deste módulo — a sua
# referência determinística, a sua reserva atómica, a sua idempotência, o seu
# documento, e o `cancelar_venda` como saída para quem não paga. Nada muda em
# `precos.linha_de_venda`, em `fiscal.py` ou no `caixa_math`: tudo o que lá foi
# endurecido aplica-se às partes sem uma linha nova.
#
# **A regra que não se negoceia: as partes somam SEMPRE e exactamente o total.**
# Medido contra a conta Vendus real, um Açaí Regular de 8,99 € por três:
# `qty 0.333` factura 2,99 € (três somam 8,97) e `qty 0.3333` factura 3,00 €
# (três somam 9,00). Nenhuma das duas dá 8,99 — mandar a mesma fracção a toda a
# gente declara à Autoridade Tributária um valor diferente do que entrou na
# gaveta, e num dia com muitas divisões acumula. Por isso reparte-se o VALOR em
# cêntimos inteiros (`reparticao.repartir_centimos`) e é dele que se deriva a
# quantidade de cada parte (`reparticao.quantidade_para`), nunca ao contrário.


def _centimos(euros: float) -> int:
    """Euros (já arredondados a 2 casas por quem os calculou) em cêntimos
    inteiros. É a fronteira entre a vírgula flutuante, que só se usa para
    LER o que está gravado, e os inteiros, que é onde toda a repartição
    acontece."""
    return int(round(euros * 100))


def _partes_de_uma_linha(linha: Dict, partes: int) -> List[Optional[Dict]]:
    """A mesma linha repartida por N — uma entrada por parte, e `None` na
    parte que não leva nada desta linha.

    O que se reparte é o VALOR, em cêntimos: o bruto da linha e, à parte, o
    desconto que ela já dava. A quantidade de cada parte é depois derivada do
    valor (`quantidade_para`), e não o contrário — é essa ordem que faz as
    partes somarem o total ao cêntimo.

    **As opções vão INTEIRAS para cada parte.** Três pessoas a partilhar um
    açaí com Nutella têm de ver "Nutella" nas três faturas: o que se reparte é
    a quantidade, e o preço unitário (`gross_price`) já inclui as opções.

    **O desconto da linha viaja em EUROS, mesmo quando a mãe o tinha em
    percentagem.** Em euros porque é a única forma de fechar ao cêntimo: um
    `round` aplicado a cada fatia não devolve sempre o que devolve aplicado ao
    total, e essa diferença é a soma das faturas a divergir da gaveta. E porque
    o contrário é pior de outra maneira — um "-3,00 €" copiado tal e qual para
    as três filhas descontava 9,00 € numa conta que descontou 3,00, e
    `precos.linha_de_venda` recusaria a linha (desconto maior do que o bruto da
    fatia) com um 422 à frente do cliente."""
    li = _linha_vendus(linha)
    preco = li["gross_price"]
    bruto_centimos = _centimos(_bruto_da_linha(li))
    desconto_centimos = _centimos(_desconto_da_linha(li))

    if bruto_centimos == 0:
        # Uma linha que não vale nada — um artigo oferecido, com preço 0 — não
        # se reparte por valor: não há valor nenhum para repartir, e
        # `quantidade_para` recusa (com razão) um preço zero. Vai INTEIRA para
        # a primeira parte, a mesma que leva o cêntimo que sobra: aparece numa
        # fatura, como aparecia na conta, e não muda um cêntimo em nenhuma.
        return [_copia_da_linha(linha) if i == 0 else None for i in range(partes)]

    brutos = repartir_centimos(bruto_centimos, partes)
    descontos = repartir_centimos(desconto_centimos, partes)

    repartida = []  # type: List[Optional[Dict]]
    for bruto, desconto in zip(brutos, descontos):
        if bruto == 0:
            # Não chegou um cêntimo para esta pessoa (uma linha de 2 cêntimos
            # dividida por três). A linha não entra na conta dela: entrar com
            # quantidade zero punha um artigo a 0,00 € numa Fatura Simplificada
            # real.
            repartida.append(None)
            continue
        nova = _copia_da_linha(linha)
        nova["quantidade"] = quantidade_para(bruto, preco)
        nova["desconto_pct"] = None
        nova["desconto_eur"] = round(desconto / 100.0, 2) if desconto else None
        repartida.append(nova)
    return repartida


def _copia_da_linha(linha: Dict) -> Dict:
    """A linha da parte é um documento NOVO, com id novo, numa venda nova.

    Cópia PROFUNDA e não `dict(...)`: as `opcoes` e as `respostas_texto` são
    listas aninhadas, e uma cópia rasa deixava as N filhas a partilhar a MESMA
    lista — uma edição numa parte mexia nas outras. É o mesmo aliasing que já
    pôs um teste deste módulo a defender um defeito, um nível mais abaixo."""
    nova = deepcopy(linha)
    nova["id"] = str(uuid.uuid4())
    return nova


def _nova_parte(mae: Dict, linhas: List[Dict], desconto_global_centimos: int) -> Dict:
    """Uma parte, com a forma de qualquer outra venda deste módulo.

    `caixa_id`/`sessao_id`/`operador_id` são os da mãe — é o que faz o fecho de
    caixa somar as partes onde somava a conta. O `dispositivo_id` também, e não
    é detalhe: a `GET /pos/venda/aberta` filtra por ele, e sem o herdar um F5 a
    meio dos pagamentos deixava a operadora com o ecrã vazio e as partes por
    cobrar.

    O desconto global da mãe chega aqui já repartido e em EUROS, com a
    percentagem a `None` de propósito: uma percentagem copiada para as filhas
    voltava a incidir sobre a fatia já descontada — o cliente pagava menos do
    que a conta dizia."""
    return {
        "id": str(uuid.uuid4()),
        "loja_id": mae["loja_id"],
        "caixa_id": mae["caixa_id"],
        "sessao_id": mae["sessao_id"],
        "operador_id": mae.get("operador_id"),
        "dispositivo_id": mae.get("dispositivo_id"),
        "conta_mae_id": mae["id"],
        "linhas": linhas,
        "linhas_versao": 0,
        "desconto_global_pct": None,
        "desconto_global_eur": round(desconto_global_centimos / 100.0, 2) or None,
        "estado": "aberta",
        "criada_em": _agora(),
    }


def _confirma_que_as_partes_somam(
    mae: Dict, filhas: List[Dict], rota: str = "dividir"
) -> None:
    """A verificação que a spec exige, feita sobre as partes JÁ construídas e
    ANTES de qualquer escrita.

    "O Vendus arredonda de forma previsível, mas a defesa não é acreditar
    nisso — é confirmar." `quantidade_para` já confirma cada fatia sozinha;
    isto confirma o CONJUNTO, que é o número que o cliente pagou. Em cêntimos
    inteiros, nunca comparando floats.

    **`rota` escolhe a REDACÇÃO do 422, não a verificação** — a MESMA soma,
    partilhada pelas duas chamadoras (`dividir_conta` e `separar_conta`),
    só muda a frase que explica o que fazer a seguir. Para o `dividir_conta`
    "experimente outro número de pessoas" é uma acção real: `n` é um
    parâmetro do pedido. Para o `separar_conta` não há "número de pessoas"
    nenhum para experimentar — o número de partes é o comprimento da
    atribuição que o staff acabou de fazer, e o que resta fazer é rever
    essa atribuição, não contar pessoas outra vez (achado da revisão: a
    mensagem genérica mandava a operadora "experimentar outro número",
    sem nenhum número para mudar).

    Se não fechar, ninguém grava nada e a operadora recebe um 422 com um
    caminho à frente, em vez de N faturas que somam um cêntimo a mais do
    que entrou na gaveta."""
    esperado = _centimos(_totais(mae)["total"])
    soma = sum(_centimos(_totais(f)["total"]) for f in filhas)
    if soma == esperado:
        return
    if rota == "separar":
        detail = (
            "Esta separação não fecha ao cêntimo: as partes somariam "
            "%.2f € e a conta é de %.2f €. Nada foi alterado — reveja a "
            "atribuição das linhas a cada parte."
            % (soma / 100.0, esperado / 100.0)
        )
    else:
        detail = (
            "Esta conta não se consegue dividir por %d ao cêntimo: as "
            "partes somariam %.2f € e a conta é de %.2f €. Nada foi "
            "alterado — experimente outro número de pessoas."
            % (len(filhas), soma / 100.0, esperado / 100.0)
        )
    raise HTTPException(status_code=422, detail=detail)


def _a_mae_como_foi_lida(mae: Dict) -> Dict:
    """O filtro da escrita que trava a mãe: não a identidade e o estado, mas
    TUDO aquilo de que as filhas foram feitas.

    **O defeito que isto fecha.** Prender só `{"estado": "aberta"}` é a
    decisão-sobre-uma-leitura outra vez, num sítio onde a leitura é a conta
    inteira: entre o `find_one` da mãe e esta escrita há N+1 `await`s (o
    `_garante_sem_emissao` e os N inserts das filhas) e a mãe fica ABERTA
    durante toda essa janela — por isso as outras rotas de escrita entram lá
    dentro sem esbarrar em nada, e a divisão fechava na mesma sobre um retrato
    que já não era a conta. É a mesma lição de `_aplicar_as_linhas` ("para quem
    deriva do array `linhas` a condição do estado não chega"), aplicada a quem
    deriva a conta toda. Medido em processo, com dois separadores do POS na
    mesma conta:

    - **linhas** — mãe com 1 Açaí de 8,99 €; a meio da divisão por 2 entra uma
      Água de 1,00 €. A mãe ficava `separada` com 9,99 € e as filhas saíam
      [4,50 / 4,49] = 8,99 €: a água não era facturada por ninguém e a conta
      ficava travada PARA SEMPRE — uma conta `separada` não aceita juntar, nem
      descontar, nem cancelar, e não há rota nenhuma que desfaça uma divisão.
    - **desconto global** — mãe de 9,00 €; a meio da divisão por 3 entra um
      desconto de 3,00 €. As filhas saíam [3,00 / 3,00 / 3,00] = 9,00 € contra
      uma conta de 6,00 €: três Faturas Simplificadas REAIS à Autoridade
      Tributária com 3,00 € a mais do que o cliente devia pagar.

    **Por isso são estes três campos, e não um contador.** `linhas_versao`
    fecha o primeiro vector, mas não o segundo: `aplicar_desconto_global`
    escreve dois escalares e NÃO sobe versão nenhuma (de propósito — ver
    `_escrever_se_ainda_aberta`). Prendem-se então os próprios valores lidos.
    Não sobra nada de fora: `_totais` só depende de `linhas` e destes dois
    campos, e o resto do que as filhas herdam (`loja_id`, `caixa_id`,
    `sessao_id`, `operador_id`, `dispositivo_id`) nasce com a venda e nenhuma
    rota deste backend lhe volta a tocar.

    Prende os valores LIDOS, nunca valores fixos: um `linhas_versao: None`
    escrito à mão recusava a divisão em toda a conta que já tinha sido alterada
    uma vez — ou seja, em quase todas. Um campo ausente casa com `None`, tal
    como no Mongo (uma conta aberta antes do contador não precisa de migração).

    E o `_confirma_que_as_partes_somam` não substitui isto: confere as filhas
    contra o `mae` em memória — o retrato velho, não o que está gravado."""
    return {
        "id": mae["id"],
        "estado": "aberta",
        "linhas_versao": mae.get("linhas_versao"),
        "desconto_global_eur": mae.get("desconto_global_eur"),
        "desconto_global_pct": mae.get("desconto_global_pct"),
    }


async def _porque_nao_travou_a_mae(db, venda_id: str) -> str:
    """Qual das duas coisas aconteceu, para o 409 descrever a conta como ela
    está no instante em que a operadora o lê — a mesma disciplina de
    `_porque_nao_foi_cancelada`.

    O filtro de `_a_mae_como_foi_lida` falha por duas razões bem diferentes, e
    a operadora faz coisas diferentes em cada uma: ou a conta já não está
    aberta (emitida ou cancelada por quem chegou primeiro) e não há divisão
    nenhuma a fazer, ou está aberta e só mudou por baixo — e aí divide-se outra
    vez. Dizer-lhe "esta venda já foi emitida ou cancelada" sobre uma conta que
    ela tem aberta à frente mandava-a procurar no Vendus um documento que não
    existe."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if (venda or {}).get("estado") == "aberta":
        return _MSG_CONTA_MUDOU_ANTES_DE_DIVIDIR
    return _MSG_VENDA_NAO_ABERTA


async def _porque_nao_ficou_dividida(db, venda_id: str) -> str:
    """A mensagem do 409 da divisão DESFEITA — escolhida pelo estado que a
    conta tem NO INSTANTE EM QUE A OPERADORA A LÊ, e não pelo que ela tinha
    quando a compensação começou.

    É o `_porque_nao_foi_cancelada` com as palavras da divisão, e existe pela
    mesma lição (A3): um diagnóstico velho manda chamar o gestor a uma loja
    cheia por causa de uma conta perfeitamente boa.

    As três saídas possíveis, todas verdadeiras no instante em que se lêem:
    1. a mãe ficou `emitida` — a emissão ganhou mesmo e saiu UMA Fatura
       Simplificada da conta inteira: não há divisão nenhuma a repetir, e o
       que a operadora precisa de saber é que a fatura SAIU;
    2. a reserva ainda lá está — a emissão continua viva ou ficou por
       confirmar: é o caso em que o gestor faz falta, e a mensagem de sempre
       (`_MSG_VENDA_COM_EMISSAO`) está certa;
    3. nem uma coisa nem outra — o `finalizar` releu a mãe, encontrou-a
       `separada`, libertou a reserva e abortou sem emitir; a compensação
       repôs a conta `aberta` e dividir outra vez resolve."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    estado = (venda or {}).get("estado")
    if estado == "emitida":
        return _MSG_DIVISAO_EMITIDA_ENTRETANTO
    if await _tem_reserva_fiscal(db, venda_id):
        return _MSG_VENDA_COM_EMISSAO
    if estado == "aberta":
        return _MSG_DIVISAO_ABORTADA_SEM_EMISSAO
    # Estado inesperado (a venda desapareceu, ou ficou num estado que este
    # módulo não escreve): não se inventa um diagnóstico — vale a mensagem
    # mais conservadora, a que manda confirmar antes de mexer.
    return _MSG_VENDA_COM_EMISSAO


async def _grava_as_partes(
    db, venda_id: str, mae: Dict, filhas: List[Dict], modo: str
) -> dict:
    """A escrita partilhada por `dividir_conta` e `separar_conta` (Task 4),
    depois de cada rota já ter construído as SUAS filhas — o dividir reparte
    um valor por N, o separar usa a atribuição do staff, mas dali em diante o
    raciocínio é o MESMO, e vive aqui uma única vez para as duas rotas nunca
    poderem divergir.

    **A ordem das escritas, e o que ela custa.** As filhas nascem primeiro e a
    mãe trava a seguir: ao contrário, existia um instante em que a conta estava
    `separada` sem partes nenhumas — a operadora sem conta para cobrar e sem
    nada para desfazer. O preço desta ordem é a janela entre a leitura da mãe e
    a escrita que a trava, e é por isso que essa escrita é CONDICIONADA à mãe
    COMO ELA FOI LIDA — estado, versão das linhas e desconto global
    (`_a_mae_como_foi_lida`) — e decide pelo `matched_count`, não pelas guardas
    de quem chamou. Se alguém ganhou a corrida nessa janela (a emissão, ou o
    outro separador do POS a juntar uma linha), as filhas que acabaram de
    nascer são apagadas e a operadora leva um 409 que diz qual das duas coisas
    foi.

    **E a escrita casar não chega.** A emissão pode ter reservado DEPOIS do
    `_garante_sem_emissao` (perguntado por quem chamou, antes de construir as
    filhas) sem mudar nada na mãe — nesse caso a escrita condicional casa, e é
    o `_ligar_venda_ao_documento` que carimba `emitida` por cima do `separada`
    mais tarde. Por isso pergunta-se outra vez pela reserva DEPOIS de travar a
    mãe, e compensa-se: filhas apagadas, mãe reposta `aberta` (condicionada a
    `separada`, nunca por cima de uma venda que já emitiu) e 409."""
    for filha in filhas:
        await db[COLECOES["vendas"]].insert_one(dict(filha))

    # `reparticao_modo` fica gravado NA MÃE, na mesma escrita que a trava, e
    # não porque o servidor precise dele para alguma coisa: precisa o ECRÃ.
    # "Divisão de Conta" e "Conta Separada" são dois cabeçalhos diferentes, e
    # sem este campo a lista de partes recuperada do servidor
    # (`contas_repartidas`, abaixo) tinha de adivinhar qual deles escrever —
    # ou seja, tinha de mentir metade das vezes. Uma repartição feita ANTES
    # deste campo existir não o tem: sai `None` e o ecrã fica com o cabeçalho
    # por omissão, que é o que ele já fazia — nada rebenta e não é preciso
    # migração nenhuma.
    atualizacao = {"estado": "separada", "reparticao_modo": modo}
    resultado = await db[COLECOES["vendas"]].update_one(
        _a_mae_como_foi_lida(mae), {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        # A mãe já não é aquela de que estas filhas foram feitas: ou deixou de
        # estar aberta (emitida ou cancelada por quem chegou primeiro), ou
        # ganhou linhas / um desconto entretanto — ver `_a_mae_como_foi_lida`.
        # Em qualquer dos casos as filhas não podem ficar: eram N contas órfãs
        # prontas a emitir N Faturas Simplificadas de uma conta que não foi
        # dividida. Apagá-las é seguro porque ninguém do lado de fora chegou a
        # ver os `id` delas.
        for filha in filhas:
            await db[COLECOES["vendas"]].delete_one({"id": filha["id"]})
        raise HTTPException(
            status_code=409, detail=await _porque_nao_travou_a_mae(db, venda_id))

    # A janela que o `_garante_sem_emissao` de quem chamou NÃO fecha — e esta
    # era a única das rotas de escrita a deixá-la aberta. Entre aquela pergunta
    # e esta escrita estão os N inserts das filhas, e lá dentro cabe o
    # `finalizar` (fiscal.py) inteiro: reserva, relê a mãe — que continua
    # `aberta`, porque só a travamos aqui em baixo — e segue para o Vendus. A
    # escrita condicional acima CASA na mesma (a mãe não mudou: mesmo estado,
    # mesmas linhas, mesmo desconto), e quando o Vendus responde o
    # `_ligar_venda_ao_documento` carimba `emitida` por cima do `separada` sem
    # condição de estado nenhuma. Ficava no sistema uma mãe com uma Fatura
    # Simplificada REAL de 8,99 € entregue à Autoridade Tributária E três
    # filhas `aberta` prontas a emitir outros 8,99 € — que a
    # `GET /pos/venda/aberta` ainda devolve sozinha à operadora, porque as
    # filhas herdam a sessão e o dispositivo da mãe (`_nova_parte`). O cliente
    # pagava duas vezes e declaravam-se 17,98 € de uma conta de 8,99 €.
    #
    # Por isso pergunta-se OUTRA VEZ depois de escrever, como o
    # `cancelar_venda` já faz na mesma janela, e compensa-se.
    #
    # **A ordem da compensação é deliberada: as filhas primeiro, a mãe depois**,
    # e mantém-se depois de esta ronda ter medido o preço dela. Filhas órfãs
    # vivas são N Faturas Simplificadas REAIS a mais, e uma FS entregue à
    # Autoridade Tributária não se desfaz; uma mãe por repor é dinheiro por
    # contar, que um humano ainda arruma. Repõe-se o que se pode perder, nunca
    # o que se pode duplicar — e repor a mãe PRIMEIRO trocava esta troca ao
    # contrário: um processo que morresse entre as duas escritas deixava a mãe
    # `aberta` E as N filhas `aberta`, que é o desfecho de 17,98 € numa conta
    # de 8,99 € descrito aqui em cima.
    #
    # **O que esta ordem custa, medido, e onde é que se paga.** Entre o
    # `delete_one` da última filha e a reposição da mãe, `_contas_do_balcao`
    # responde `[]` — o balcão PARECE livre, e um segundo separador que abra
    # ali a conta do cliente seguinte fica com a etiqueta deste posto. A
    # reposição colide então com o índice único. O que não se paga mais é a
    # mãe: `_repor_aberta` deixou de desistir nessa colisão (largou a etiqueta
    # e repôs `aberta` na mesma), e por isso a mãe volta SEMPRE ao Z e ao ecrã.
    # Sem isso ela ficava `separada` sem partes — invisível aos três conjuntos
    # que filtram por `estado: "aberta"` —, e foi assim que 11,64 € saíram de
    # um Z assinado.
    #
    # Fica de fora, por escolha e não por esquecimento, a morte do processo
    # ENTRE as duas escritas: aí a mãe fica mesmo `separada` sem partes.
    #
    # **E até esta ronda essa mitigação estava escrita aqui e era FALSA no
    # segundo passo.** Dizia-se: a reserva ainda está viva, trava o fecho e a
    # conta aparece em `/fiscal/reservas-presas`; quem a arruma é o gestor, por
    # lá. A primeira metade era verdade. A segunda era o gatilho: o gestor
    # carregava em LIBERTAR — a única saída que a lista lhe oferece — e a
    # partir daí a conta desaparecia de TODOS os conjuntos ao mesmo tempo.
    # Medido, sobre uma mãe de 11,64 €: `libertada: True`, balcão `null`,
    # `/caixa/contas-esquecidas` 0, `/fiscal/reservas-presas` 0, o diálogo do
    # fecho `quantas=0 total=0,00`, e o `POST /pos/caixa/fechar` a responder
    # **200 com o Z assinado a dizer «por cobrar 0,00 €»**. O remédio que o
    # sistema nomeia era o gatilho.
    #
    # Já não é: uma mãe `separada` SEM PARTES é, por si só, uma conta por
    # resolver (`por_resolver.contas_por_resolver`) — não depende da reserva
    # para ser vista. Libertar a reserva deixa de a tirar do último conjunto
    # que a via: ela continua no diálogo, no Z e na lista do gestor, com o
    # motivo escrito, e é lá que se arruma.
    #
    # E a reposição é CONDICIONADA a {"estado": "separada"} — o único estado que
    # a NOSSA escrita pode ter deixado — exactamente pela razão do
    # `cancelar_venda`: se o `_gravar_documento` já pôs `emitida` por cima dela,
    # o filtro não casa e não lhe tocamos. Incondicional, reabria como `aberta`
    # uma venda com FS real e ATCUD, que é o estrago que isto existe para
    # evitar.
    if await _tem_reserva_fiscal(db, venda_id):
        for filha in filhas:
            await db[COLECOES["vendas"]].delete_one({"id": filha["id"]})
        await _repor_aberta(
            db, {"id": venda_id, "estado": "separada"}, {"estado": "aberta"}
        )
        raise HTTPException(
            status_code=409, detail=await _porque_nao_ficou_dividida(db, venda_id)
        )

    mae.update(atualizacao)
    # A MESMA forma que `contas_repartidas` devolve ao recuperar isto do
    # servidor — `modo` incluído. É de propósito: o ecrã constrói a
    # repartição a partir das duas respostas, e duas formas diferentes para a
    # mesma coisa acabam com um dos dois caminhos a esquecer-se de um campo.
    return {
        "modo": modo,
        "conta_mae": _venda_publica(mae),
        "partes": [_venda_publica(f) for f in filhas],
    }


@router.post("/pos/venda/{venda_id}/dividir", status_code=201)
async def dividir_conta(
    venda_id: str, dados: PedidoDividir, operador: Dict = Depends(operador_atual)
) -> dict:
    """Divide a conta por N pessoas: N contas-filhas que somam exactamente o
    total, e uma mãe que passa a `separada` e deixa de ser finalizável.

    As guardas de entrada são as das outras rotas de escrita, e pelas mesmas
    razões: a venda tem de ser da loja do token (`_obter_venda_da_loja`), tem
    de estar ABERTA (`_garante_aberta` — uma conta já dividida cai aqui, com a
    mensagem própria) e não pode ter emissão em curso
    (`_garante_sem_emissao`). Esta última é a mais importante das três: dividir
    uma conta congelada fazia nascer N contas prontas a emitir enquanto a mãe
    podia estar a virar uma Fatura Simplificada real.

    A construção das filhas (repartir o valor de cada linha e o desconto
    global por N, e confirmar que somam o total) é o que torna esta rota
    diferente do `separar_conta` (Task 4); a escrita, o travão da mãe e a
    compensação de uma corrida são o MESMO código nas duas — ver
    `_grava_as_partes`."""
    db = obter_db()
    mae = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(mae)
    _garante_do_balcao(mae)
    _garante_que_nao_e_ja_uma_parte(mae)
    await _garante_sem_emissao(db, venda_id)
    # A conta que nasce daqui herda o `sessao_id` da mãe (`_nova_parte`): sem
    # esta guarda, dividir uma conta numa sessão FECHADA fazia nascer partes
    # `aberta` num turno cujo Z já estava assinado — medido, 2 partes numa
    # sessão fechada. E em `a_fechar` era pior ainda: nasciam DEPOIS de o
    # fecho ter contado as contas abertas, e ficavam fora do próprio Z que
    # existe para as mencionar.
    await _garante_sessao_desta_venda_aberta(db, mae)

    linhas_da_mae = mae.get("linhas") or []
    if not linhas_da_mae:
        raise HTTPException(status_code=422, detail=_MSG_CONTA_VAZIA_NAO_SE_DIVIDE)

    n = dados.partes
    try:
        # `ValueError` só sai daqui quando nenhuma quantidade com as casas de
        # `CASAS_DA_QUANTIDADE` produz a fatia ao cêntimo (medido: não acontece
        # em nenhum preço de 0,01 € a 999,99 €). Vira 422 e não um 500: é a
        # conta que não se divide assim, não o servidor que se partiu.
        repartidas = [_partes_de_uma_linha(li, n) for li in linhas_da_mae]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # O desconto GLOBAL também se reparte. Se ficasse só na mãe, as partes
    # somavam mais do que o cliente pagou — e a mãe já não emite nada.
    globais = repartir_centimos(_centimos(_totais(mae)["desconto_global"]), n)

    filhas = [
        _nova_parte(mae, [r[i] for r in repartidas if r[i] is not None], globais[i])
        for i in range(n)
    ]
    _confirma_que_as_partes_somam(mae, filhas)

    return await _grava_as_partes(db, venda_id, mae, filhas, "dividir")


# --- Separar a conta: cada parte leva as UNIDADES que o staff atribuiu (Task 4) --
#
# Três amigos, dois açaís e uma Coca-Cola: quando não pagam por igual, cada um
# leva o que consumiu. Ao contrário do `dividir_conta` (que reparte um VALOR
# por N pessoas, ao cêntimo), aqui é o STAFF que diz quem leva o quê — por
# isso não há fracções: uma linha de 2 açaís vai 1 para cada, nunca 0.6 para
# um e 1.4 para o outro. Isto não é só descrito — `PedidoSepararLinha` RECUSA
# com 422 uma quantidade que não seja um número inteiro de unidades. É essa
# diferença que torna esta rota mais simples do que a anterior, e é também
# por que a spec pôs as fracções fora do âmbito daqui.
#
# A decisão estrutural é a MESMA da divisão: cada parte é uma venda normal, e
# a escrita que a cria — trancar a mãe, perguntar outra vez pela emissão,
# compensar uma corrida — é literalmente o MESMO código (`_grava_as_partes`),
# não uma segunda cópia dele. O desconto (de linha e global) da mãe TAMBÉM
# viaja para as partes, tal como na divisão — repartido PROPORCIONALMENTE ao
# que cada parte leva (`_reparte_por_peso`), e não em fatias iguais como lá:
# aqui as partes não pesam o mesmo entre si. E a soma confirma-se ANTES de
# qualquer escrita (`_confirma_que_as_partes_somam`), a mesma rede que já
# existia para a divisão.

# Unidade em que as quantidades se SOMAM e se COMPARAM nesta rota — nunca em
# float. `0.1 + 0.2 != 0.3` na vírgula flutuante binária, e aqui o que está em
# jogo é uma conta fechar (ou recusar) ao cêntimo certo. Usa a MESMA resolução
# de `reparticao.CASAS_DA_QUANTIDADE`, e não uma segunda escolhida à parte,
# para uma quantidade que "bate certo" aqui não poder "não bater" lá.
_UNIDADES_POR_QUANTIDADE = 10 ** CASAS_DA_QUANTIDADE


def _unidades(quantidade: float) -> int:
    """A quantidade em UNIDADES INTEIRAS, só para somar e comparar sem os
    erros da vírgula flutuante — nunca para gravar nem para calcular preço,
    que continuam em float como o resto do módulo."""
    return round(quantidade * _UNIDADES_POR_QUANTIDADE)


def _reparte_por_peso(total_centimos: int, pesos: List[int]) -> List[int]:
    """Reparte `total_centimos` pelos `pesos` dados, PROPORCIONALMENTE — ao
    contrário de `reparticao.repartir_centimos`, que reparte em partes
    IGUAIS (a ferramenta certa para o `dividir_conta`, que já repartiu o
    VALOR de cada linha por N antes de chegar aqui). Aqui as partes não têm
    o mesmo peso entre si: um desconto de 10% sobre dois açaís e uma
    Coca-Cola não pode acabar metade em cima de quem só levou a Coca-Cola.

    Chão da divisão inteira para cada peso, e os cêntimos que sobram vão,
    um a um, para quem tem o maior resto por arredondar — o método do maior
    resto, que é o que faz a soma fechar ao cêntimo exacto sem beneficiar
    sempre a mesma parte. Tudo em ARITMÉTICA INTEIRA (multiplicação e resto
    da divisão, nunca uma divisão em vírgula flutuante): a mesma disciplina
    de `repartir_centimos`, só que com pesos diferentes em vez de partes
    iguais."""
    n = len(pesos)
    soma_pesos = sum(pesos)
    if soma_pesos <= 0 or total_centimos == 0:
        # Nada para repartir (ou nada com peso nenhum para o receber): todas
        # as partes ficam a 0, e é o `_confirma_que_as_partes_somam` a seguir
        # que apanha o caso em que isso deixa a soma por bater.
        return [0] * n
    numeradores = [total_centimos * peso for peso in pesos]
    base = [num // soma_pesos for num in numeradores]
    restos = [num % soma_pesos for num in numeradores]
    falta = total_centimos - sum(base)
    for i in sorted(range(n), key=lambda i: restos[i], reverse=True)[:falta]:
        base[i] += 1
    return base


def _partes_da_separacao(mae: Dict, dados: PedidoSeparar) -> List[List[Dict]]:
    """As linhas de cada parte, tal como o staff as atribuiu — e a
    verificação central desta rota: a soma do que cada linha da mãe recebeu
    tem de dar EXACTAMENTE a quantidade que ela tinha. Nem menos (um artigo
    sem dono sai da loja sem fatura e sem pagamento) nem mais (fatura-se o
    que não se vendeu) — e são dois 422 com mensagens diferentes, porque o
    que a operadora tem de fazer a seguir também é diferente.

    **O desconto de uma linha reparte-se pelas partes que a atribuição lhe
    deu — nunca copiado inteiro, e isto vale IGUALMENTE para `desconto_eur`
    e para `desconto_pct`.** Uma linha de 2 unidades com um desconto de PAR
    (`desconto_eur`, o tecto validado sobre a linha INTEIRA) separada 1+1
    não pode dar a cada filha o desconto completo: é exactamente o defeito
    que a docstring de `_partes_de_uma_linha` (Task 3) descreve — "um
    '-3,00 €' copiado tal e qual para as três filhas descontava 9,00 € numa
    conta que descontou 3,00".

    O `desconto_pct` tinha aqui a mesma garantia falsa que a Task 3 já
    tinha documentado como falsa: "incide sobre o bruto de CADA filha, que
    encolhe sozinho" ignora que o Vendus ARREDONDA o desconto de cada linha
    ao cêntimo — `round(bruto × pct / 100, 2)` — e o arredondamento feito
    em CADA filha, separadamente, não devolve sempre o que o mesmo
    arredondamento devolve aplicado à linha INTEIRA. Medido: um Açaí de
    3,02 € × 2 com -20% de linha desconta 1,21 € de uma vez (mãe = 4,83 €)
    mas 0,60 € + 0,60 € = 1,20 € separado 1+1 (partes = 4,84 €) — a mesma
    divergência de 1 cêntimo que o `desconto_eur` já tinha, só que
    escondida atrás de uma percentagem em vez de um valor.

    Por isso os dois convertem-se em EUROS pela mesma função que já lê
    qualquer um dos dois (`_desconto_da_linha`, sobre a linha INTEIRA como
    estava na mãe) e repartem-se PROPORCIONALMENTE às unidades atribuídas
    (`_reparte_por_peso`), em cêntimos — a mesma disciplina de
    `_partes_de_uma_linha`, que também converte a percentagem em euros
    antes de repartir e nunca ao contrário. Cada filha sai com
    `desconto_pct = None` e `desconto_eur` já com a fatia que lhe
    corresponde: uma percentagem copiada para a filha voltaria a arredondar
    sozinha, refazendo o mesmo defeito que esta conversão existe para
    fechar."""
    por_linha = {li["id"]: li for li in (mae.get("linhas") or [])}
    atribuido = {lid: 0 for lid in por_linha}
    # As unidades que cada parte atribuiu a cada linha, pela MESMA ordem em
    # que `dados.partes` as lista — é o peso que `_reparte_por_peso` usa a
    # seguir, e tem de estar sincronizado com a segunda passagem lá em baixo.
    unidades_por_linha = {lid: [] for lid in por_linha}  # type: Dict[str, List[int]]

    for parte in dados.partes:
        for pl in parte.linhas:
            linha = por_linha.get(pl.linha_id)
            if linha is None:
                raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)
            unidades = _unidades(pl.quantidade)
            atribuido[pl.linha_id] += unidades
            unidades_por_linha[pl.linha_id].append(unidades)

    for lid, linha in por_linha.items():
        total_linha = linha.get("quantidade", 1)
        atribuido_linha = atribuido[lid] / _UNIDADES_POR_QUANTIDADE
        nome = linha.get("produto_nome") or "Este artigo"
        if atribuido[lid] < _unidades(total_linha):
            raise HTTPException(
                status_code=422,
                detail=(
                    "\"%s\" ainda tem artigos por atribuir a alguém: a conta "
                    "tem %g e as partes só levam %g. Um artigo que não é de "
                    "ninguém sai da loja sem fatura e sem pagamento — "
                    "atribua-o a uma das partes antes de separar a conta."
                    % (nome, total_linha, atribuido_linha)
                ),
            )
        if atribuido[lid] > _unidades(total_linha):
            raise HTTPException(
                status_code=422,
                detail=(
                    "\"%s\" ficou atribuída a mais gente do que artigos tem: "
                    "a conta tem %g e as partes pedem %g. Fatura-se o que foi "
                    "vendido, nunca mais — reveja a atribuição desta linha."
                    % (nome, total_linha, atribuido_linha)
                ),
            )

    # Só depois de confirmado que cada linha bate certo é que se reparte o
    # desconto dela pelas partes — pelos MESMOS pesos que acabaram de ser
    # validados. `_desconto_da_linha` lê o desconto da linha INTEIRA em
    # euros, seja ele guardado em `desconto_eur` ou em `desconto_pct` (o
    # Vendus só aceita um dos dois por linha) — a mesma função que
    # `_partes_de_uma_linha` (Task 3) já usa para a mesma conversão.
    descontos_por_linha = {}  # type: Dict[str, List[int]]
    for lid, linha in por_linha.items():
        desconto_linha_eur = _desconto_da_linha(_linha_vendus(linha))
        if desconto_linha_eur:
            descontos_por_linha[lid] = _reparte_por_peso(
                _centimos(desconto_linha_eur), unidades_por_linha[lid]
            )

    # Segunda passagem por `dados.partes`, agora a construir as linhas de
    # facto — na MESMA ordem da primeira, para o índice de cada linha_id
    # apanhar a fatia de desconto que lhe corresponde em
    # `descontos_por_linha`.
    indice_por_linha = {lid: 0 for lid in por_linha}
    linhas_por_parte = []
    for parte in dados.partes:
        linhas_da_parte = []
        for pl in parte.linhas:
            linha = por_linha[pl.linha_id]
            nova = _copia_da_linha(linha)
            nova["quantidade"] = pl.quantidade
            if pl.linha_id in descontos_por_linha:
                i = indice_por_linha[pl.linha_id]
                fatia_centimos = descontos_por_linha[pl.linha_id][i]
                # A percentagem NUNCA viaja para a filha — voltaria a
                # arredondar sozinha (o próprio defeito que isto corrige).
                # O desconto desta linha já saiu em euros de
                # `_desconto_da_linha` lá em cima, seja qual for a forma em
                # que a mãe o guardava.
                nova["desconto_pct"] = None
                nova["desconto_eur"] = round(fatia_centimos / 100.0, 2) or None
                indice_por_linha[pl.linha_id] += 1
            linhas_da_parte.append(nova)
        linhas_por_parte.append(linhas_da_parte)

    return linhas_por_parte


@router.post("/pos/venda/{venda_id}/separar", status_code=201)
async def separar_conta(
    venda_id: str, dados: PedidoSeparar, operador: Dict = Depends(operador_atual)
) -> dict:
    """Separa a conta pelas linhas que o STAFF atribuiu a cada pessoa — ao
    contrário do `dividir_conta`, que reparte um VALOR por N. As guardas de
    entrada são as mesmas três da divisão (`_obter_venda_da_loja`,
    `_garante_aberta`, `_garante_sem_emissao`), e a escrita que segue —
    trancar a mãe condicionada a como foi lida, perguntar outra vez pela
    emissão, compensar uma corrida — é o MESMO ajudante que a divisão usa
    (`_grava_as_partes`), não uma segunda implementação dele.

    **O desconto GLOBAL da mãe reparte-se pelas partes, PROPORCIONALMENTE
    ao que cada uma vale** (`_reparte_por_peso`, pesada pelo líquido de
    linhas de cada parte) — nunca fica todo na mãe: uma mãe `separada` não
    emite mais nada, e um desconto que ficasse só nela desaparecia,
    facturando-se às partes o valor CHEIO. E nunca em fatias iguais como o
    `dividir_conta` (que pode, porque já repartiu o valor de cada linha em N
    fatias iguais): aqui as partes não pesam o mesmo entre si, e um desconto
    de 10% sobre dois açaís não pode acabar metade em cima de uma
    Coca-Cola.

    **A soma confirma-se ANTES de qualquer escrita**
    (`_confirma_que_as_partes_somam`, a mesma rede que o `dividir_conta` já
    usa) — nunca depois. Uma linha cujo desconto (agora reduzido à fatia
    certa) ainda assim não bata com o bruto da parte, ou uma divergência de
    arredondamento entre a soma das partes e a mãe, rebentam aqui, em
    memória, com um 422 e nada gravado — não a meio das escritas, com a mãe
    já `separada` e filhas órfãs vivas."""
    db = obter_db()
    mae = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(mae)
    _garante_do_balcao(mae)
    _garante_que_nao_e_ja_uma_parte(mae)
    await _garante_sem_emissao(db, venda_id)
    # A mesma guarda (e a mesma razão) do `dividir_conta`: as partes herdam o
    # `sessao_id` da mãe, e um turno fechado não pode ganhar contas novas.
    await _garante_sessao_desta_venda_aberta(db, mae)

    if not (mae.get("linhas") or []):
        raise HTTPException(status_code=422, detail=_MSG_CONTA_VAZIA_NAO_SE_DIVIDE)

    linhas_por_parte = _partes_da_separacao(mae, dados)

    # Pesos para o desconto global: o líquido de CADA parte (bruto já menos
    # o desconto de linha, antes do global) — a mesma base sobre a qual
    # `_desconto_global_eur` incide na mãe. Um dict só com "linhas" não tem
    # desconto global nenhum, por isso `_totais(...)["total"]` aqui é
    # exactamente esse líquido.
    pesos = [
        _centimos(_totais({"linhas": linhas})["total"]) for linhas in linhas_por_parte
    ]
    # Uma parte cujas linhas somam 0,00 € (só artigos oferecidos, preço 0) é
    # tão presa como uma parte sem linha nenhuma: `fiscal.finalizar` recusa
    # `total <= 0` (a MESMA guarda que aqui se antecipa, `_MSG_TOTAL_NAO_
    # POSITIVO` em fiscal.py) e só sobra cancelar — uma venda `aberta` para
    # sempre na sessão, que a operadora nem vê porque não tem nada visível
    # de errado. Recusa-se aqui, ANTES de gravar, e não se descobre isto
    # três clientes depois com uma conta presa.
    if any(peso <= 0 for peso in pesos):
        raise HTTPException(status_code=422, detail=_MSG_PARTE_SEM_VALOR)
    globais = _reparte_por_peso(_centimos(_totais(mae)["desconto_global"]), pesos)

    filhas = [
        _nova_parte(mae, linhas, globais[i])
        for i, linhas in enumerate(linhas_por_parte)
    ]
    _confirma_que_as_partes_somam(mae, filhas, rota="separar")

    return await _grava_as_partes(db, venda_id, mae, filhas, "separar")


# --- As partes por cobrar, ao arrancar o ecrã ---------------------------------
#
# Declarada ANTES de `GET /pos/venda/{venda_id}` (que está no fim do
# ficheiro), pela razão de sempre: as duas casam com um caminho de três
# segmentos e a de `{venda_id}` casa com qualquer um. Abaixo dela, "repartidas"
# era lido como um id de venda e a operadora apanhava um 404.


@router.get("/pos/venda/repartidas")
async def contas_repartidas(
    caixa_id: str, operador: Dict = Depends(operador_atual)
) -> List[dict]:
    """As contas repartidas deste posto que ainda têm gente por pagar — cada
    uma com a mãe e com TODAS as suas partes, no formato de `dividir_conta`.

    **Porque é uma rota nova e não um alargamento do `GET /pos/venda/aberta`.**
    A tentação era acrescentar as partes à resposta dessa rota, já que é ela
    que o ecrã chama ao arrancar. Três razões decidiram contra, e a terceira
    sozinha chegava:

    1. **Ela responde `null`, e é isso que dá a resposta.** `venda_aberta`
       devolve `Optional[dict]`: `null` quer dizer "não há conta em curso", e
       o ecrã lê essa resposta como a conta que vai pôr à frente
       (`aplicarVenda(respVenda.data || null)`). Uma conta repartida deixa
       precisamente o posto SEM conta em curso — a mãe fica `separada` e o
       ecrã fica vazio — por isso o caso que mais interessa aqui é
       exactamente aquele em que a outra rota tem de continuar a responder
       `null`. Embrulhar tudo num `{conta: ..., partes: [...]}` mudava o
       significado da resposta dela para todos os chamadores de uma vez.
    2. **São dois âmbitos e duas cardinalidades.** Aquela pergunta é "qual é a
       conta que está à frente" e responde UMA (a mais recente); esta é
       "quanto é que ficou por receber neste posto" e responde N, e as N são
       contas que não estão à frente de ninguém.
    3. **A que existe é o caminho de recuperação da conta em curso, e não se
       parte o que salva o balcão.** É por ela que o posto recupera a conta
       depois da tela de descanso e de um F5. Uma pergunta nova, que ninguém
       ainda faz, não pode custar-lhe nada — e uma rota separada é a única
       forma de garantir isso: falhe ela o que falhar, a conta em curso volta
       na mesma.

    **O âmbito é o da sessão E do dispositivo**, o mesmo (e pela mesma razão)
    de `GET /pos/venda/aberta`: as partes herdam o `dispositivo_id` da mãe
    (`_nova_parte`), e a repartição é o estado do ECRÃ daquele posto — o "PC
    Drive-Thru" não tem nada que mostrar as pessoas por cobrar do "PC Balcão",
    tal como não mostra a conta em curso dele. Quem tem de ver TODAS as contas
    abertas da sessão, venham do posto que vierem, é o fecho de caixa — e é lá
    que isso está (`caixa.py::_contas_abertas_da_sessao`).

    **Devolve as partes TODAS de cada mãe, não só as que faltam.** A faixa do
    balcão diz "Faltam cobrar 2 pessoas **de 3**", e a lista mostra o número
    da fatura das que já foram cobradas: com só as abertas na resposta, o "de
    3" virava "de 2" e a conta parecia mais pequena do que foi. O que decide
    se um grupo entra na resposta é ter pelo menos uma parte ainda `aberta`;
    uma repartição inteiramente resolvida não é dinheiro por receber e não
    tem de voltar ao ecrã.

    Sem sessão aberta, o 409 de `_sessao_aberta` — não há partes por cobrar
    numa caixa que não está aberta. Sem partes nenhumas, `[]`, que é o estado
    normal do balcão e não é erro nenhum.
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, caixa_id, operador["loja_id"])
    # Como em `venda_aberta`: exige-se uma caixa ABERTA para o ecrã existir,
    # mas não é ela que escolhe o conjunto.
    await _sessao_aberta(db, caixa_id)

    # **O MESMO conjunto da porta e do ecrã da conta em curso** — a MESMA
    # função (`_contas_do_balcao`), e é daqui que sai a resposta: as partes por
    # cobrar deste posto são, sem uma regra à parte, as contas deste conjunto
    # que têm `conta_mae_id`.
    #
    # A pergunta começa pelas PARTES por cobrar, e não pelas mães `separada`,
    # por uma questão de resposta: uma mãe separada cujas partes já foram
    # todas cobradas não é para mostrar, e começar por ela obrigava a
    # perguntar por cada uma para depois a deitar fora.
    abertas = await _contas_do_balcao(
        db, operador["loja_id"], operador.get("dispositivo_id"))

    # As mães pela ordem em que a parte aberta MAIS RECENTE de cada uma
    # aparece — a mesma regra do "a mais recente" de `venda_aberta`, para o
    # ecrã, que só tem lugar para uma repartição de cada vez, ficar com a que
    # a operadora estava mesmo a cobrar. `dict.fromkeys` guarda a ordem e tira
    # os repetidos numa passagem (Python 3.7+).
    maes_ids = list(dict.fromkeys(
        v["conta_mae_id"] for v in abertas if v.get("conta_mae_id")
    ))

    grupos = []
    for mae_id in maes_ids:
        # A mãe pelo âmbito de sempre — a loja do token. Uma parte não pode
        # arrastar para a resposta uma conta de outra loja, e o `find_one`
        # pode não encontrar nada (uma parte cuja mãe foi apagada à mão na
        # base de dados): aí salta-se o grupo em vez de rebentar o arranque do
        # ecrã inteiro.
        mae = await db[COLECOES["vendas"]].find_one(
            {"id": mae_id, "loja_id": operador["loja_id"]}
        )
        if mae is None:
            continue
        irmas = await (
            db[COLECOES["vendas"]]
            .find({"conta_mae_id": mae_id})
            .sort("criada_em", 1)
            .to_list(1000)
        )
        grupos.append({
            "modo": mae.get("reparticao_modo"),
            "conta_mae": _venda_publica(
                mae, emissao_por_confirmar=await _emissao_por_confirmar(db, mae)
            ),
            # O travão pergunta-se por PARTE, e não se assume `False` para
            # nenhuma: é desta lista que sai a conta que a operadora vai pôr à
            # frente para cobrar, e uma parte com uma emissão por confirmar
            # tem de chegar ao ecrã já travada — senão o EMITIR aparece aceso
            # por cima de uma Fatura Simplificada que pode ter saído, que é o
            # defeito que `emissao_por_confirmar` existe para fechar. São
            # poucas leituras (no máximo 20 partes por conta) e só correm
            # quando há mesmo uma repartição por cobrar.
            "partes": [
                _venda_publica(
                    irma, emissao_por_confirmar=await _emissao_por_confirmar(db, irma)
                )
                for irma in irmas
            ],
        })
    return grupos


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
