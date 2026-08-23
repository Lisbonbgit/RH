"""A FILA DE IMPRESSÃO — o que tem de sair em papel, e a garantia de que sai.

Sem isto, o cliente paga, a Fatura Simplificada vai à Autoridade Tributária e
**não leva papel** (que é obrigação legal, e é o QR desse papel que a app de
fidelização lê); a cozinha não recebe ficha nenhuma numa loja onde cada copo
tem nome, toppings e «levar ou comer aqui»; e a gaveta não abre.

## A ARQUITECTURA: o programa VAI BUSCAR, o ecrã não lhe entrega

O POS é uma página **https**. Uma página https não consegue falar com um
programa em `localhost` sem certificados próprios e sem que alguém os instale
e os renove em cinco lojas. Por isso a direcção é a contrária: o programa da
loja (`agente_impressao/`) liga-se ao servidor e PERGUNTA se há trabalho.

Três coisas saem de graça dessa escolha, e a terceira é a que interessa ao
balcão:

- não há nada a configurar na rede, e funciona atrás de qualquer firewall —
  é o PC da loja a ligar para fora, como o browser já faz;
- não há certificado nenhum a instalar nem a renovar;
- **se o browser fechar a meio, o talão sai na mesma.** O trabalho está no
  servidor, não no ecrã. Uma operadora que carregue em Finalizar e feche o
  Chrome sem querer não deixa o cliente sem documento.

## O CORAÇÃO: duas vezes ou nenhuma

O programa vai buscar, imprime, e diz que imprimiu. **A rede pode cair em
qualquer um dos três passos**, e não há forma de os tornar um só — a
impressora não faz parte da transacção.

A escolha está feita e é esta: **ANTES DUAS VEZES DO QUE NENHUMA.**

A razão não é técnica, é do balcão. Um talão a mais é papel: a operadora
deita-o fora e ninguém fica a perder. Um talão a MENOS é um cliente sem
documento — é a obrigação legal por cumprir, é o QR da fidelização que ele
não consegue ler, e é a operadora a explicar-lhe que o sistema falhou. Os dois
estragos não têm o mesmo tamanho, por isso a fila não é simétrica.

Na prática, isso decide-se em UM sítio: quando o programa vai buscar o
trabalho e depois se cala (morreu, a rede caiu, o PC reiniciou), **o trabalho
volta à fila**. Se ele tinha mesmo imprimido e só se perdeu a confirmação,
sai um segundo talão. Aceita-se.

A defesa que se mantém é a do outro lado: **um trabalho só pode ser entregue
a UM programa de cada vez**. A entrega é uma escrita CONDICIONADA ao estado
que se leu, e é o `matched_count` que decide quem ganha — a mesma disciplina
que este módulo já usa para a reserva atómica das faturas
(`fiscal.py::_reservar`) e para a intenção das notas de crédito. Dois
programas a perguntar ao mesmo tempo (um PC de reserva ligado por engano)
não levam o mesmo talão.

## E não pode ficar preso para sempre

Um trabalho entregue e nunca confirmado volta à fila ao fim de
`_ARRENDAMENTO_SEGUNDOS` — mas só até `_MAX_TENTATIVAS`. Depois disso fica
`falhado` e PÁRA.

O limite é obrigatório e a razão é a mesma frase que decidiu o resto: uma
impressora avariada com um trabalho a repetir-se para sempre não produz papel
nenhum, produz uma fila que cresce toda a noite e vomita duzentos talões na
manhã seguinte, quando alguém a arranjar. O limite não tira ao cliente a
hipótese de ter o papel — o talão fica guardado com a fatura
(`fat_documentos.talao_escpos`) e reimprime-se num toque no separador
Faturação. O que o limite tira é a repetição cega.

**`falhado` é VISÍVEL.** `GET /pos/impressao/estado` diz quantos são, e o ecrã
do POS mostra-o. Uma fila que desiste em silêncio é pior do que uma fila que
insiste.

## E o que ficou de ontem

Cada trabalho nasce com uma VALIDADE, e passada essa validade nunca chega a
sair. Uma loja que abre de manhã não quer vinte talões de ontem à noite a
sair — e a operadora que os visse sair não voltava a confiar na impressora.

A validade não é a mesma para todos, e a diferença é o que faz isto ser uma
decisão e não um número:

- **a gaveta são DOIS minutos.** Um impulso de abertura que chegasse dez
  minutos atrasado abria a gaveta do dinheiro com ninguém à frente dela.
  Aqui a validade não é cortesia, é segurança.
- **o resto são trinta minutos.** É mais tempo do que qualquer papel
  encravado que alguém esteja mesmo a desencravar, e menos do que uma pausa
  de almoço. Um cliente que saiu há meia hora não volta pelo papel — e o
  papel não se perdeu, está guardado com a fatura.

Quem arruma isto é a própria pergunta do programa (`_arrumar_a_fila`), não um
processo em segundo plano: sem ninguém a perguntar não há impressão nenhuma a
acontecer, por isso também não há nada a arrumar com pressa.

## E o que NUNCA se faz aqui

**O talão é consequência da fatura, nunca condição dela.** Se enfileirar
falhar — o Mongo em baixo, o índice em falta, o que for — a fatura continua
boa: perde-se o papel, nunca o registo. Por isso `enfileirar` NUNCA levanta
excepção para fora (ver a função), e quem a chama nunca precisa de a
embrulhar em nada.

E não se mexe no núcleo fiscal por causa disto: os dois pontos onde o POS
enfileira (`fiscal.finalizar` e `caixa.fechar_caixa`) enfileiram DEPOIS de o
documento existir, e uma linha só.
"""
import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from . import escpos
from .db import COLECOES, obter_db
from .pos_auth import dispositivo_atual, operador_atual
from .talao import pedido_da_cozinha, relatorio_z

logger = logging.getLogger(__name__)

router = APIRouter()

# As duas impressoras que existem em cada loja, e não mais. O dono foi claro:
# «Duas impressoras: Epson TM-m30 e TP8002, as mesmas nas caixas e nas
# cozinhas, e a impressora da cozinha está instalada no PC da caixa.» São
# PAPÉIS, não marcas nem portas — o programa da loja é que diz qual é a
# impressora do Windows que faz cada papel, e nada aqui sabe se é USB ou rede.
CAIXA = "caixa"
COZINHA = "cozinha"
_IMPRESSORAS = (CAIXA, COZINHA)

# Os tipos de trabalho. Servem para o ecrã e para o log dizerem o que é cada
# papel; a fila trata-os todos da mesma maneira, à excepção da validade da
# gaveta (ver `_VALIDADE_MINUTOS`).
TALAO = "talao"
PEDIDO = "pedido"
Z = "z"
SEGUNDA_VIA = "segunda_via"
GAVETA = "gaveta"

PENDENTE = "pendente"
RESERVADO = "reservado"
IMPRESSO = "impresso"
FALHADO = "falhado"
CADUCADO = "caducado"

# Quanto tempo um trabalho entregue pode ficar sem confirmação antes de voltar
# à fila. 60 s é muito mais do que uma impressão demora (décimos de segundo) e
# muito menos do que a paciência de quem está à espera do papel.
_ARRENDAMENTO_SEGUNDOS = 60

# Quantas vezes um trabalho pode ser entregue antes de a fila desistir. Ver a
# docstring do módulo: o limite existe para não haver duzentos talões a sair
# de madrugada, e não custa ao cliente o papel (que se reimprime).
_MAX_TENTATIVAS = 5

# A VALIDADE de cada tipo, em minutos. A gaveta é o caso especial, e é o único
# — ver a docstring do módulo.
_VALIDADE_MINUTOS = {GAVETA: 2}
_VALIDADE_MINUTOS_POR_OMISSAO = 30

# Quantos trabalhos se entregam de uma vez. Uma volta da fila leva os que
# estiverem à espera até este limite; o programa pergunta outra vez a seguir.
# O tecto existe para uma fila acumulada não devolver uma resposta de megabytes
# ao PC da loja de uma assentada.
_QUANTOS_DE_CADA_VEZ = 5

# A partir de quantos segundos sem o programa perguntar nada é que se diz ao
# ecrã que **não há programa nenhum a ouvir**. O agente pergunta de poucos em
# poucos segundos; 90 s cobre um pico de rede sem acender o aviso, e é curto o
# bastante para uma loja onde ninguém o instalou nunca o esconder.
_AGENTE_VIVO_SEGUNDOS = 90

# Quantos dias um trabalho já resolvido fica guardado antes de o Mongo o
# apagar sozinho (índice TTL, ver `db.py`). É história para uma pessoa ir ver
# o que aconteceu ao papel de ontem — não é registo de nada: o documento
# fiscal e o talão certificado ficam em `fat_documentos`, para sempre.
_DIAS_DE_HISTORIA = 7

_MSG_IMPRESSORA_INVALIDA = "Impressora desconhecida: só existem 'caixa' e 'cozinha'."
_MSG_TRABALHO_INEXISTENTE = "Não existe nenhum trabalho de impressão com este id nesta loja."
_MSG_RECIBO_INVALIDO = (
    "Este trabalho já não está reservado por si — entretanto voltou à fila ou "
    "foi dado como impresso. Nada foi alterado."
)
_MSG_DESISTIU = (
    "Entregue %d vezes ao programa de impressão sem nunca ser confirmado. A "
    "fila desistiu para não repetir para sempre — o papel reimprime-se à mão."
)
_MSG_CADUCOU = "Passou a validade sem chegar a ser impresso."
_MSG_VENDA_INEXISTENTE = "Não existe nenhuma conta com este id nesta loja."
_MSG_DOCUMENTO_INEXISTENTE = "Não existe nenhum documento com este id nesta loja."
_MSG_DOCUMENTO_SEM_TALAO = (
    "Esta fatura não tem o talão certificado guardado — foi emitida antes de o "
    "sistema o passar a guardar, ou o Vendus devolveu-o ilegível. O documento "
    "fiscal está bom; o que não há é papel para reimprimir daqui."
)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(momento: datetime) -> str:
    return momento.isoformat()


def _quando(valor: Optional[str]) -> Optional[datetime]:
    """Lê um instante gravado. Ilegível conta como AUSENTE, nunca como
    "agora": um `validade_ate` que não se percebe não pode ser lido como
    "ainda é válido para sempre" nem como "caducou já" por acidente — quem
    chama decide, e os dois sítios que decidem estão escritos."""
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


# --- Criar trabalho -----------------------------------------------------------


def _validade(tipo: str, agora: datetime) -> str:
    minutos = _VALIDADE_MINUTOS.get(tipo, _VALIDADE_MINUTOS_POR_OMISSAO)
    return _iso(agora + timedelta(minutes=minutos))


async def enfileirar(
    db,
    *,
    loja_id: str,
    impressora: str,
    tipo: str,
    dados: bytes,
    chave: str,
    dispositivo_id: Optional[str] = None,
) -> Optional[str]:
    """Põe UM trabalho na fila. Devolve o id, ou `None` se não entrou.

    **Nunca levanta excepção.** É a regra que sustenta a promessa toda deste
    módulo: o talão é consequência da fatura e nunca condição dela. Um
    `enfileirar` que rebentasse dentro do `finalizar` transformava uma
    emissão bem sucedida — com Fatura Simplificada REAL já entregue à
    Autoridade Tributária — num erro no ecrã, e um erro no ecrã com a venda
    aparentemente por emitir é exactamente o que faz a operadora carregar
    outra vez. Perde-se o papel; nunca o registo.

    **A `chave` é a idempotência da CRIAÇÃO**, e é onde se resolve a outra
    metade do "duas vezes": o índice único de `fat_trabalhos_impressao.chave`
    (ver `db.py`) impede que a mesma coisa entre duas vezes na fila. O
    `finalizar` é idempotente por desenho — uma segunda tentativa da mesma
    venda encontra o documento já gravado e devolve-o tal e qual — e sem esta
    chave essa segunda tentativa enfileirava um segundo talão do mesmo
    cliente.

    Quem quer repetição escolhe uma chave NOVA de propósito: a segunda via e
    a gaveta trazem um uuid, porque duas vezes ali é o que a pessoa pediu ao
    carregar duas vezes no botão.
    """
    if not dados:
        # Um trabalho sem bytes não é um trabalho: era papel em branco a sair
        # e a operadora a pensar que o sistema imprimiu.
        logger.warning(
            "[faturacao] impressão %s da loja %s ignorada: sem bytes nenhuns.",
            tipo, loja_id,
        )
        return None
    if impressora not in _IMPRESSORAS:
        logger.error("[faturacao] impressão pedida para %r, que não existe.", impressora)
        return None
    agora = _agora()
    trabalho = {
        "id": str(uuid.uuid4()),
        "chave": chave,
        "loja_id": loja_id,
        # QUEM o pediu. Não é por aqui que se ENTREGA (ver `_recolher`: a
        # entrega é por LOJA), mas fica gravado — é o que responde a "que PC
        # é que mandou isto?" quando um dia houver dois, e não custa nada.
        "dispositivo_id": dispositivo_id,
        "impressora": impressora,
        "tipo": tipo,
        "bytes_b64": base64.b64encode(dados).decode("ascii"),
        "estado": PENDENTE,
        "criado_em": _iso(agora),
        "validade_ate": _validade(tipo, agora),
        # A data em que o Mongo apaga isto sozinho (índice TTL, ver `db.py`).
        # É um `datetime` a sério e não a string ISO do resto do documento:
        # um índice TTL sobre uma string não apaga nada e não se queixa.
        "apagar_depois_de": agora + timedelta(days=_DIAS_DE_HISTORIA),
        # SEMPRE presente e a zero, nunca ausente: a entrega compara-o na
        # condição da escrita (ver `_recolher`), e no Mongo um campo ausente
        # não casa com uma igualdade a 0 — o trabalho ficava por entregar
        # para sempre, em silêncio.
        "tentativas": 0,
        "recibo": None,
        "reservado_em": None,
        "reservado_por": None,
        "terminado_em": None,
        "erro": None,
    }
    try:
        await db[COLECOES["trabalhos_impressao"]].insert_one(dict(trabalho))
    except DuplicateKeyError:
        # Já lá está — é a segunda tentativa da mesma emissão a passar por
        # aqui. Não é erro nenhum: é a defesa a funcionar.
        logger.info(
            "[faturacao] impressão %s já estava na fila (chave=%s).", tipo, chave)
        return None
    except Exception as e:  # noqa: BLE001 — o papel, nunca o registo (ver docstring)
        logger.error(
            "[faturacao] não foi possível pôr na fila a impressão %s da loja "
            "%s: %s. O documento fiscal NÃO é afectado — o que se perde é o "
            "papel, e ele reimprime-se.", tipo, loja_id, e,
        )
        return None
    return trabalho["id"]


# --- Os dois pontos onde o POS enfileira sozinho ------------------------------


async def enfileirar_venda_emitida(db, venda: Dict, documento: Dict) -> None:
    """Uma venda acabou de virar Fatura Simplificada: sai o talão do cliente
    NA CAIXA e o pedido NA COZINHA.

    **Dois trabalhos e não um**, porque são dois papéis em duas impressoras
    diferentes — e porque assim a cozinha continua a receber a ficha quando a
    impressora do balcão está sem papel, e vice-versa. Um trabalho só, com os
    dois lá dentro, fazia uma avaria de um lado calar o outro.

    O talão do cliente vai **tal e qual veio do Vendus**: são bytes ESC/POS
    certificados, guardados com a fatura (`fiscal._gravar_documento`), e não
    se lhes acrescenta nem se lhes tira nada. O pedido da cozinha é que é
    nosso, e o texto dele já estava escrito e testado há muito
    (`talao.pedido_da_cozinha`).

    Chamado de dentro do `finalizar` e nunca levanta nada — as duas chamadas
    passam por `enfileirar`, que engole tudo."""
    talao = documento.get("talao_escpos")
    if isinstance(talao, str):
        # Um documento relido do Mongo pode trazer o talão como texto (foi
        # gravado assim por uma versão anterior). Aceita-se, mas nunca se
        # adivinha a codificação: latin-1 é a única que nunca falha byte
        # nenhum e devolve exactamente os 256 valores originais.
        talao = talao.encode("latin-1", errors="ignore")
    await enfileirar(
        db,
        loja_id=venda["loja_id"],
        dispositivo_id=venda.get("dispositivo_id"),
        impressora=CAIXA,
        tipo=TALAO,
        dados=talao or b"",
        # O DOCUMENTO, não a venda: é o documento que é o papel. Uma retoma
        # que grave o mesmo documento outra vez cai na mesma chave e não
        # duplica nada.
        chave="talao:%s" % documento.get("id"),
    )
    await enfileirar(
        db,
        loja_id=venda["loja_id"],
        dispositivo_id=venda.get("dispositivo_id"),
        impressora=COZINHA,
        tipo=PEDIDO,
        dados=escpos.documento(pedido_da_cozinha(venda)),
        chave="pedido:%s" % venda["id"],
    )


async def enfileirar_z(db, z: Dict, dispositivo_id: Optional[str] = None) -> None:
    """A caixa fechou: sai o Z na impressora do balcão.

    Chamado DEPOIS de o Z estar escrito na sessão, nunca antes — um Z em
    papel que não corresponda ao Z gravado é a pior espécie de papel que esta
    loja pode produzir."""
    await enfileirar(
        db,
        loja_id=z.get("loja_id"),
        dispositivo_id=dispositivo_id,
        impressora=CAIXA,
        tipo=Z,
        dados=escpos.documento(relatorio_z(z)),
        # Um fecho, um Z. Uma retoma de um fecho que morreu a meio não faz
        # sair um segundo papel.
        chave="z:%s" % z.get("id"),
    )


# --- A fila, vista do lado do programa da loja --------------------------------


async def _arrumar_a_fila(db, loja_id: str, agora: datetime) -> None:
    """Antes de entregar seja o que for: devolve à fila o que ficou por
    confirmar, desiste do que já foi entregue vezes de mais, e deita fora o
    que passou a validade.

    Corre AQUI e não num processo em segundo plano de propósito: sem ninguém
    a perguntar por trabalho não há impressão nenhuma a acontecer, por isso
    também não há nada que precise de ser arrumado com pressa. Um cron a
    mais é um cron a falhar em silêncio.

    Cada arrumação é uma escrita CONDICIONADA ao que se leu — o
    `matched_count` decide, como no resto do módulo. Duas voltas da fila em
    paralelo (dois programas ligados por engano) não arrumam o mesmo trabalho
    duas vezes, e nenhuma delas pisa um trabalho que entretanto mudou de
    estado debaixo dela."""
    coleccao = db[COLECOES["trabalhos_impressao"]]
    vivos = await coleccao.find(
        {"loja_id": loja_id, "estado": {"$in": [PENDENTE, RESERVADO]}}
    ).to_list(1000)

    for trabalho in vivos:
        if trabalho.get("estado") == RESERVADO:
            reservado_em = _quando(trabalho.get("reservado_em"))
            # Sem instante legível não se consegue dizer se o arrendamento
            # acabou. Trata-se como ACABADO — a alternativa era um trabalho
            # preso para sempre, e este módulo escolheu papel a mais em vez
            # de papel a menos.
            if reservado_em is not None and (
                agora - reservado_em
            ).total_seconds() < _ARRENDAMENTO_SEGUNDOS:
                continue
            tentativas = trabalho.get("tentativas") or 0
            if tentativas >= _MAX_TENTATIVAS:
                novo = {
                    "estado": FALHADO,
                    "terminado_em": _iso(agora),
                    "erro": _MSG_DESISTIU % tentativas,
                }
            else:
                novo = {
                    "estado": PENDENTE,
                    "recibo": None,
                    "reservado_em": None,
                    "reservado_por": None,
                }
            await coleccao.update_one(
                # O `recibo` na condição, e não só o estado: é ele que
                # identifica ESTA entrega. Sem ele, uma volta lenta da fila
                # devolvia à fila um trabalho que já tinha sido entregue de
                # novo a outro programa entretanto — e os dois imprimiam.
                {"id": trabalho["id"], "estado": RESERVADO,
                 "recibo": trabalho.get("recibo")},
                {"$set": novo},
            )
            continue

        validade = _quando(trabalho.get("validade_ate"))
        # Sem validade legível NÃO caduca: um trabalho gravado por uma versão
        # que não escrevia este campo é papel que alguém está à espera, e
        # deitá-lo fora por não se perceber a data era escolher exactamente o
        # estrago que este módulo recusa.
        if validade is not None and validade < agora:
            await coleccao.update_one(
                {"id": trabalho["id"], "estado": PENDENTE},
                {"$set": {"estado": CADUCADO, "terminado_em": _iso(agora),
                          "erro": _MSG_CADUCOU}},
            )


@router.post("/pos/impressao/recolher")
async def recolher(dispositivo: Dict = Depends(dispositivo_atual)) -> dict:
    """O programa da loja pergunta se há trabalho. É esta rota, e só esta,
    que faz o papel sair.

    **A entrega é por LOJA**, não pelo PC que pediu a impressão. É a
    realidade do hardware, dita pelo dono: «UM PC por loja, Windows. Todos.»
    — e a impressora da cozinha está instalada nesse mesmo PC. Entregar por
    dispositivo partia-se em dois sítios que não se veriam a tempo: o Z pode
    ser fechado de um PC que não é o que tem o programa instalado, e um
    talão pedido do tablet do gestor não teria programa nenhum a quem ser
    entregue. Por loja, tudo o que aquela loja precisa de imprimir sai
    naquela loja.

    A ordem é a de CHEGADA (`criado_em`), sempre. A operadora que fez três
    contas seguidas vê os três pedidos sair pela ordem em que os fez, que é a
    ordem por que a cozinha os vai fazer.

    **Cada entrega é uma escrita condicionada ao que se leu**, e é o
    `matched_count` que decide — a disciplina de sempre deste módulo. A
    condição inclui as `tentativas`: é uma comparação-e-troca completa, e é
    ela que garante que a contagem não se perde numa corrida (uma contagem
    perdida é o limite das tentativas a deixar de existir, e o limite é o
    que impede os duzentos talões de madrugada).
    """
    db = obter_db()
    loja_id = dispositivo["loja_id"]
    agora = _agora()
    await _arrumar_a_fila(db, loja_id, agora)

    coleccao = db[COLECOES["trabalhos_impressao"]]
    candidatos = await coleccao.find(
        {"loja_id": loja_id, "estado": PENDENTE}
    ).sort("criado_em", 1).to_list(_QUANTOS_DE_CADA_VEZ)

    entregues: List[Dict] = []
    for trabalho in candidatos:
        recibo = str(uuid.uuid4())
        tentativas = trabalho.get("tentativas") or 0
        resultado = await coleccao.update_one(
            {"id": trabalho["id"], "estado": PENDENTE, "tentativas": tentativas},
            {"$set": {
                "estado": RESERVADO,
                "recibo": recibo,
                "reservado_em": _iso(agora),
                "reservado_por": dispositivo.get("id"),
                "tentativas": tentativas + 1,
            }},
        )
        if resultado.matched_count != 1:
            # Outro programa levou-o entretanto. Não é erro: é a corrida a
            # ser decidida onde tem de ser.
            continue
        entregues.append({
            "id": trabalho["id"],
            # O RECIBO é o que prova, depois, que quem confirma é quem
            # recebeu. Sem ele, um `impresso` atrasado de uma entrega
            # anterior dava por impresso um trabalho que outro programa tem
            # neste momento nas mãos.
            "recibo": recibo,
            "impressora": trabalho.get("impressora"),
            "tipo": trabalho.get("tipo"),
            "bytes_b64": trabalho.get("bytes_b64"),
        })

    # A marca de que ESTA loja tem um programa de impressão vivo. É ela — e
    # não a `ultima_atividade_em`, que qualquer browser do POS também
    # actualiza — que responde à pergunta «há alguém a ouvir?» em
    # `GET /pos/impressao/estado`. Confundir as duas fazia o ecrã dizer que
    # havia programa numa loja onde só há o browser aberto.
    await db[COLECOES["dispositivos"]].update_one(
        {"id": dispositivo.get("id")},
        {"$set": {"ultima_recolha_em": _iso(agora)}},
    )
    return {"trabalhos": entregues}


class PedidoRecibo(BaseModel):
    recibo: str = Field(min_length=1)


class PedidoFalhou(PedidoRecibo):
    erro: str = Field(default="", max_length=500)


async def _trabalho_da_loja(db, trabalho_id: str, loja_id: str) -> Dict:
    trabalho = await db[COLECOES["trabalhos_impressao"]].find_one(
        {"id": trabalho_id, "loja_id": loja_id}
    )
    if not trabalho:
        raise HTTPException(status_code=404, detail=_MSG_TRABALHO_INEXISTENTE)
    return trabalho


@router.post("/pos/impressao/trabalhos/{trabalho_id}/impresso")
async def marcar_impresso(
    trabalho_id: str, dados: PedidoRecibo, dispositivo: Dict = Depends(dispositivo_atual)
) -> dict:
    """O programa diz que o papel saiu.

    Condicionada ao `recibo` DESTA entrega: quem confirma tem de ser quem
    recebeu. Uma confirmação que chegue tarde — depois de o arrendamento ter
    expirado e o trabalho ter voltado à fila — não casa, e responde-se-lhe
    com a verdade (409) em vez de a aceitar em silêncio. O programa lê isso e
    segue; o trabalho é de outro agora."""
    db = obter_db()
    await _trabalho_da_loja(db, trabalho_id, dispositivo["loja_id"])
    resultado = await db[COLECOES["trabalhos_impressao"]].update_one(
        {"id": trabalho_id, "estado": RESERVADO, "recibo": dados.recibo},
        {"$set": {"estado": IMPRESSO, "terminado_em": _iso(_agora()), "recibo": None}},
    )
    if resultado.matched_count != 1:
        raise HTTPException(status_code=409, detail=_MSG_RECIBO_INVALIDO)
    return {"registado": True}


@router.post("/pos/impressao/trabalhos/{trabalho_id}/falhou")
async def marcar_falhou(
    trabalho_id: str, dados: PedidoFalhou, dispositivo: Dict = Depends(dispositivo_atual)
) -> dict:
    """O programa diz que não conseguiu imprimir.

    **Isto NÃO é prova de que não saiu papel**, e é importante não fingir que
    é. O caminho até à impressora tem três passos (`StartDocPrinter`,
    `WritePrinter`, `EndDocPrinter`) e uma falha no último acontece com os
    bytes já entregues ao spooler do Windows: pode ter saído meio talão, pode
    ter saído inteiro. Por isso o trabalho **volta à fila** — a mesma escolha
    de sempre, papel a mais em vez de papel a menos — e conta como mais uma
    tentativa, para o limite continuar a valer.

    O que isto dá, e é a razão de existir em vez de se deixar o arrendamento
    expirar: o trabalho volta à fila NO INSTANTE em que falha, e não daqui a
    um minuto. Numa impressora que ficou sem papel e a que alguém acabou de
    pôr um rolo, é a diferença entre o talão sair já e o cliente ficar à
    espera."""
    db = obter_db()
    trabalho = await _trabalho_da_loja(db, trabalho_id, dispositivo["loja_id"])
    tentativas = trabalho.get("tentativas") or 0
    agora = _agora()
    erro = (dados.erro or "").strip() or "O programa de impressão não disse porquê."
    if tentativas >= _MAX_TENTATIVAS:
        novo = {"estado": FALHADO, "terminado_em": _iso(agora), "erro": erro,
                "recibo": None}
    else:
        novo = {"estado": PENDENTE, "recibo": None, "reservado_em": None,
                "reservado_por": None, "erro": erro}
    resultado = await db[COLECOES["trabalhos_impressao"]].update_one(
        {"id": trabalho_id, "estado": RESERVADO, "recibo": dados.recibo},
        {"$set": novo},
    )
    if resultado.matched_count != 1:
        raise HTTPException(status_code=409, detail=_MSG_RECIBO_INVALIDO)
    logger.warning(
        "[faturacao] impressão %s da loja %s falhou (%d/%d): %s",
        trabalho.get("tipo"), trabalho.get("loja_id"), tentativas,
        _MAX_TENTATIVAS, erro,
    )
    return {"registado": True, "estado": novo["estado"]}


# --- A fila, vista do lado do ecrã do POS -------------------------------------


def _ha_programa_a_ouvir(dispositivos: List[Dict], agora: datetime) -> Optional[str]:
    """O instante da última recolha de ALGUM programa desta loja, se for
    recente. `None` quer dizer que não há nenhum a ouvir.

    Pura de propósito: é a decisão que o ecrã do POS usa para desligar os
    botões de impressão, e uma decisão que só exista dentro de uma rota não
    se consegue prender a um teste sem montar meio servidor."""
    melhor = None
    for dispositivo in dispositivos:
        recolha = _quando(dispositivo.get("ultima_recolha_em"))
        if recolha is None:
            continue
        if (agora - recolha).total_seconds() > _AGENTE_VIVO_SEGUNDOS:
            continue
        if melhor is None or recolha > melhor:
            melhor = recolha
    return _iso(melhor) if melhor is not None else None


@router.get("/pos/impressao/estado")
async def estado_da_impressao(operador: Dict = Depends(operador_atual)) -> dict:
    """O que o ecrã do POS precisa de saber: **há programa a ouvir?**, e o que
    é que está por sair ou ficou por sair.

    Existe por uma razão só, e é a mais importante deste ficheiro do lado do
    balcão: **uma loja onde ninguém instalou o programa não pode ter um botão
    que parece funcionar.** Sem esta pergunta, o «Imprimir» ficava bonito, o
    trabalho entrava na fila, caducava trinta minutos depois e ninguém sabia
    de nada — a operadora dava o cliente por servido e o papel nunca existiu.
    """
    db = obter_db()
    loja_id = operador["loja_id"]
    agora = _agora()

    dispositivos = await db[COLECOES["dispositivos"]].find(
        {"loja_id": loja_id, "estado": "activo"}
    ).to_list(100)
    ultima_recolha = _ha_programa_a_ouvir(dispositivos, agora)

    trabalhos = await db[COLECOES["trabalhos_impressao"]].find(
        {"loja_id": loja_id, "estado": {"$in": [PENDENTE, RESERVADO, FALHADO]}}
    ).to_list(1000)
    # Os PENDENTES contam-se só enquanto valem: um trabalho que já passou a
    # validade vai ser deitado fora na próxima volta da fila, e mostrá-lo
    # como "à espera" era prometer um papel que não vai sair.
    por_sair = sum(
        1 for t in trabalhos
        if t.get("estado") in (PENDENTE, RESERVADO)
        and (_quando(t.get("validade_ate")) or agora) >= agora
    )
    return {
        "ha_programa": ultima_recolha is not None,
        "ultima_recolha_em": ultima_recolha,
        "por_sair": por_sair,
        "falhados": sum(1 for t in trabalhos if t.get("estado") == FALHADO),
    }


class PedidoPaginaDeTeste(BaseModel):
    impressora: str = Field(default=CAIXA)


@router.post("/pos/impressao/pagina-de-teste")
async def pagina_de_teste(
    dados: PedidoPaginaDeTeste, dispositivo: Dict = Depends(dispositivo_atual)
) -> dict:
    """Os bytes da página de teste, para o programa da loja os mandar
    DIRECTAMENTE à impressora — sem passar pela fila.

    **É o único teste que existe para a metade Windows deste sistema**, e é
    por isso que não passa pela fila: a fila prova que o servidor sabe o que
    tem a imprimir, e o que esta página tem de provar é o ÚLTIMO salto — que
    estes bytes entram naquela impressora em cru, e não desenhados. Se saísse
    da fila e não aparecesse papel, ficavam três suspeitos em vez de um.

    **Os bytes vêm daqui e não do programa da loja** para não haver duas
    cópias do ESC/POS. Os dois números que se afinam quando uma impressora
    discorda (`escpos._CORTAR` e `escpos._TABELA_DE_CARACTERES`) vivem numa
    constante só, e uma cópia dentro do `.exe` fazia com que afinar um deles
    corrigisse os talões e não a página que os devia diagnosticar — ou o
    contrário, que é pior.

    Só precisa do DISPOSITIVO: quem carrega neste botão está à frente do PC
    da loja, no programa de impressão, e ali não há operador nenhum com PIN
    dado. É a mesma autorização que a recolha usa.
    """
    impressora = dados.impressora if dados.impressora in _IMPRESSORAS else CAIXA
    db = obter_db()
    loja = await db[COLECOES["lojas"]].find_one({"id": dispositivo["loja_id"]})
    bytes_da_pagina = escpos.pagina_de_teste(
        impressora,
        loja=(loja or {}).get("nome") or dispositivo["loja_id"],
    )
    return {"bytes_b64": base64.b64encode(bytes_da_pagina).decode("ascii")}


@router.post("/pos/impressao/gaveta")
async def abrir_gaveta(operador: Dict = Depends(operador_atual)) -> dict:
    """«Abrir Gaveta», do menu Caixa.

    A gaveta abre PELA IMPRESSORA — é um impulso ESC/POS pelo cabo da
    gaveta, não um aparelho à parte (é assim que está montado nas lojas). Por
    isso isto é um trabalho de impressão como os outros, e passa pela mesma
    fila: se não houver programa a ouvir, o ecrã já o disse antes do toque.

    **Chave nova de cada vez, de propósito.** Aqui a repetição é o que a
    pessoa quer: dois toques no botão são dois pedidos de abrir a gaveta.
    E são dois minutos de validade, não trinta — ver a docstring do módulo."""
    db = obter_db()
    trabalho_id = await enfileirar(
        db,
        loja_id=operador["loja_id"],
        dispositivo_id=operador.get("dispositivo_id"),
        impressora=CAIXA,
        tipo=GAVETA,
        dados=escpos.abrir_gaveta(),
        chave="gaveta:%s" % uuid.uuid4(),
    )
    return {"trabalho_id": trabalho_id, "aceite": trabalho_id is not None}


@router.post("/pos/venda/{venda_id}/imprimir-pedido")
async def imprimir_pedido(
    venda_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """«Imprimir Pedido», no ecrã da venda — a ficha da cozinha ANTES de a
    conta ser finalizada.

    É o que a operadora usa quando o cliente pede para começarem a fazer o
    copo enquanto ele decide o resto, e é o que faz a cozinha não depender de
    a conta estar fechada.

    Não valida o estado da conta e não é engano: um pedido já emitido também
    se reimprime (a ficha caiu, molhou-se, a cozinha perdeu-a), e uma conta
    cancelada simplesmente não é pedida. O que este botão faz é papel — nada
    aqui toca em dinheiro nem em documento fiscal nenhum.

    **Chave nova de cada vez**, como a gaveta: quem carrega duas vezes quer
    duas fichas."""
    db = obter_db()
    venda = await db[COLECOES["vendas"]].find_one(
        {"id": venda_id, "loja_id": operador["loja_id"]}
    )
    if not venda:
        raise HTTPException(status_code=404, detail=_MSG_VENDA_INEXISTENTE)
    trabalho_id = await enfileirar(
        db,
        loja_id=venda["loja_id"],
        dispositivo_id=operador.get("dispositivo_id"),
        impressora=COZINHA,
        tipo=PEDIDO,
        dados=escpos.documento(pedido_da_cozinha(venda)),
        chave="pedido-mao:%s" % uuid.uuid4(),
    )
    return {"trabalho_id": trabalho_id, "aceite": trabalho_id is not None}


@router.post("/pos/documentos/{documento_id}/imprimir")
async def imprimir_segunda_via(
    documento_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """«Imprimir», dentro de uma fatura do separador Faturação — a segunda
    via do talão do cliente.

    **Não volta ao Vendus.** Os bytes são os do talão certificado que ficou
    guardado com a fatura (`fat_documentos.talao_escpos`): é o MESMO papel
    que saiu da primeira vez, byte a byte, com o mesmo ATCUD e o mesmo QR. Ir
    outra vez ao Vendus era uma chamada de rede por cada reimpressão, e uma
    reimpressão que falhasse porque a internet da loja está em baixo — quando
    o papel já estava cá dentro.

    Uma fatura antiga, emitida antes de o talão passar a ser guardado, não
    tem papel para dar daqui: diz-se isso por extenso (o documento fiscal
    continua bom) em vez de se enfileirar uma folha em branco."""
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one(
        {"id": documento_id, "loja_id": operador["loja_id"]}
    )
    if not documento:
        raise HTTPException(status_code=404, detail=_MSG_DOCUMENTO_INEXISTENTE)
    talao = documento.get("talao_escpos")
    if isinstance(talao, str):
        talao = talao.encode("latin-1", errors="ignore")
    if not talao:
        raise HTTPException(status_code=422, detail=_MSG_DOCUMENTO_SEM_TALAO)
    trabalho_id = await enfileirar(
        db,
        loja_id=documento["loja_id"],
        dispositivo_id=operador.get("dispositivo_id"),
        impressora=CAIXA,
        tipo=SEGUNDA_VIA,
        dados=bytes(talao),
        chave="segunda-via:%s" % uuid.uuid4(),
    )
    return {"trabalho_id": trabalho_id, "aceite": trabalho_id is not None}
