"""`/api/crm/lojas/{loja_id}/contactos` — os contactos de uma loja (2026-11-07).

Desenho dos contactos §3; dossiê §5.11 e §6. Cada contacto é uma linha de
`crm_interacoes` (`{id, loja_id, tipo, resultado: null, notas: <resumo>,
paragem_id: null, utilizador_id, ocorrida_em, criado_em, editado_em: null,
client_uuid}`). As regras estão em `dominio/contactos.py`: aqui só se lê, grava
e responde. Só o escritório (admin e utilizador do CRM): o motorista só entra
no terreno na F4.

- `GET /lojas/{loja_id}/contactos`
- `POST …/contactos` `{tipo, data, resumo, client_uuid?}` → 201
- `PATCH …/contactos/{contacto_id}` `{tipo?, data?, resumo?}`
- `DELETE …/contactos/{contacto_id}`

As quatro devolvem o mesmo, `{hoje, contactos: [{id, numero, tipo, data, resumo,
autor, pode_alterar, corrigido}]}`, do mais recente para o mais antigo: a
numeração fica só com o servidor, porque um contacto com data antiga renumera
os outros. Na lista só entram `visita`, `chamada` e `mensagem`; a F4 revê esta
lista junto com as do recálculo.

Relógio: nas escritas lê-se uma vez (`agora`, e `hoje` tirado dele), para a
validação, os instantes gravados e a resposta ficarem do mesmo instante; no GET,
`relogio.hoje()`. `ocorrida_em` é o instante do pedido se a data for hoje, e as
12:00 de Lisboa desse dia se for outra; um PATCH que não muda a data não lhe
toca. Na API, `data` é sempre o dia de Lisboa do `ocorrida_em`
(`relogio.dia_lisboa`).

Ordem das recusas do PATCH: o corpo (422, sem ler a base) → a loja (404) → o
contacto (404: não existe, é de outra loja ou de um tipo fora dos três) → a
permissão (403 `sem_permissao`) → a escrita. Sem nada a mudar responde-se 200 com
a lista, sem escrever e sem `editado_em`. No DELETE, a mesma ordem sem o corpo.

`client_uuid`: um reenvio do mesmo bloco não cria outra linha. Antes de gravar
faz-se `find_one`, porque o CRM pode arrancar sem índices, e o `DuplicateKeyError`
do `insert_one` apanha a corrida, como em `membros.py`. Um repetido da mesma
loja volta a aplicar os `$max` com o `tipo` e o `ocorrida_em` da linha gravada, e
responde como se tivesse corrido bem: é o que acerta a loja depois de uma falha
entre o `insert_one` e o `$max`. Um repetido de outra loja é 422 em `client_uuid`.

Último contacto: o POST sobe `ultima_interacao_em` e, numa visita,
`ultima_visita_ou_entrega_em`, com `$max`, porque os instantes ordenam como
texto. O PATCH e o DELETE recalculam a partir das interações, porque a data pode
ter recuado. Sem transações, como na `mudanca_fase`: o contacto grava-se
primeiro e, se a loja falhar, fica uma linha `[crm]` no registo e responde-se com
sucesso. Corrida residual aceite: um recálculo que leia antes de um POST e
escreva depois dele perde esse instante até ao contacto seguinte.

Guardar um contacto não muda a fase da loja (a fase muda-se à mão) nem o
`atualizado_em`: a ficha aberta noutro sítio não recebe um conflito falso.
"""
import logging
import uuid
from typing import Dict

from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from . import db as bd
from . import relogio
from .auth import ESCRITORIO, MENSAGEM_SEM_PERMISSAO
from .dominio import contactos
from .dominio.datas import texto_data
from .erros import erro, nao_encontrado, validacao
from .lojas import LIMITE_LISTA, MENSAGEM_NAO_ENCONTRADA, PROJECAO_ID
from .pedidos import corpo_json

logger = logging.getLogger(__name__)

router = APIRouter()

MENSAGEM_CONTACTO_NAO_ENCONTRADO = "Contacto não encontrado."
# O `autor` de um contacto cuja conta do portal já não existe.
CONTA_REMOVIDA = "Conta removida"

# O que a lista e as regras leem de cada linha.
PROJECAO_CONTACTO = {
    "_id": 0, "id": 1, "tipo": 1, "notas": 1, "paragem_id": 1, "utilizador_id": 1,
    "ocorrida_em": 1, "criado_em": 1, "editado_em": 1,
}
# De um repetido, o que chega para decidir e para voltar a subir a loja.
PROJECAO_REPETIDO = {"_id": 0, "loja_id": 1, "tipo": 1, "ocorrida_em": 1}
# Das contas do portal, só o nome: o email nunca sai.
PROJECAO_AUTOR = {"_id": 0, "id": 1, "name": 1}
PROJECAO_INSTANTE = {"_id": 0, "ocorrida_em": 1}


def _interacoes(base):
    return base[bd.COLECOES["interacoes"]]


def _filtro_contactos(loja_id: str) -> Dict:
    return {"loja_id": loja_id, "tipo": {"$in": list(contactos.TIPOS_CONTACTO)}}


@router.get("/lojas/{loja_id}/contactos")
async def listar_contactos(loja_id: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """`{hoje, contactos}`, ou 404 se a loja não existir."""
    base = bd.obter_db()
    await _exigir_loja(base, loja_id)
    return await _resposta(base, loja_id, relogio.hoje(), membro)


@router.post("/lojas/{loja_id}/contactos", status_code=201)
async def criar_contacto(loja_id: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{tipo, data, resumo, client_uuid?}` → 201 com a lista (o repetido e a
    corrida no docstring do módulo)."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dados, erros = contactos.criacao(corpo, hoje)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    await _exigir_loja(base, loja_id)

    interacoes = _interacoes(base)
    linha = await _ja_gravada(interacoes, loja_id, dados["client_uuid"])
    if linha is None:
        linha = _documento_contacto(loja_id, dados, membro["user_id"], hoje, agora)
        try:
            # O insert_one acrescenta `_id` (ObjectId) a `linha`; não sai na
            # resposta, que volta a ler a lista.
            await interacoes.insert_one(linha)
        except DuplicateKeyError:
            # A corrida: outro pedido gravou o mesmo `client_uuid` depois da
            # verificação. Sem linha, a chave repetida era outra: um erro a sério.
            linha = await _ja_gravada(interacoes, loja_id, dados["client_uuid"])
            if linha is None:
                raise

    await _subir_ultimo_contacto(base, loja_id, linha["tipo"], linha["ocorrida_em"])
    return await _resposta(base, loja_id, hoje, membro)


@router.patch("/lojas/{loja_id}/contactos/{contacto_id}")
async def alterar_contacto(
    loja_id: str, contacto_id: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)
) -> Dict:
    """`{tipo?, data?, resumo?}` → a lista (ordem das recusas no docstring do
    módulo)."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dados, erros = contactos.alteracao(corpo, hoje)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    linha = await _contacto_a_alterar(base, loja_id, contacto_id, membro)

    mudancas = contactos.mudancas(linha, relogio.dia_lisboa(linha["ocorrida_em"]), dados)
    if mudancas:
        resultado = await _interacoes(base).update_one(
            {"id": contacto_id, "loja_id": loja_id}, {"$set": _valores_novos(mudancas, hoje, agora)}
        )
        if resultado.matched_count == 0:
            # Apagado por outra pessoa entre a leitura e esta escrita.
            raise nao_encontrado(MENSAGEM_CONTACTO_NAO_ENCONTRADO)
        await _recalcular_ultimo_contacto(base, loja_id)

    return await _resposta(base, loja_id, hoje, membro)


@router.delete("/lojas/{loja_id}/contactos/{contacto_id}")
async def apagar_contacto(loja_id: str, contacto_id: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """→ a lista. Não lê o corpo."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)

    base = bd.obter_db()
    await _contacto_a_alterar(base, loja_id, contacto_id, membro)

    resultado = await _interacoes(base).delete_one({"id": contacto_id, "loja_id": loja_id})
    if resultado.deleted_count == 0:
        # Apagado por outra pessoa entre a leitura e esta escrita.
        raise nao_encontrado(MENSAGEM_CONTACTO_NAO_ENCONTRADO)
    await _recalcular_ultimo_contacto(base, loja_id)

    return await _resposta(base, loja_id, hoje, membro)


async def _exigir_loja(base, loja_id: str) -> None:
    if await base[bd.COLECOES["lojas"]].find_one({"id": loja_id}, PROJECAO_ID) is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)


async def _contacto_a_alterar(base, loja_id: str, contacto_id: str, membro: Dict) -> Dict:
    """A linha, depois da loja (404), do contacto (404) e da permissão (403)."""
    await _exigir_loja(base, loja_id)
    linha = await _interacoes(base).find_one({"id": contacto_id, **_filtro_contactos(loja_id)}, PROJECAO_CONTACTO)
    if linha is None:
        raise nao_encontrado(MENSAGEM_CONTACTO_NAO_ENCONTRADO)
    if not contactos.pode_alterar(linha, membro["crm_perfil"], membro["user_id"]):
        raise erro(403, "sem_permissao", MENSAGEM_SEM_PERMISSAO)
    return linha


async def _ja_gravada(interacoes, loja_id: str, client_uuid):
    """A linha desta loja com este `client_uuid`, ou `None` (sem `client_uuid`
    nem se pergunta: `null` apanhava todas as interações sem ele). Noutra loja é
    422, nunca sucesso."""
    if client_uuid is None:
        return None
    linha = await interacoes.find_one({"client_uuid": client_uuid}, PROJECAO_REPETIDO)
    if linha is not None and linha["loja_id"] != loja_id:
        raise validacao({"client_uuid": contactos.MENSAGEM_CLIENT_UUID_DE_OUTRA_LOJA})
    return linha


def _ocorrida_em(dia, hoje, agora) -> str:
    return relogio.instante(agora) if dia == hoje else relogio.meio_dia_lisboa(dia)


def _documento_contacto(loja_id: str, dados: Dict, utilizador_id, hoje, agora) -> Dict:
    """O contacto novo, como fica gravado em `crm_interacoes`."""
    return {
        "id": str(uuid.uuid4()),
        "loja_id": loja_id,
        "tipo": dados["tipo"],
        "resultado": None,
        "notas": dados["resumo"],
        "paragem_id": None,
        "utilizador_id": utilizador_id,
        "ocorrida_em": _ocorrida_em(dados["data"], hoje, agora),
        "criado_em": relogio.instante(agora),
        "editado_em": None,
        "client_uuid": dados["client_uuid"],
    }


def _valores_novos(mudancas: Dict, hoje, agora) -> Dict:
    """O `$set` de um PATCH com alguma coisa a mudar: só os campos que mudam,
    como a base os guarda, e o `editado_em`, que é o "corrigido" na API."""
    novos = {"editado_em": relogio.instante(agora)}
    if "tipo" in mudancas:
        novos["tipo"] = mudancas["tipo"]
    if "data" in mudancas:
        novos["ocorrida_em"] = _ocorrida_em(mudancas["data"], hoje, agora)
    if "resumo" in mudancas:
        novos["notas"] = mudancas["resumo"]
    return novos


async def _subir_ultimo_contacto(base, loja_id: str, tipo: str, ocorrida_em: str) -> None:
    """O `$max` na loja (ver o docstring do módulo). Só com os dois campos: o
    `atualizado_em` fica como estava."""
    try:
        await base[bd.COLECOES["lojas"]].update_one(
            {"id": loja_id}, {"$max": contactos.ultimos_instantes(tipo, ocorrida_em)}
        )
    except Exception as e:  # noqa: BLE001 — o contacto já está gravado (ver o docstring do módulo)
        _registar_falha(loja_id, e)


async def _recalcular_ultimo_contacto(base, loja_id: str) -> None:
    """Os dois campos da loja a partir das interações que ficaram (ver o
    docstring do módulo). Sem nenhuma, voltam a `null`."""
    try:
        await base[bd.COLECOES["lojas"]].update_one({"id": loja_id}, {"$set": {
            "ultima_interacao_em": await _ultimo_instante(base, loja_id, contactos.TIPOS_ULTIMA_INTERACAO),
            "ultima_visita_ou_entrega_em": await _ultimo_instante(base, loja_id, contactos.TIPOS_VISITA_OU_ENTREGA),
        }})
    except Exception as e:  # noqa: BLE001 — o contacto já está gravado (ver o docstring do módulo)
        _registar_falha(loja_id, e)


async def _ultimo_instante(base, loja_id: str, tipos):
    """O `ocorrida_em` mais recente das interações destes `tipos`, ou `None`."""
    filtro = {"loja_id": loja_id, "tipo": {"$in": list(tipos)}}
    linhas = await _interacoes(base).find(filtro, PROJECAO_INSTANTE).sort("ocorrida_em", -1).limit(1).to_list(1)
    return linhas[0]["ocorrida_em"] if linhas else None


def _registar_falha(loja_id: str, excecao: Exception) -> None:
    """A linha `[crm]`, só com o id da loja e o tipo da exceção: nunca a mensagem
    dela (pode trazer o documento), nem o resumo, nem quem o escreveu."""
    logger.error(
        "[crm] loja %s: o contacto ficou gravado, mas o último contacto da loja não se atualizou (%s)",
        loja_id,
        type(excecao).__name__,
    )


async def _nomes_dos_autores(base, linhas: list) -> Dict:
    """`{user_id: name}` dos autores, de uma vez (só os ids de texto: `null` no
    `$in` apanhava contas sem `id`)."""
    ids = sorted({linha.get("utilizador_id") for linha in linhas if isinstance(linha.get("utilizador_id"), str)})
    if not ids:
        return {}
    contas = await base.users.find({"id": {"$in": ids}}, PROJECAO_AUTOR).to_list(LIMITE_LISTA)
    return {conta["id"]: conta.get("name") for conta in contas}


def _contacto_api(numero: int, linha: Dict, nomes: Dict, membro: Dict) -> Dict:
    """Uma linha na forma da API."""
    return {
        "id": linha["id"],
        "numero": numero,
        "tipo": linha["tipo"],
        "data": texto_data(relogio.dia_lisboa(linha["ocorrida_em"])),
        "resumo": linha["notas"],
        "autor": nomes.get(linha.get("utilizador_id")) or CONTA_REMOVIDA,
        "pode_alterar": contactos.pode_alterar(linha, membro["crm_perfil"], membro["user_id"]),
        "corrigido": linha.get("editado_em") is not None,
    }


async def _resposta(base, loja_id: str, hoje, membro: Dict) -> Dict:
    """A resposta das quatro rotas: `{hoje, contactos}`."""
    linhas = await _interacoes(base).find(_filtro_contactos(loja_id), PROJECAO_CONTACTO).to_list(LIMITE_LISTA)
    nomes = await _nomes_dos_autores(base, linhas)
    return {
        "hoje": texto_data(hoje),
        "contactos": [_contacto_api(numero, linha, nomes, membro) for numero, linha in contactos.numerados(linhas)],
    }
