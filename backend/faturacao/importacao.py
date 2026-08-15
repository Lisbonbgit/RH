"""Importação do catálogo Vendus (Task 21).

Enche `fat_categorias` e `fat_produtos` a partir da conta Vendus da
Fordaimon Foods (FAT_NIF, por omissão "517542510") — o dono já tem
categorias e artigos configurados lá, com preço e IVA certos, para as 5
lojas de açaí. Escrevê-los à mão no catálogo novo é exactamente onde se
erraria um IVA (ver o cabeçalho de precos.py sobre a app antiga que faturou
refrigerantes a 13% durante meses).

SÓ LEITURA do lado do Vendus — o cliente em faturacao/vendus/cliente.py
nunca escreve lá (ver a sua docstring: a app L'Açaí em produção fatura
referenciando os artigos de lá). Este módulo só LÊ de lá e ESCREVE no
catálogo PRÓPRIO (fat_categorias/fat_produtos).

Idempotência — o que uma reimportação faz a cada colecção, e porquê:

- Categorias: casadas por NOME. O modelo da Task 19 (`CategoriaEntrada`) não
  tem `vendus_ref` — a decisão D7 fixa as categorias a "Venda ao Público" /
  "Vendas Aplicações", não são um catálogo arbitrário a sincronizar campo a
  campo. Uma categoria nova no Vendus é CRIADA aqui; uma já existente é
  deixada tal e qual — `ordem`/`ativa` são decisões só nossas (como o
  backoffice as arrumou), sem equivalente no Vendus, e uma reimportação não
  as deve pisar.

- Produtos: casados por `vendus_ref` — o `id` do produto no Vendus. É
  estável (ao contrário de `reference`/SKU, que o dono pode reescrever no
  Vendus sem a intenção de criar um artigo novo). Um produto novo é CRIADO;
  um já existente é ACTUALIZADO nos campos que vêm do Vendus — nome, preço,
  tax_id, categoria — porque o Vendus é a fonte de verdade para o que o
  dono mudou LÁ. `foto_url`, `grupos_personalizacao` e `ativo` são
  PRESERVADOS: nunca vieram do Vendus, são configuração feita aqui no
  backoffice (uma foto carregada, os toppings associados, um produto
  desligado à mão) — uma reimportação não pode apagar isso nem
  reactivar/desligar um produto à revelia do que o dono decidiu aqui.
"""
import asyncio
import logging
import os
import uuid
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from .auth import gestor_atual
from .catalogo import CategoriaEntrada, ProdutoEntrada, _CODIGOS_IVA_VALIDOS
from .db import COLECOES, obter_db
from .precos import tax_id_de_taxa
from .vendus.cliente import ClienteVendus, VendusErro, obter_conta

logger = logging.getLogger(__name__)

router = APIRouter()

FAT_NIF_POR_OMISSAO = "517542510"  # Fordaimon Foods


def _nif_configurado() -> str:
    return os.environ.get("FAT_NIF") or FAT_NIF_POR_OMISSAO


def _extrair_preco(produto_vendus: dict) -> Optional[float]:
    """O preço guardado no catálogo é o preço COM IVA (ver
    precos.linha_de_venda, que usa `gross_price`) — por isso lemos
    `gross_price`, com `price` como reserva para uma conta configurada sem
    esse campo. None se nenhum dos dois vier utilizável — quem chama trata
    isso como "produto por resolver", nunca inventa um preço."""
    bruto = produto_vendus.get("gross_price", produto_vendus.get("price"))
    if bruto is None:
        return None
    try:
        return round(float(bruto), 2)
    except (TypeError, ValueError):
        return None


def _extrair_tax_id(produto_vendus: dict) -> Optional[str]:
    """O `tax_id` do Vendus já usa os mesmos códigos que este módulo usa
    internamente (NOR/INT/RED/ISE — ver precos._TAXAS), tanto nos produtos
    como nas linhas de documento que este sistema EMITE para o Vendus
    (precos.linha_de_venda). Se uma conta devolver antes uma taxa percentual
    (num campo `tax` aninhado, ou directamente em `tax_id`), converte-se com
    o mesmo `tax_id_de_taxa` que a Task 20 usa. Sem nada reconhecível,
    devolve None — a regra que não se negoceia (precos.py): nunca inventar
    um IVA."""
    direto = produto_vendus.get("tax_id")
    if isinstance(direto, str) and direto in _CODIGOS_IVA_VALIDOS:
        return direto
    aninhado = produto_vendus.get("tax")
    taxa = None
    if isinstance(aninhado, dict):
        taxa = aninhado.get("rate", aninhado.get("value"))
    elif isinstance(direto, (int, float)):
        taxa = direto
    if taxa is None:
        return None
    return tax_id_de_taxa(taxa)


async def _sincronizar_categorias(
    db, categorias_vendus: List[dict]
) -> Tuple[Dict[str, str], List[str]]:
    """Cria as categorias do Vendus que ainda não existem localmente
    (casadas por nome — ver docstring do módulo) e devolve:
    - um mapa {id_da_categoria_no_vendus: id_local_da_categoria}, para ligar
      os produtos à categoria certa;
    - a lista de problemas encontrados (categorias sem id/nome, ignoradas).

    NÃO toca nas categorias já existentes — `ordem`/`ativa` são só nossas."""
    existentes = await db[COLECOES["categorias"]].find({}, {"_id": 0}).to_list(500)
    por_nome = {c["nome"]: c["id"] for c in existentes}
    ordem_seguinte = len(existentes)
    mapa: Dict[str, str] = {}
    problemas: List[str] = []

    for c in categorias_vendus:
        vid = str(c.get("id") or "").strip()
        nome = str(c.get("title") or c.get("name") or "").strip()
        if not vid or not nome:
            problemas.append("categoria do Vendus sem id/nome ignorada: %r" % (c,))
            continue
        if nome in por_nome:
            mapa[vid] = por_nome[nome]
            continue
        try:
            dados = CategoriaEntrada(nome=nome, ordem=ordem_seguinte, ativa=True)
        except ValidationError as e:
            problemas.append("categoria '%s' recusada: %s" % (nome, e))
            continue
        nova = dados.model_dump()
        nova["id"] = str(uuid.uuid4())
        await db[COLECOES["categorias"]].insert_one(dict(nova))
        por_nome[nome] = nova["id"]
        ordem_seguinte += 1
        mapa[vid] = nova["id"]

    return mapa, problemas


async def _sincronizar_produtos(
    db, produtos_vendus: List[dict], mapa_categorias: Dict[str, str]
) -> Dict[str, object]:
    """Cria/actualiza os produtos do Vendus, casados por `vendus_ref` — ver
    a docstring do módulo para a decisão do que é actualizado e do que é
    preservado numa reimportação. Um produto que não se consiga mapear
    (sem categoria conhecida, sem preço, sem IVA reconhecível) é IGNORADO e
    reportado em `problemas` — um artigo por resolver no Vendus não pode
    abortar a importação dos restantes."""
    criados = 0
    atualizados = 0
    problemas: List[str] = []

    for p in produtos_vendus:
        vid = str(p.get("id") or "").strip()
        nome = str(p.get("title") or p.get("name") or "").strip()
        if not vid:
            problemas.append("produto sem id do Vendus ignorado: %r" % nome)
            continue

        categoria_vendus_id = str(
            p.get("category_id") or (p.get("category") or {}).get("id") or ""
        ).strip()
        categoria_id = mapa_categorias.get(categoria_vendus_id)
        preco = _extrair_preco(p)
        tax_id = _extrair_tax_id(p)

        if not categoria_id:
            problemas.append("'%s' (ref %s): categoria do Vendus desconhecida" % (nome, vid))
            continue
        if preco is None:
            problemas.append("'%s' (ref %s): sem preço" % (nome, vid))
            continue
        if not tax_id:
            problemas.append(
                "'%s' (ref %s): sem IVA reconhecido — não importado (nunca se inventa "
                "um IVA)" % (nome, vid)
            )
            continue

        existente = await db[COLECOES["produtos"]].find_one({"vendus_ref": vid}, {"_id": 0})
        try:
            if existente is None:
                dados = ProdutoEntrada(
                    nome=nome, categoria_id=categoria_id, preco=preco, tax_id=tax_id,
                    vendus_ref=vid,
                )
                novo = dados.model_dump()
                novo["id"] = str(uuid.uuid4())
                await db[COLECOES["produtos"]].insert_one(dict(novo))
                criados += 1
            else:
                # Reimportação: nome/preço/tax_id/categoria vêm do Vendus (é
                # o que o dono mudou lá); foto_url/grupos_personalizacao/
                # ativo são só nossos e têm de sobreviver.
                dados = ProdutoEntrada(
                    nome=nome, categoria_id=categoria_id, preco=preco, tax_id=tax_id,
                    foto_url=existente.get("foto_url"),
                    grupos_personalizacao=existente.get("grupos_personalizacao") or [],
                    ativo=existente.get("ativo", True),
                    vendus_ref=vid,
                )
                await db[COLECOES["produtos"]].update_one(
                    {"vendus_ref": vid}, {"$set": dados.model_dump()}
                )
                atualizados += 1
        except ValidationError as e:
            problemas.append("'%s' (ref %s) recusado: %s" % (nome, vid, e))
            continue

    return {
        "lidos": len(produtos_vendus),
        "criados": criados,
        "atualizados": atualizados,
        "problemas": problemas,
    }


@router.post("/importacao/vendus")
async def importar_vendus(_: dict = Depends(gestor_atual)) -> dict:
    """Traz categorias e produtos da conta Vendus (FAT_NIF) para o catálogo.

    Idempotente — correr outra vez actualiza, não duplica (ver docstring do
    módulo). Devolve quantos itens leu de cada colecção — o número
    verificável contra o backoffice do Vendus, para a armadilha da Task 21
    (paginação truncada a 20 por omissão) nunca passar despercebida — e
    quantos criou/actualizou/teve de ignorar.
    """
    nif = _nif_configurado()
    conta = obter_conta(nif)
    if conta is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Conta Vendus não configurada para o NIF %s. Defina VENDUS_ACCOUNTS "
                "no .env (ver backend/.env.example) com uma entrada cujo company_nif "
                "seja esse NIF." % nif
            ),
        )

    try:
        with ClienteVendus(conta.chave) as cliente:
            categorias_vendus = await asyncio.to_thread(cliente.listar_categorias)
            produtos_vendus = await asyncio.to_thread(cliente.listar_produtos)
    except VendusErro as e:
        raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)

    db = obter_db()
    mapa_categorias, problemas_categorias = await _sincronizar_categorias(db, categorias_vendus)
    resultado_produtos = await _sincronizar_produtos(db, produtos_vendus, mapa_categorias)

    return {
        "categorias_lidas": len(categorias_vendus),
        "produtos_lidos": resultado_produtos["lidos"],
        "produtos_criados": resultado_produtos["criados"],
        "produtos_atualizados": resultado_produtos["atualizados"],
        "problemas": problemas_categorias + resultado_produtos["problemas"],
    }
