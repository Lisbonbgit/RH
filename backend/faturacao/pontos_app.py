"""**Os pontos L'Açaí dados na caixa** — o POS a falar com a app.

A regra do dono: ganha os pontos quem mostra a app na caixa ANTES de pagar. O
talão deixa de ser um bilhete ao portador, porque o que dá pontos já não é o
QR fiscal impresso — é o QR da app, lido pela funcionária e preso a UMA venda.

Três peças, e uma regra acima das três: **nada daqui pode impedir uma fatura
de sair nem atrasar o EMITIR.**

1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome. Não grava nada na venda: é o ecrã que
   guarda a ligação e a manda no finalizar (`fiscal.PedidoFinalizarVenda`).
2. **A fila** (`fat_pontos_app`) — uma linha por crédito (FS) e por estorno
   (NC), com chave única. Nasce DEPOIS de o documento existir e nunca antes:
   os pontos só entram com a fatura já entregue à AT.
3. **O envio** — reserva a linha, fala com a app (4 s) e grava o desfecho. O
   que for técnico (rede, 5xx, chave errada) volta a tentar-se com espera
   crescente; o que for de negócio (`recusado`) não se repete.

A app é idempotente por ATCUD e por nota de crédito, e é isso que deixa este
lado ser simples: um reenvio nunca credita duas vezes.
"""
import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import CODIGO_NAO_SUJEITO
from .venda import _garante_aberta, _obter_venda_da_loja

logger = logging.getLogger(__name__)

router = APIRouter()

# 4 segundos, como o desconto de stock (`estoque_cliente.TIMEOUT_SAIDA_SEGUNDOS`)
# e pela mesma razão: quem espera pelo Ler é a funcionária com o cliente à
# frente. Uma app em baixo diz-se depressa, e a fatura segue sem pontos.
TIMEOUT_SEGUNDOS = 4.0

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte
# normal do httpx.
_transporte = None

_MSG_QR_INVALIDO = "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."
_MSG_APP_INDISPONIVEL = (
    "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."
)


class IntegracaoNaoConfigurada(Exception):
    """Falta `APP_LACAI_URL` ou `APP_LACAI_CHAVE`. Não é uma avaria — é uma
    instalação por acabar."""


async def _chamar_app(acao: str, corpo: Dict) -> httpx.Response:
    """`POST {APP_LACAI_URL}/api/pos-integracao/{acao}` com a chave de serviço.

    As duas variáveis lêem-se a CADA chamada e não à importação (o molde é
    `estoque_cliente.chave_de_servico`): o `.env` pode ganhá-las sem o portal
    reiniciar, e uma constante de módulo congelava o «não configurado».

    A chave vai no CABEÇALHO e nunca no URL: um `?key=` fica escrito nos
    registos de quem estiver pelo meio."""
    url = (os.environ.get("APP_LACAI_URL") or "").strip().rstrip("/")
    chave = (os.environ.get("APP_LACAI_CHAVE") or "").strip()
    if not url or not chave:
        raise IntegracaoNaoConfigurada("integração não configurada")
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS, transport=_transporte) as http:
        return await http.post(
            "%s/api/pos-integracao/%s" % (url, acao),
            json=corpo,
            headers={"X-Service-Key": chave},
        )


def _json_ou_nada(resposta: httpx.Response):
    try:
        return resposta.json()
    except ValueError:
        return None


# --- Ler o QR -----------------------------------------------------------------


class PedidoLerQr(BaseModel):
    venda_id: str = Field(min_length=1, max_length=100)
    # O código vai CRU: quem o normaliza (espaços, maiúsculas) é a app, que é
    # quem conhece o formato. Aqui só se trava o tamanho — um leitor avariado
    # não manda um livro à app.
    codigo: str = Field(min_length=1, max_length=200)


@router.post("/pos/pontos/ler")
async def ler_qr_de_pontos(
    dados: PedidoLerQr, operador: Dict = Depends(operador_atual)
) -> dict:
    """Troca o QR que o cliente mostra por uma ligação na app.

    **A venda confere-se ANTES de falar com a app**, e a ordem não é gosto: a
    app consome o token do QR na primeira leitura. Perguntar-lhe primeiro e
    recusar depois (venda de outra loja, já emitida) gastava o QR do cliente
    para nada, e ele tinha de o abrir outra vez. As recusas são as das outras
    rotas de venda (`venda.py`): 404 «Venda não encontrada.» para uma venda que
    não existe OU é de outra loja, 409 para uma que já não está aberta (a
    frase própria da conta dividida, `_MSG_VENDA_SEPARADA`, ou a genérica).

    **Não grava nada na venda.** A ligação volta ao ecrã, que a guarda presa ao
    id da conta e a manda no finalizar. Uma leitura que não acabe em fatura
    não deixa lixo em lado nenhum deste servidor.

    A loja e o operador vão pelo NOME e saem do TOKEN, nunca do corpo: são o
    registo de quem associou que conta a que venda, para o relatório de
    concentração da 2.ª fase."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, dados.venda_id, operador["loja_id"])
    _garante_aberta(venda)
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": operador["loja_id"]}, {"_id": 0, "nome": 1})
    try:
        resposta = await _chamar_app("ligar", {
            "codigo": dados.codigo,
            "loja_nome": (loja or {}).get("nome") or "",
            "operador_nome": operador.get("nome") or "",
        })
    except (IntegracaoNaoConfigurada, httpx.HTTPError) as e:
        logger.warning(
            "[faturacao] ler QR de pontos (venda %s): a app não respondeu — %s: %s",
            dados.venda_id, type(e).__name__, e)
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    # **Só é «QR inválido» o 404 que o contrato descreve** — o da app, que traz
    # sempre `{"estado": "recusado", "motivo": "qr_invalido"}`. Um 404 do
    # FastAPI da app (`{"detail": "Not Found"}`, a rota por deployar) ou de um
    # proxy pelo meio (404 em HTML) é a app a não estar lá, e a frase certa é a
    # do 503: traduzido para «peça outro QR», a funcionária pedia ao cliente um
    # código novo vezes sem conta e nenhum ia funcionar.
    corpo_do_404 = _json_ou_nada(resposta) if resposta.status_code == 404 else None
    if isinstance(corpo_do_404, dict) and corpo_do_404.get("motivo") == "qr_invalido":
        raise HTTPException(status_code=404, detail=_MSG_QR_INVALIDO)
    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    if not isinstance(corpo, dict) or not corpo.get("ligacao_id"):
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: para a
        # funcionária é tudo «a app não está a responder»; o pormenor fica no log.
        logger.error(
            "[faturacao] ler QR de pontos (venda %s): resposta inesperada da app "
            "(HTTP %s): %s", dados.venda_id, resposta.status_code, resposta.text[:200])
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    return {
        "ligacao_id": str(corpo["ligacao_id"]),
        "primeiro_nome": str(corpo.get("primeiro_nome") or ""),
    }


# --- A fila -------------------------------------------------------------------

# **O «nunca» de `a_enviar_ate`, e não `None`.** No Mongo, `null` não casa com
# `$lt` de uma string — os operadores de comparação só comparam dentro do mesmo
# tipo. Uma linha nascida com `a_enviar_ate: None` nunca era reservada por
# ninguém: ficava pendente para sempre, sem um erro.
_NUNCA = "1970-01-01T00:00:00+00:00"

# Quanto tempo uma linha fica reservada a quem a está a enviar. Muito acima dos
# 4 s do pedido: passado isto, só um processo morto a meio a deixa presa, e a
# volta seguinte do cron pega-lhe.
_RESERVA_SEGUNDOS = 60

# A espera antes da tentativa seguinte, em minutos: 1, 2, 5, 10 e daí em diante
# 30. Ao fim de 24 h **a falhar** (contadas da primeira falha técnica, ver
# `_falhou`), desiste-se (`falhado`).
_ESPERAS_EM_MINUTOS = (1, 2, 5, 10, 30)
_DESISTIR_AO_FIM_DE = timedelta(hours=24)

_RESPOSTAS_FEITAS = ("creditado", "ja_creditado", "estornado", "ja_estornado")

# As tentativas imediatas ainda a correr — ver `tentar_ja`.
_EM_CURSO = set()


def _iso(momento: datetime) -> str:
    """Todas as datas da fila no MESMO formato, ao segundo e em UTC: a reserva
    compara-as como texto, e dois formatos diferentes ordenam-se mal."""
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def _linha_nova(tipo: str, chave: str, payload: Dict, agora: datetime, **campos) -> Dict:
    """Uma linha da fila com TODOS os campos presentes desde o nascimento: a
    reserva compara `proxima_tentativa_em` e `a_enviar_ate`, e um campo ausente
    não casa com comparação nenhuma."""
    quando = _iso(agora)
    linha = {
        "id": str(uuid.uuid4()),
        "chave": chave,
        "tipo": tipo,
        "documento_id": None,
        "nc_documento_id": None,
        "venda_id": None,
        # Para o backoffice dizer «17 pontos para Ana» sem perguntar à app.
        "primeiro_nome": None,
        "payload": payload,
        "estado": "pendente",
        "pontos": None,
        "motivo": None,
        "tentativas": 0,
        "ultimo_erro": None,
        "criado_em": quando,
        "atualizado_em": quando,
        "proxima_tentativa_em": quando,
        "a_enviar_ate": _NUNCA,
        # **O relógio das 24 h, e é ESTE e não `criado_em`.** Carimba-se na
        # primeira falha TÉCNICA (a app a responder mal, a rede em baixo) e
        # nunca mais se mexe. Contado desde o nascimento, uma linha que esperou
        # legitimamente — integração por configurar, crontab por instalar —
        # desistia na primeira falha real depois de a chave chegar, com a app
        # em baixo 4 segundos, e os pontos daquela compra perdiam-se.
        "primeira_falha_tecnica_em": None,
    }
    linha.update(campos)
    return linha


async def _enfileirar(db, linha: Dict) -> bool:
    """Insere a linha e manda-a já, em segundo plano. Devolve `False` se a
    chave já lá estava.

    `DuplicateKeyError` engole-se e não é erro nenhum: o gancho da emissão
    (`fiscal._ligar_venda_ao_documento`) corre mais do que uma vez por venda —
    o retry que reencontra o documento, a reconciliação de uma reserva presa —
    e a segunda passagem é a defesa a funcionar."""
    try:
        await db[COLECOES["pontos_app"]].insert_one(dict(linha))
    except DuplicateKeyError:
        return False
    tentar_ja(db, linha["id"])
    return True


def tentar_ja(db, linha_id: str) -> None:
    """A tentativa imediata, em SEGUNDO PLANO: agenda o envio e volta logo.

    Quem chama está dentro do EMITIR, com a fatura já na AT e a funcionária à
    espera da resposta. Esperar aqui pela app eram até 4 s de balcão parado por
    causa de pontos — e se a app estiver em baixo a linha fica pendente e o
    cron de 1 em 1 minuto pega-lhe. Com dois workers, o outro processo e o cron
    não a enviam ao mesmo tempo: a reserva de `enviar` decide.

    A tarefa fica em `_EM_CURSO` até acabar: o asyncio só guarda uma referência
    FRACA às tarefas, e uma tarefa que ninguém segura pode ser recolhida a
    meio."""
    tarefa = asyncio.get_running_loop().create_task(_tentar_em_silencio(db, linha_id))
    _EM_CURSO.add(tarefa)
    tarefa.add_done_callback(_EM_CURSO.discard)


async def _tentar_em_silencio(db, linha_id: str) -> None:
    try:
        await enviar(db, linha_id)
    except Exception as e:  # noqa: BLE001 — em segundo plano não há a quem devolver o erro
        logger.error(
            "[faturacao] envio imediato da linha de pontos %s falhou (o cron repete): %s",
            linha_id, e)


async def enviar(db, linha_id: Optional[str] = None, *, agora: Optional[datetime] = None) -> Optional[Dict]:
    """Reserva UMA linha pendente e vencida (esta, se vier `linha_id`), manda-a
    à app e grava o desfecho. Devolve a linha como ficou, ou `None` se não
    havia nada para reservar.

    **A reserva é a primeira escrita, e é condicional.** Dois workers do
    uvicorn e o cron podem pegar na mesma linha no mesmo segundo; o
    `find_one_and_update` com `a_enviar_ate < agora` deixa passar exactamente
    um. A app é idempotente de qualquer forma — a reserva é para não a
    incomodar duas vezes e para duas respostas não se escreverem por cima.

    **Um estorno só sai com o crédito `feito`.** Com o crédito ainda pendente
    espera (sem gastar tentativas: não é uma falha); com o crédito recusado ou
    falhado não há pontos a tirar e fica `sem_efeito` sem falar com a app."""
    agora = agora or datetime.now(timezone.utc)
    filtro = {
        "estado": "pendente",
        "proxima_tentativa_em": {"$lte": _iso(agora)},
        "a_enviar_ate": {"$lt": _iso(agora)},
    }
    if linha_id is not None:
        filtro["id"] = linha_id
    reserva = _iso(agora + timedelta(seconds=_RESERVA_SEGUNDOS))
    linha = await db[COLECOES["pontos_app"]].find_one_and_update(
        filtro, {"$set": {"a_enviar_ate": reserva}},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if linha is None:
        return None

    if linha["tipo"] == "estorno":
        credito = await db[COLECOES["pontos_app"]].find_one(
            {"chave": "credito:%s" % linha["documento_id"]}, {"_id": 0, "estado": 1})
        estado_do_credito = (credito or {}).get("estado")
        if estado_do_credito == "pendente":
            return await _fechar(db, linha, reserva, agora, {
                "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
                "ultimo_erro": "à espera do crédito da fatura",
            })
        if estado_do_credito != "feito":
            return await _fechar(db, linha, reserva, agora, {
                "estado": "sem_efeito",
                "motivo": "credito_%s" % (estado_do_credito or "inexistente"),
            })

    acao = "creditar" if linha["tipo"] == "credito" else "estornar"
    try:
        resposta = await _chamar_app(acao, linha["payload"])
    except IntegracaoNaoConfigurada:
        # «Não se perde nada»: sem configuração a linha ESPERA — não falhou.
        # O molde é o do estorno à espera do crédito, aqui em cima: não gasta
        # tentativa (senão a primeira tentativa a sério só acontecia 30 min
        # depois de a chave chegar) e não carimba `primeira_falha_tecnica_em`,
        # por isso as 24 h nem sequer arrancaram. As 24 h são para a app em
        # baixo, não para um servidor por acabar de instalar.
        return await _fechar(db, linha, reserva, agora, {
            "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
            "ultimo_erro": "integração não configurada",
        })
    except httpx.HTTPError as e:
        return await _falhou(db, linha, reserva, agora, "rede: %s %s" % (type(e).__name__, e))

    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    estado_da_app = corpo.get("estado") if isinstance(corpo, dict) else None
    if estado_da_app in _RESPOSTAS_FEITAS:
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "feito", "pontos": corpo.get("pontos")})
    if estado_da_app == "recusado":
        # Uma recusa de negócio (plataforma, acima do teto, ligação já usada…)
        # não muda por se repetir — e repeti-la era bater à porta da app de 30
        # em 30 minutos durante um dia inteiro.
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "recusado", "motivo": corpo.get("motivo")})
    if estado_da_app == "sem_efeito":
        return await _fechar(db, linha, reserva, agora, {"estado": "sem_efeito"})
    # 401 (chaves trocadas), 5xx, ou um 200 que não diz nada do contrato.
    return await _falhou(db, linha, reserva, agora,
                         "HTTP %s: %s" % (resposta.status_code, resposta.text[:200]))


async def _falhou(db, linha: Dict, reserva: str, agora: datetime, erro: str) -> Dict:
    """Uma falha TÉCNICA: conta a tentativa, afasta a seguinte e, ao fim de 24 h
    **a falhar**, desiste.

    O relógio conta de `primeira_falha_tecnica_em` e não de `criado_em`: uma
    linha que esperou pela configuração (ver o `except IntegracaoNaoConfigurada`
    de `enviar`) não pode desistir na primeira falha real, e é isso que
    `criado_em` fazia — a app em baixo 4 segundos e os pontos perdidos."""
    tentativas = int(linha.get("tentativas") or 0) + 1
    espera = _ESPERAS_EM_MINUTOS[min(tentativas, len(_ESPERAS_EM_MINUTOS)) - 1]
    primeira = linha.get("primeira_falha_tecnica_em") or _iso(agora)
    campos = {
        "tentativas": tentativas,
        "ultimo_erro": erro[:300],
        "proxima_tentativa_em": _iso(agora + timedelta(minutes=espera)),
        # Escrito sempre com o valor que já lá estava (ou o de agora, na
        # primeira): carimba uma vez e fica — recarimbá-lo a cada falha adiava
        # as 24 h para sempre.
        "primeira_falha_tecnica_em": primeira,
    }
    if agora - datetime.fromisoformat(primeira) >= _DESISTIR_AO_FIM_DE:
        campos["estado"] = "falhado"
    logger.warning(
        "[faturacao] pontos da app: a linha %s (%s) não chegou à app (tentativa %d): %s",
        linha["id"], linha["chave"], tentativas, erro)
    return await _fechar(db, linha, reserva, agora, campos)


async def _fechar(db, linha: Dict, reserva: str, agora: datetime, campos: Dict) -> Dict:
    """Grava o desfecho e larga a reserva — só se a reserva ainda for ESTA. Se
    o envio demorou mais do que `_RESERVA_SEGUNDOS` e outro processo pegou na
    linha entretanto, é a escrita dele que vale."""
    campos = dict(campos, a_enviar_ate=_NUNCA, atualizado_em=_iso(agora))
    await db[COLECOES["pontos_app"]].update_one(
        {"id": linha["id"], "a_enviar_ate": reserva}, {"$set": campos})
    linha.update(campos)
    return linha


# --- O crédito, na emissão ------------------------------------------------------


async def enfileirar_credito(db, venda_id: str, documento: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o crédito desta Fatura Simplificada, se a venda tiver um
    cliente ligado. Chamado no fim de `fiscal._ligar_venda_ao_documento`.

    - **Só o modo `normal`.** Uma fatura em `tests` não existe na AT, e
      creditar pontos por ela era dar pontos por nada.
    - **A ligação lê-se da VENDA gravada**, não do pedido: é a venda que chega
      aos cinco caminhos da emissão, a reconciliação incluída.
    - **O corpo é o contrato de `/api/pos-integracao/creditar`**, e fica
      gravado na linha: os reenvios mandam exactamente o mesmo, dias depois
      se for preciso, sem voltar a ler a venda.

    Os meios de pagamento vão pelo id do VENDUS — é por eles, e só por eles,
    que a app recusa Uber Eats, Glovo e Bolt — e saem do RETRATO gravado na
    venda (`fiscal.finalizar`), que é o que valia no dia. A releitura de
    `fat_tipos_pagamento` é só o recuo para as vendas de antes desse campo
    existir; um pagamento que não dê id nenhum fica de fora da lista, mas
    NUNCA em silêncio (é assim que a recusa por plataforma falharia aberta).
    A caução vai à parte (`deposito`, carimbado no documento pela emissão): os
    pontos contam sobre o total sem ela. O operador é o dono da CONTA
    (`operador_id` da venda), o mesmo que o backoffice mostra no documento."""
    if documento.get("modo") != "normal":
        return
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    ligacao = (venda or {}).get("pontos_ligacao")
    if not ligacao:
        return
    meios = []
    for pagamento in venda.get("pagamentos") or []:
        identificador = pagamento.get("vendus_payment_method_id")
        if not identificador:
            tipo = await db[COLECOES["tipos_pagamento"]].find_one(
                {"id": pagamento.get("tipo_pagamento_id")},
                {"_id": 0, "vendus_payment_method_id": 1})
            identificador = (tipo or {}).get("vendus_payment_method_id")
        if identificador:
            meios.append(str(identificador))
        else:
            # Uma lista mais curta do que os pagamentos é a recusa por
            # plataforma a falhar ABERTA — a app não tem como saber que aquele
            # pagamento foi Glovo. Não se adivinha nada, mas fica escrito: é o
            # único sítio onde alguém pode vir a perceber porque é que aquela
            # fatura deu pontos.
            logger.error(
                "[faturacao] pontos da app: o pagamento %r da venda %s (documento "
                "%s) não tem id do Vendus — `meios_pagamento` vai mais curto e a "
                "app não consegue recusar uma plataforma por ele",
                pagamento.get("tipo_pagamento_id"), venda_id, documento["id"])
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": venda.get("loja_id")}, {"_id": 0, "nome": 1})
    operador = await db[COLECOES["utilizadores"]].find_one(
        {"id": venda.get("operador_id")}, {"_id": 0, "nome": 1})
    payload = {
        "ligacao_id": ligacao.get("id"),
        "documento_id": documento["id"],
        "atcud": documento.get("atcud"),
        "numero": documento.get("numero"),
        "emitido_em": documento.get("emitido_em"),
        "total": round(float(documento.get("total") or 0), 2),
        "caucao": round(float(documento.get("deposito") or 0), 2),
        "meios_pagamento": meios,
        "loja_nome": (loja or {}).get("nome") or "",
        "operador_nome": (operador or {}).get("nome") or "",
    }
    await _enfileirar(db, _linha_nova(
        "credito", "credito:%s" % documento["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=documento["id"], venda_id=venda_id,
        primeiro_nome=ligacao.get("primeiro_nome")))


# --- O estorno, na nota de crédito ----------------------------------------------


async def enfileirar_estorno(db, nota: Dict, documento_nc: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o estorno desta nota de crédito, se a fatura de origem tiver
    uma linha de crédito. Chamado em `nota_credito.emitir_nota_credito`, logo a
    seguir à marca `emitida`.

    Não interessa aqui se o crédito já chegou à app: a linha entra na mesma, e
    é o ENVIO que espera por ele (ou a fecha `sem_efeito` se ele nunca entrar).

    **A caução da nota são as linhas `NS`.** O depósito de embalagem é a única
    coisa deste POS fora do imposto (`precos.CODIGO_NAO_SUJEITO`), e a nota
    credita-o como qualquer outra linha da fatura. Os pontos contam sem ela,
    por isso a app precisa de a saber para tirar a proporção certa. Somada em
    cêntimos inteiros, como todo o dinheiro deste módulo."""
    if documento_nc.get("modo") != "normal":
        return
    credito = await db[COLECOES["pontos_app"]].find_one(
        {"chave": "credito:%s" % nota["documento_id"]}, {"_id": 0})
    if not credito:
        return
    caucao_em_centimos = sum(
        round(float(linha.get("total") or 0) * 100)
        for linha in nota.get("linhas") or []
        if linha.get("tax_id") == CODIGO_NAO_SUJEITO
    )
    payload = {
        "atcud_origem": credito["payload"]["atcud"],
        "nc_id": documento_nc["id"],
        "numero_nc": documento_nc.get("numero"),
        "valor_nc": round(float(nota.get("total") or 0), 2),
        "caucao_nc": caucao_em_centimos / 100.0,
    }
    await _enfileirar(db, _linha_nova(
        "estorno", "estorno:%s" % documento_nc["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=nota["documento_id"], nc_documento_id=documento_nc["id"],
        venda_id=nota.get("venda_id"), primeiro_nome=credito.get("primeiro_nome")))


# --- A volta do cron -------------------------------------------------------------

# O tecto de linhas por volta. Com a app em baixo, cada linha pode gastar os 4 s
# do pedido: 50 são 200 s no pior caso, e duas voltas sobrepostas não se pisam
# (a reserva decide). Num dia normal a volta encontra zero ou uma.
_LIMITE_POR_VOLTA = 50


@router.post("/cron/pontos-app")
async def cron_pontos_app(key: str = Query(...)) -> dict:
    """A porta de 1 em 1 minuto (`faturacao-pontos-cron.sh`). Protegida pela
    `CRON_KEY`, sem JWT — o mesmo padrão de `/cron/sincronizar-app`: sem a
    variável no ambiente ninguém entra, e `compare_digest` para o tempo da
    comparação não dizer quantos caracteres estavam certos.

    Envia uma a uma as linhas pendentes que já chegaram à hora e pára quando
    não houver mais nenhuma — uma linha que falha fica com a próxima tentativa
    no futuro, por isso a mesma volta não lhe volta a pegar."""
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    db = obter_db()
    enviadas = 0
    for _ in range(_LIMITE_POR_VOLTA):
        if await enviar(db) is None:
            break
        enviadas += 1
    return {"enviadas": enviadas}
