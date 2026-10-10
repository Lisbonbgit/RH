"""`/api/crm/lojas` — as lojas do mapa: listar, ler e criar (T2.10).

Plano T2.10; dossiê §5.2, §5.5 e §6. Porta de src/Http/Controladores/
LojasControlador.php (`listar`, `ver`, `criar`) e do LojasRepositorio.php do
CRM autónomo. As regras do corpo estão em `dominio/validador_loja.py` (T2.5),
os duplicados em `dominio/geo.py` (T2.3) e a forma do documento e da resposta
em `formatar.py`: aqui só se lê, grava e responde. Editar (T2.11) e apagar
(T2.12) juntam-se a este módulo.

Só o escritório (admin e utilizador do CRM): o motorista ganha o POST na F4
(plano §1, "Perfis por rota").

- `GET /lojas` → `[{id, nome, fase, regiao_id, lat, lng, telefone}]` (o
  resumo para o mapa; os filtros aplicam-se no cliente), pelo nome sem
  maiúsculas nem acentos (`texto.chave_comparacao`, a collation do
  `ORDER BY nome, id` do autónomo) e depois pelo `id`.
- `GET /lojas/{loja_id}` → a loja completa, ou 404 "Loja não encontrada.".
- `POST /lojas` (os campos da loja + `confirmar_duplicado?`) → 201 com a loja
  completa. As outras chaves do corpo (`id`, `criado_por`, `fase_desde`,
  `atualizado_em`, `loc`, `janelas`…) ignoram-se: o servidor decide-as.

Ordem das verificações do POST, a do autónomo: o corpo (422 com os campos,
sem ler a base) → a região existe (422 em `regiao_id` "A região não
existe.") → outra loja a menos de 50 m (409 `duplicado`, com as lojas da mais
perto para a mais longe, e nada se grava), salvo com `"confirmar_duplicado":
true` — só o booleano JSON: `"true"`, `1` e `null` não confirmam → a escrita.

Sem transações (o autónomo lia a região com bloqueio partilhado na transação
que gravava a loja). Corridas residuais aceites (plano §9; dossiê §3): uma
região apagada entre a verificação e o `insert_one` deixa um `regiao_id`
órfão (os filtros do mapa toleram-no, T2.25); e dois pedidos no mesmo
instante e no mesmo sítio gravam-se os dois — o duplicado é um aviso, não uma
regra da base (também era assim no autónomo).
"""
from typing import Dict, List

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio
from .auth import ESCRITORIO
from .dominio import validador_loja
from .dominio.geo import encontrar_duplicados, filtro_candidatos
from .dominio.texto import chave_comparacao
from .erros import erro, nao_encontrado, validacao
from .formatar import CAMPOS_RESUMO, documento_loja, loja_api, resumo_loja_api
from .pedidos import corpo_json

router = APIRouter()

# A loja completa: tudo menos o `_id` (o `loc` e a lista das janelas o
# `loja_api` não os copia).
PROJECAO_LOJA = {"_id": 0}

# O resumo do mapa.
PROJECAO_RESUMO = {"_id": 0, **{campo: 1 for campo in CAMPOS_RESUMO}}

# O que a regra dos 50 m mede em cada candidato (`geo.encontrar_duplicados`).
PROJECAO_CANDIDATO = {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}

# Para saber se a região existe, basta o `id`.
PROJECAO_ID = {"_id": 0, "id": 1}

# Teto das listas: o volume esperado é de centenas de lojas (plano §3), e no
# círculo de 60 m dos duplicados, umas poucas; o teto só trava um caso
# patológico.
LIMITE_LISTA = 5000

MENSAGEM_NAO_ENCONTRADA = "Loja não encontrada."
MENSAGEM_REGIAO_NAO_EXISTE = "A região não existe."


def _colecao():
    return bd.obter_db()[bd.COLECOES["lojas"]]


@router.get("/lojas")
async def listar_lojas(membro: Dict = Depends(ESCRITORIO)) -> List[Dict]:
    """O resumo de todas, pelo nome (sem maiúsculas nem acentos) e pelo `id`."""
    lojas = await _colecao().find({}, PROJECAO_RESUMO).to_list(LIMITE_LISTA)
    lojas.sort(key=lambda loja: (chave_comparacao(loja["nome"]), loja["id"]))
    return [resumo_loja_api(loja) for loja in lojas]


@router.post("/lojas", status_code=201)
async def criar_loja(membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """Os campos da loja + `confirmar_duplicado?` → 201 com a loja completa."""
    dados, erros = validador_loja.criacao(corpo)
    if erros:
        raise validacao(erros)

    # Só o true confirma (em Python, `1 == True`: por isso `is`).
    confirmado = corpo.get("confirmar_duplicado") is True
    agora = relogio.agora()
    base = bd.obter_db()

    # A região validada é um uuid4 em texto (nunca um operador do Mongo).
    regiao_id = dados["regiao_id"]
    if regiao_id is not None and await base[bd.COLECOES["regioes"]].find_one({"id": regiao_id}, PROJECAO_ID) is None:
        raise validacao({"regiao_id": MENSAGEM_REGIAO_NAO_EXISTE})

    lojas = base[bd.COLECOES["lojas"]]
    if not confirmado:
        # O pré-filtro pelo índice `2dsphere` (círculo de 60 m) e depois a
        # regra exata dos 50 m em Python (T2.3).
        candidatos = await lojas.find(filtro_candidatos(dados["lat"], dados["lng"]), PROJECAO_CANDIDATO).to_list(
            LIMITE_LISTA
        )
        duplicados = encontrar_duplicados(candidatos, dados["lat"], dados["lng"])
        if duplicados:
            raise erro(409, "duplicado", f"Já existe {duplicados[0]['nome']} aqui — é a mesma?", lojas=duplicados)

    loja = documento_loja(dados, membro["user_id"], agora)
    # O insert_one acrescenta `_id` (ObjectId) a `loja`; não sai na resposta,
    # porque o `loja_api` só copia as chaves da API.
    await lojas.insert_one(loja)
    return loja_api(loja)


@router.get("/lojas/{loja_id}")
async def ler_loja(loja_id: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """A loja completa, ou 404."""
    loja = await _colecao().find_one({"id": loja_id}, PROJECAO_LOJA)
    if loja is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    return loja_api(loja)
