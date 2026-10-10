"""`/api/crm/regioes` — as regiões que filtram as lojas no mapa.

Plano T2.9; dossiê §5.8 e §6. Porta de src/Http/Controladores/
RegioesControlador.php e de RegioesRepositorio.php do CRM autónomo. As regras
do corpo (nome 1–100 caracteres aparado, ordem inteira de um INT, 0 por
omissão) estão em `dominio/regioes.py` (T2.7): aqui só se lê, grava e responde.

- `GET /regioes` (escritório: admin e utilizador do CRM) → `[{id, nome, ordem}]`
  por ordem, depois pelo nome sem maiúsculas nem acentos
  (`texto.chave_comparacao`, a mesma da `nome_chave`) e por fim pelo `id`
  (correções do plano, linha "T2.30 e T2.9"; o `ORDER BY ordem, nome, id` do
  autónomo com a collation unicode_ci).
- `POST /regioes` `{nome, ordem?}` (admin) → 201 `{id, nome, ordem}`. Grava
  `{id (uuid4 em texto), nome, nome_chave, ordem}`: o `str(uuid.uuid4())` é o
  único `regiao_id` que uma loja aceita (`validador_loja`, T2.5).
- `PATCH /regioes/{regiao_id}` `{nome?, ordem?}` (admin) → 200 `{id, nome,
  ordem}`; só se escreve o que veio, e a `nome_chave` só se recalcula quando
  vem o nome. Sem nenhum dos dois devolve a região tal como está, sem
  escrever (um `$set` vazio o Mongo recusa).
- `DELETE /regioes/{regiao_id}` (admin) → `{apagada: true}`; com lojas → 409
  `regiao_com_lojas` (muda-se-lhe o nome em vez de a apagar).

Ordem das verificações, a do autónomo: o corpo (422, sem ler a base) → a
região existe (404; lá era o `bloquear`) → o nome é de OUTRA região (409
`regiao_repetida`) / a região tem lojas (409 `regiao_com_lojas`) → a escrita.

Nomes repetidos (sem maiúsculas nem acentos: o índice único em `nome_chave`
faz o papel da collation unicode_ci do MariaDB):
- verificam-se ANTES de gravar, para valer também se o arranque não conseguiu
  criar os índices (o CRM arranca sem eles); no PATCH com
  `{"nome_chave": k, "id": {"$ne": regiao_id}}`, para corrigir as maiúsculas
  ou os acentos do próprio nome não ser repetição (correções do plano, linha
  "T2.9");
- na corrida (outro admin grava o mesmo nome entre a verificação e a
  escrita) o índice único recusa com `DuplicateKeyError`, que só é 409 quando
  há mesmo OUTRA região com esse nome; senão não se disfarça e sobe (500).

Sem transações (o autónomo bloqueava a linha da região): uma região apagada
entre a leitura e a escrita dá 404 (o `update_one` nunca tem upsert, por isso
não a ressuscita). Corrida residual aceite (plano §9; dossiê §3): uma loja
gravada nesta região entre a contagem das lojas e o `delete_one` fica com um
`regiao_id` que já não existe.
"""
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from . import db as bd
from .auth import ESCRITORIO, SO_ADMIN
from .dominio import regioes as regras
from .dominio.texto import chave_comparacao
from .erros import erro, nao_encontrado, validacao
from .pedidos import corpo_json

router = APIRouter()

# O que sai de uma região: nunca a `nome_chave` (é só para o índice).
PROJECAO_REGIAO = {"_id": 0, "id": 1, "nome": 1, "ordem": 1}

# Para saber se uma região existe, basta o `id`.
PROJECAO_ID = {"_id": 0, "id": 1}

# Teto da lista: o volume esperado é de poucas dezenas de regiões; o teto só
# trava um caso patológico.
LIMITE_LISTA = 5000

MENSAGEM_NAO_ENCONTRADA = "Região não encontrada."
MENSAGEM_REPETIDA = "Já existe uma região com este nome."
MENSAGEM_COM_LOJAS = "Esta região tem lojas — mude-lhe o nome em vez de a apagar."


def _regiao_api(regiao) -> Dict:
    """`{id, nome, ordem}`, por esta ordem."""
    return {"id": regiao.get("id"), "nome": regiao.get("nome"), "ordem": regiao.get("ordem")}


def _repetida():
    return erro(409, "regiao_repetida", MENSAGEM_REPETIDA)


def _nao_encontrada():
    return nao_encontrado(MENSAGEM_NAO_ENCONTRADA)


def _colecao():
    return bd.obter_db()[bd.COLECOES["regioes"]]


async def _ha_outra_com_a_chave(regioes, chave: str, regiao_id=None) -> bool:
    """Há uma região (outra que não `regiao_id`, se vier) com esta `nome_chave`?"""
    filtro = {"nome_chave": chave}
    if regiao_id is not None:
        filtro["id"] = {"$ne": regiao_id}
    return await regioes.find_one(filtro, PROJECAO_ID) is not None


@router.get("/regioes")
async def listar_regioes(membro: Dict = Depends(ESCRITORIO)) -> List[Dict]:
    """Todas, por ordem, depois pelo nome (sem maiúsculas nem acentos) e pelo `id`."""
    regioes = await _colecao().find({}, PROJECAO_REGIAO).to_list(LIMITE_LISTA)
    regioes.sort(key=lambda r: (r["ordem"], chave_comparacao(r["nome"]), r["id"]))
    return [_regiao_api(regiao) for regiao in regioes]


@router.post("/regioes", status_code=201)
async def criar_regiao(admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{nome, ordem?}` → 201 `{id, nome, ordem}`. As outras chaves do corpo
    (`id`, `nome_chave`…) ignoram-se: a chave calcula-se sempre do nome."""
    campos, erros = regras.criacao(corpo)
    if erros:
        raise validacao(erros)
    chave = regras.nome_chave(campos["nome"])
    regioes = _colecao()
    if await _ha_outra_com_a_chave(regioes, chave):
        raise _repetida()
    regiao = {"id": str(uuid.uuid4()), "nome": campos["nome"], "nome_chave": chave, "ordem": campos["ordem"]}
    try:
        # O insert_one acrescenta `_id` (ObjectId) a `regiao`; não sai na
        # resposta, porque `_regiao_api` só copia as chaves da API.
        await regioes.insert_one(regiao)
    except DuplicateKeyError:
        # A corrida: outro admin gravou o mesmo nome depois da verificação.
        if await _ha_outra_com_a_chave(regioes, chave):
            raise _repetida() from None
        raise
    return _regiao_api(regiao)


@router.patch("/regioes/{regiao_id}")
async def alterar_regiao(
    regiao_id: str, admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)
) -> Dict:
    """`{nome?, ordem?}` → 200 `{id, nome, ordem}`. As outras chaves ignoram-se."""
    campos, erros = regras.alteracao(corpo)
    if erros:
        raise validacao(erros)
    regioes = _colecao()
    antes = await regioes.find_one({"id": regiao_id}, PROJECAO_REGIAO)
    if antes is None:
        raise _nao_encontrada()

    alteracoes = {}
    if "nome" in campos:
        chave = regras.nome_chave(campos["nome"])
        if await _ha_outra_com_a_chave(regioes, chave, regiao_id):
            raise _repetida()
        alteracoes["nome"] = campos["nome"]
        alteracoes["nome_chave"] = chave
    if "ordem" in campos:
        alteracoes["ordem"] = campos["ordem"]

    if alteracoes:
        try:
            resultado = await regioes.update_one({"id": regiao_id}, {"$set": alteracoes})
        except DuplicateKeyError:
            # A corrida: outra região ficou com este nome depois da
            # verificação. A própria nunca colide consigo mesma.
            if "nome_chave" in alteracoes and await _ha_outra_com_a_chave(
                regioes, alteracoes["nome_chave"], regiao_id
            ):
                raise _repetida() from None
            raise
        if resultado.matched_count == 0:
            # Apagada por outro admin entre a leitura e a escrita.
            raise _nao_encontrada()
    return _regiao_api({**antes, **campos})


@router.delete("/regioes/{regiao_id}")
async def apagar_regiao(regiao_id: str, admin: Dict = Depends(SO_ADMIN)) -> Dict:
    """→ `{apagada: true}`, ou 409 `regiao_com_lojas` se alguma loja estiver nela."""
    base = bd.obter_db()
    regioes = base[bd.COLECOES["regioes"]]
    if await regioes.find_one({"id": regiao_id}, PROJECAO_ID) is None:
        raise _nao_encontrada()
    # Pelo índice `regiao_id` de crm_lojas (o "SELECT 1 … LIMIT 1" do autónomo).
    if await base[bd.COLECOES["lojas"]].count_documents({"regiao_id": regiao_id}) > 0:
        raise erro(409, "regiao_com_lojas", MENSAGEM_COM_LOJAS)
    resultado = await regioes.delete_one({"id": regiao_id})
    if resultado.deleted_count == 0:
        # Apagada por outro admin entre a leitura e esta escrita.
        raise _nao_encontrada()
    return {"apagada": True}
