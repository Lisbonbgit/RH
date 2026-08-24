"""Autenticação do POS — separada da autenticação de gestão (auth.py).

Duas peças, duas vidas diferentes (spec §7.1):
- Token de DISPOSITIVO: o PC da loja é autorizado uma vez, no backoffice —
  o gestor gera um código de emparelhamento de uso único
  (`gerar_codigo_emparelhamento`, exige `gestor_atual`) e o próprio POS
  troca-o por um token de dispositivo (`emparelhar`, sem Depends — é o
  bootstrap da cadeia, o dispositivo ainda não tem nenhum token nesse
  momento). O token fica em localStorage no browser da loja e vai no
  cabeçalho X-Device-Token em cada pedido seguinte (`dispositivo_atual`).
- Token de OPERADOR: sai da entrada por PIN (`entrar`, exige
  `dispositivo_atual`) e dura o turno. É o que identifica quem fez cada
  venda. Vai no cabeçalho X-Operator-Token (`operador_atual`), NUNCA no
  Authorization — esse cabeçalho é do JWT de gestão (auth.py).

Nenhum dos dois mecanismos usa `descodificar_token` nem o `JWT_SECRET` de
gestão: o token de operador é assinado com `POS_JWT_SECRET`, uma chave
própria, para que um JWT de gestão nunca seja aceite aqui — nem por
coincidência de segredo. Um administrador com sessão aberta no backoffice
não pode, por isso, vender sem se identificar com o PIN: senão a venda
entrava na caixa sem dono e o fecho deixava de responsabilizar ninguém.

Regra 2 da spec (§7.1), aplicada em `entrar`: a unicidade do PIN não é
garantida por índice (bcrypt tem sal — ver faturacao/pins.py e
faturacao/db.py). A verificação no servidor, em utilizadores.py, cobre criar
e mudar PIN, mas não cobre alguém ser movido de loja ou reactivado. Por
isso a entrada busca TODOS os operadores activos cujo âmbito de loja inclui
a loja do dispositivo, verifica um a um, e:
- 0 correspondências → 401 genérico (não diz se o PIN existe nalgum lado)
- 1 correspondência → emite o token de operador
- 2+ correspondências → 409 explícito, NUNCA escolhe a primeira — escolher
  a primeira atribuiria as vendas à pessoa errada e destruía a
  responsabilização do fecho de caixa.

bcrypt custa ~166ms e é síncrono. A entrada compara o PIN contra todos os
operadores activos da loja — com 20 pessoas seriam ~3,3s a bloquear o event
loop do portal INTEIRO (RH, Financeiro, picagem de ponto incluídos). Por
isso cada verificação corre em `asyncio.to_thread`, nunca directamente no
loop.
"""
import hashlib
import os
import secrets
import uuid
from asyncio import to_thread
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pins import pin_valido

router = APIRouter()

# Segredo próprio dos tokens de operador — deliberadamente DIFERENTE do
# JWT_SECRET de gestão (auth.py). Não é só para não colidir por acaso: é a
# garantia de que um JWT de gestão nunca decodifica aqui, mesmo que alguém
# tente usá-lo num cabeçalho X-Operator-Token.
#
# SEM valor por omissão — nunca. C4 (a revisão do núcleo fiscal): a versão
# anterior tinha `os.environ.get("POS_JWT_SECRET", "faturacao-pos-secret-
# key-2026")`, uma string gravada no próprio repositório. Não estava no
# .env.example nem em nenhum script de deploy — se ninguém a definisse no
# servidor, e nada avisava disso, qualquer pessoa com o código forjava um
# token de operador válido para QUALQUER loja e QUALQUER operador, e emitia
# Faturas Simplificadas reais em nome de uma funcionária. Ver
# `_segredo_operador_configurado`: as rotas do POS que dependem disto
# recusam-se a servir em vez de cair num valor previsível.
POS_JWT_SECRET = os.environ.get("POS_JWT_SECRET")
_ALGORITMO = "HS256"
_TIPO_TOKEN_OPERADOR = "operador_pos"
_TTL_OPERADOR_HORAS = 12
_TTL_CODIGO_MINUTOS = 15

_MSG_PIN_INCORRECTO = "PIN incorrecto."
_MSG_CODIGO_INVALIDO = "Código de emparelhamento inválido ou expirado."
_MSG_DISPOSITIVO_INVALIDO = "Dispositivo não emparelhado."
_MSG_SESSAO_OPERADOR_INVALIDA = "Sessão de operador inválida ou expirada."
_MSG_DISPOSITIVO_NAO_ENCONTRADO = "Dispositivo não encontrado ou já revogado."
_MSG_SEGREDO_OPERADOR_EM_FALTA = (
    "POS_JWT_SECRET não está configurado no servidor — as rotas do POS que "
    "dependem da identidade do operador estão desactivadas por segurança. "
    "Defina POS_JWT_SECRET no ambiente (.env) antes de usar o POS."
)


def _segredo_operador_configurado() -> str:
    """Devolve o POS_JWT_SECRET, ou recusa o pedido com uma mensagem clara
    (503) se não estiver definido — nunca um valor por omissão (ver C4 na
    docstring do módulo, acima de POS_JWT_SECRET)."""
    if not POS_JWT_SECRET:
        raise HTTPException(status_code=503, detail=_MSG_SEGREDO_OPERADOR_EM_FALTA)
    return POS_JWT_SECRET


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(valor: str) -> str:
    # sha256 chega aqui: o código/token já tem entropia própria (uso único
    # com expiração curta, ou 256 bits de secrets.token_urlsafe) — ao
    # contrário do PIN de 4 dígitos (10 000 combinações), não há o problema
    # de espaço de procura pequeno que obriga o bcrypt.
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


class PedidoCodigo(BaseModel):
    loja_id: str
    # Opcional (Task 5, spec do buraco achado na Task 2): o nome que o gestor
    # dá a este PC ao gerar o código (ex.: "PC Balcão", "PC Drive-Thru") — é o
    # que distingue os dispositivos na listagem, quando uma loja tem mais do
    # que um. Sem nome, listar_dispositivos mostra apenas o id.
    nome: Optional[str] = Field(default=None, max_length=60)


class PedidoEmparelhar(BaseModel):
    codigo: str = Field(min_length=1)


class PedidoEntrar(BaseModel):
    # A cara em que se tocou na grelha (spec §7.1). OBRIGATÓRIO — ver a
    # docstring de `entrar`: sem este campo, a entrada era só pelo PIN.
    operador_id: str = Field(min_length=1)
    pin: str


@router.post("/dispositivos-pos", status_code=201)
async def gerar_codigo_emparelhamento(dados: PedidoCodigo, _: dict = Depends(gestor_atual)) -> dict:
    """Rota de gestão (exige gestor_atual): gera um código de emparelhamento
    de uso único para uma loja. O gestor lê este código ao PC da loja, que o
    troca por um token de dispositivo em POST /pos/emparelhar."""
    db = obter_db()
    if not await db[COLECOES["lojas"]].find_one({"id": dados.loja_id}):
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    codigo = secrets.token_hex(4).upper()
    doc = {
        "id": str(uuid.uuid4()),
        "loja_id": dados.loja_id,
        "nome": dados.nome,
        "codigo_hash": _hash_token(codigo),
        "estado": "pendente",
        "criado_em": _agora().isoformat(),
        "expira_em": (_agora() + timedelta(minutes=_TTL_CODIGO_MINUTOS)).isoformat(),
    }
    await db[COLECOES["dispositivos"]].insert_one(dict(doc))
    return {"codigo": codigo, "expira_em": doc["expira_em"]}


def _expirou(valor) -> bool:
    """Um `expira_em` que não se consiga ler conta como EXPIRADO.

    Sem isto, uma data gravada mal responde **500** ao passo 5 do manual de
    instalação — e uma data SEM FUSO percebe-se (o `fromisoformat` aceita-a)
    mas rebenta na comparação, que é a forma mais silenciosa de falhar.

    A direcção é a contrária à da fila de impressão (`impressao._quando`, onde
    ilegível NÃO deita papel fora): um código cuja validade não se percebe não
    pode ser trocado por um token deste PC."""
    try:
        quando = datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return True
    return quando.tzinfo is None or quando < _agora()


@router.post("/pos/emparelhar")
async def emparelhar(dados: PedidoEmparelhar) -> dict:
    """Troca um código de emparelhamento válido por um token de dispositivo.

    Sem Depends de propósito: é o próprio bootstrap da cadeia de
    autenticação do POS — o dispositivo ainda não tem nenhum token neste
    momento. A guarda aqui não é uma dependência do FastAPI, é o código em
    si: de uso único (o estado passa a "activo" e deixa de casar com
    {"estado": "pendente"}), com expiração curta, e comparado por hash
    (nunca em claro). Ver test_protecao_rotas.py para a excepção documentada
    e test_pos_auth.py para os testes desta guarda."""
    db = obter_db()
    codigo_normalizado = dados.codigo.strip().upper()
    disp = await db[COLECOES["dispositivos"]].find_one(
        {"codigo_hash": _hash_token(codigo_normalizado), "estado": "pendente"}
    )
    if not disp or _expirou(disp.get("expira_em")):
        raise HTTPException(status_code=401, detail=_MSG_CODIGO_INVALIDO)

    token = secrets.token_urlsafe(32)
    agora = _agora().isoformat()
    await db[COLECOES["dispositivos"]].update_one(
        {"id": disp["id"]},
        {"$set": {
            "estado": "activo",
            "token_hash": _hash_token(token),
            "emparelhado_em": agora,
            # O próprio emparelhamento já é "falar connosco" — inicializa a
            # marca da Task 5 aqui, para um PC nunca emparelhado (activo mas
            # sem ninguém a usá-lo ainda) já ter uma data e não um vazio
            # ambíguo na listagem.
            "ultima_atividade_em": agora,
        }},
    )
    # loja_nome só para o ecrã mostrar "emparelhado com a Loja X" logo a
    # seguir ao código (spec §7.1) — não é usado para nada de segurança, por
    # isso uma loja entretanto apagada não impede o emparelhamento em si:
    # cai só para None, e o ecrã mostra o id em vez do nome.
    loja = await db[COLECOES["lojas"]].find_one({"id": disp["loja_id"]})
    return {
        "device_token": token,
        "loja_id": disp["loja_id"],
        "loja_nome": loja.get("nome") if loja else None,
    }


@router.get("/dispositivos-pos")
async def listar_dispositivos(_: dict = Depends(gestor_atual)) -> List[dict]:
    """Lista os dispositivos alguma vez emparelhados — activos e revogados.

    Não inclui códigos "pendentes" (gerados e nunca trocados): esses ainda
    não são um dispositivo, só um convite por usar. Task 5 (buraco achado na
    Task 2): sem `ultima_atividade_em`, um PC emparelhado uma vez ficava
    válido para sempre e não havia forma de perceber qual já não existe —
    esta lista é o que permite ao gestor decidir o que revogar.
    """
    db = obter_db()
    todos = await db[COLECOES["dispositivos"]].find({}).to_list(500)
    return [
        {
            "id": d["id"],
            "loja_id": d["loja_id"],
            "nome": d.get("nome"),
            "estado": d["estado"],
            "emparelhado_em": d.get("emparelhado_em"),
            "ultima_atividade_em": d.get("ultima_atividade_em"),
        }
        for d in todos
        if d.get("estado") != "pendente"
    ]


@router.delete("/dispositivos-pos/{dispositivo_id}")
async def revogar_dispositivo(dispositivo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    """Revoga um dispositivo: a partir daqui, `dispositivo_atual` deixa de o
    aceitar (deixa de haver `estado='activo'` a casar), e o /pos desse PC
    deixa de carregar. Mesmo padrão de `emparelhar`: confirma primeiro com
    find_one (também serve para distinguir "nunca existiu" de "já estava
    revogado" — os dois dão 404, mas nenhum finge sucesso)."""
    db = obter_db()
    disp = await db[COLECOES["dispositivos"]].find_one(
        {"id": dispositivo_id, "estado": "activo"}
    )
    if not disp:
        raise HTTPException(status_code=404, detail=_MSG_DISPOSITIVO_NAO_ENCONTRADO)
    await db[COLECOES["dispositivos"]].update_one(
        {"id": dispositivo_id},
        {"$set": {"estado": "revogado", "revogado_em": _agora().isoformat()}},
    )
    return {"revogado": True}


async def dispositivo_atual(x_device_token: Optional[str] = Header(default=None)) -> Dict:
    """Dependência das rotas do POS que só precisam do dispositivo (ainda
    sem operador identificado) — usa-se directamente em /pos/entrar.

    Um dispositivo revogado (Task 5) já não tem estado='activo', por isso
    deixa de casar com o filtro abaixo e cai no mesmo 401 de sempre — é
    assim que "revogar corta o /pos desse PC" acontece, sem precisar de
    nenhuma lógica extra aqui.
    """
    if not x_device_token:
        raise HTTPException(status_code=401, detail=_MSG_DISPOSITIVO_INVALIDO)
    db = obter_db()
    disp = await db[COLECOES["dispositivos"]].find_one(
        {"token_hash": _hash_token(x_device_token), "estado": "activo"}
    )
    if not disp:
        raise HTTPException(status_code=401, detail=_MSG_DISPOSITIVO_INVALIDO)
    # Task 5: regista "a última vez que este PC falou connosco" — é o que
    # distingue, na listagem, o PC ainda em uso do que já foi arrumado numa
    # gaveta. Não bloqueia nem faz o pedido falhar se a escrita não voltar
    # a tempo — é só um sinal para o gestor, não uma condição de entrada.
    await db[COLECOES["dispositivos"]].update_one(
        {"id": disp["id"]}, {"$set": {"ultima_atividade_em": _agora().isoformat()}}
    )
    return disp


def _ambito_bate_com_loja(lojas_do_operador: List[str], loja_id: str) -> bool:
    """Lista vazia = administrador, entra em qualquer loja (mesma convenção
    de utilizadores.py::_sobrepoe_lojas)."""
    return not lojas_do_operador or loja_id in lojas_do_operador


@router.get("/pos/operadores")
async def listar_operadores_do_dispositivo(dispositivo: Dict = Depends(dispositivo_atual)) -> List[dict]:
    """A grelha de caras do ecrã de entrada/tela de descanso (spec §7.1).

    Depende só de dispositivo_atual — nunca de operador_atual: é
    precisamente o ecrã que aparece ANTES de existir qualquer operador
    identificado, por isso não pode exigir um. Usa o MESMO âmbito de loja
    que `entrar` usa para comparar o PIN (`_ambito_bate_com_loja`), para a
    grelha mostrar exactamente quem vai conseguir entrar ali — nem mais
    nem menos.

    Nunca devolve pin_hash nem qualquer outro campo do utilizador. A foto
    vem do colaborador do RH (colecção `employees`, fora do prefixo fat_ —
    é o resto do portal) só quando o utilizador está ligado a um
    employee_id (faturacao/utilizadores.py); sem ligação, o ecrã mostra as
    iniciais do nome numa cor da marca."""
    db = obter_db()
    loja_id = dispositivo["loja_id"]
    activos = await db[COLECOES["utilizadores"]].find({"ativo": True}).to_list(1000)
    candidatos = [u for u in activos if _ambito_bate_com_loja(u.get("lojas") or [], loja_id)]

    employee_ids = sorted({u["employee_id"] for u in candidatos if u.get("employee_id")})
    fotos: Dict[str, Optional[str]] = {}
    if employee_ids:
        colaboradores = await db["employees"].find(
            {"id": {"$in": employee_ids}}, {"_id": 0, "id": 1, "photo": 1}
        ).to_list(len(employee_ids))
        fotos = {c["id"]: c.get("photo") for c in colaboradores}

    return [
        {"id": u["id"], "nome": u.get("nome"), "foto": fotos.get(u.get("employee_id"))}
        for u in candidatos
    ]


@router.post("/pos/entrar")
async def entrar(dados: PedidoEntrar, dispositivo: Dict = Depends(dispositivo_atual)) -> dict:
    # Verificado ANTES de tocar na base de dados ou gastar bcrypt a comparar
    # PINs: sem segredo configurado não há token nenhum para emitir, e é
    # melhor a operadora ver "sistema por configurar" do que "PIN
    # incorrecto" quando na verdade o PIN estava certo.
    _segredo_operador_configurado()
    db = obter_db()
    loja_id = dispositivo["loja_id"]

    # O PIN é verificado contra o utilizador em cuja CARA se tocou, e contra
    # mais nenhum.
    #
    # Antes, esta rota recebia só o PIN e percorria TODOS os utilizadores
    # activos da loja, entrando como aquele a quem o PIN calhasse pertencer.
    # A cara escolhida na grelha nem sequer chegava ao servidor. Tocar na
    # cara da Rafaela e escrever o PIN da Ana entrava como a ANA, sem um
    # aviso — a grelha prometia uma identidade que o servidor deitava fora.
    #
    # Não era cosmético: é o `operador_id` deste token que assina cada venda,
    # cada entrada e saída de dinheiro e o Z do fecho. Quem tocasse na sua
    # própria cara e enganasse um dígito, calhando num PIN válido de outra
    # pessoa, passava o turno a vender em nome dela e a gaveta fechava com o
    # dono errado. Com PINs de 4 dígitos e ~16 pessoas por loja, essa colisão
    # não é hipótese remota — é uma questão de tempo.
    #
    # De caminho, isto arruma duas coisas: já não há "PIN em conflito" para
    # tratar (um pedido compara um hash, nunca vinte, por isso não pode haver
    # duas correspondências), e um PIN adivinhado à sorte deixa de ter ~16
    # hipóteses de casar com ALGUÉM — tem de casar com aquela pessoa.
    operador = await db[COLECOES["utilizadores"]].find_one(
        {"id": dados.operador_id, "ativo": True}
    )
    # Mesma resposta para "não existe", "está inactivo", "é de outra loja" e
    # "PIN errado": um 401 igual em todos os casos. Distingui-los dizia a
    # quem estivesse a tentar exactamente onde continuar a tentar.
    if not operador or not _ambito_bate_com_loja(operador.get("lojas") or [], loja_id):
        raise HTTPException(status_code=401, detail=_MSG_PIN_INCORRECTO)

    # Fora do event loop: ver docstring do módulo — o bcrypt leva ~166ms e,
    # corrido no loop, trava o portal inteiro (RH e Financeiro incluídos).
    if not await to_thread(pin_valido, dados.pin, operador.get("pin_hash")):
        raise HTTPException(status_code=401, detail=_MSG_PIN_INCORRECTO)

    agora = _agora()
    # QUAL o PC — não só qual a loja. O token do operador é a única coisa que
    # o POS envia em cada pedido, por isso é aqui que o dispositivo tem de
    # viajar: sem ele, `GET /pos/venda/aberta` (venda.py) só sabia da sessão
    # de caixa, e numa loja com UMA caixa e dois PCs emparelhados os dois
    # recuperavam a MESMA conta — um cliente pagava o açaí do outro, o dia
    # inteiro. Vem do `dispositivo_atual`, o documento do PC emparelhado,
    # nunca de nada que o cliente escreva no corpo.
    #
    # `.get("id")`, não `["id"]`: um documento de dispositivo sem `id` (dados
    # corrompidos, uma migração a meio) tem de deixar entrar na mesma — cair
    # aqui num 500 fechava a loja à funcionária. Sem id, o token fica no
    # mesmo âmbito dos tokens antigos (ver o filtro em venda.py::venda_aberta).
    payload = {
        "operador_id": operador["id"],
        "nome": operador.get("nome"),
        "perfil": operador.get("perfil"),
        "loja_id": loja_id,
        "dispositivo_id": dispositivo.get("id"),
        "tipo": _TIPO_TOKEN_OPERADOR,
        "iat": int(agora.timestamp()),
        "exp": int((agora + timedelta(hours=_TTL_OPERADOR_HORAS)).timestamp()),
    }
    token = jwt.encode(payload, _segredo_operador_configurado(), algorithm=_ALGORITMO)
    return {
        "operator_token": token,
        "operador": {
            "id": operador["id"],
            "nome": operador.get("nome"),
            "perfil": operador.get("perfil"),
        },
    }


async def operador_atual(x_operator_token: Optional[str] = Header(default=None)) -> Dict:
    """Dependência das rotas do POS que precisam de saber quem está a
    vender (abrir/fechar caixa, vender — Tasks seguintes do Plano 2A)."""
    if not x_operator_token:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    segredo = _segredo_operador_configurado()
    try:
        payload = jwt.decode(x_operator_token, segredo, algorithms=[_ALGORITMO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    if payload.get("tipo") != _TIPO_TOKEN_OPERADOR:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    return payload
