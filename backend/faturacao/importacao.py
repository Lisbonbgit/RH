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

- Categorias: casadas por `vendus_ref` — o `id` da categoria no Vendus,
  gravado em `CategoriaEntrada.vendus_ref`. O nome NÃO é chave: o ecrã
  deixa renomear a categoria, e casar por nome fazia uma categoria
  renomeada aqui ser "perdida" na reimportação seguinte (o Vendus
  recriava-a com o nome de lá e arrastava-lhe os produtos todos). O nome
  só serve de reserva na PRIMEIRA ligação, para uma categoria já existente
  sem `vendus_ref` ainda (criada à mão, ou de antes desta correcção) não
  ficar duplicada — encontrada por nome, o `vendus_ref` é gravado nela e
  passa a ser a chave a partir daí. Uma categoria nova no Vendus é CRIADA
  aqui; uma já ligada é deixada tal e qual — `ordem`/`ativa`/`nome` são
  decisões só nossas (como o backoffice as arrumou), sem equivalente no
  Vendus, e uma reimportação não as deve pisar.

- Produtos: casados por `vendus_ref` — o `id` do produto no Vendus. É
  estável (ao contrário de `reference`/SKU, que o dono pode reescrever no
  Vendus sem a intenção de criar um artigo novo). Sem correspondência por
  `vendus_ref`, procura-se por nome (+categoria) entre os produtos SEM
  `vendus_ref` — um produto criado à mão no backoffice, que o ecrã vazio
  convida a criar antes de se importar do Vendus — e LIGA-SE em vez de
  duplicar. Um produto novo é CRIADO; um já existente (por `vendus_ref` ou
  ligado agora por nome) é ACTUALIZADO nos campos que vêm do Vendus —
  nome, preço, tax_id, categoria — porque o Vendus é a fonte de verdade
  para o que o dono mudou LÁ. `grupos_personalizacao` e `ativo` são
  PRESERVADOS: nunca vieram do Vendus, são configuração feita aqui no
  backoffice (os toppings associados, um produto desligado à mão) — uma
  reimportação não pode apagar isso nem reactivar/desligar um produto à
  revelia do que o dono decidiu aqui.

- A FOTO deixou de estar nessa lista e passou a ter uma regra de
  PRECEDÊNCIA própria, porque o dono pediu as duas coisas ao mesmo tempo:
  «pode pegar as imagens do vendus» e «as que você não conseguir deixe no
  backoffice a opção de fazer upload». Em resumo: quem AGIU aqui ganha a um
  automatismo, e uma reimportação nunca APAGA uma foto. O quadro completo,
  linha a linha, está em `fotos.foto_da_reimportacao` — e as fotos
  carregadas aqui ficam no NOSSO servidor, nunca no Vendus (`fotos.py`
  explica porquê).
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
from .fotos import foto_da_reimportacao
from .precos import _tem_mais_de_2_casas_decimais, tax_id_de_taxa
from .vendus.cliente import ClienteVendus, VendusErro, obter_conta

logger = logging.getLogger(__name__)

router = APIRouter()

FAT_NIF_POR_OMISSAO = "517542510"  # Fordaimon Foods


def _nif_configurado() -> str:
    return os.environ.get("FAT_NIF") or FAT_NIF_POR_OMISSAO


def _extrair_preco(produto_vendus: dict) -> Optional[float]:
    """O preço guardado no catálogo é o preço COM IVA (ver
    precos.linha_de_venda, que usa `gross_price`) — por isso lemos SÓ
    `gross_price`. No Vendus, `price` é o preço LÍQUIDO (sem IVA): não é o
    mesmo número com outro nome, é uma quantidade diferente — usá-lo como
    reserva gravaria o preço a menos do IVA embutido, em silêncio (um açaí
    de €8,99 com IVA a 13% entraria a ~€7,96, e a importação diria que
    correu bem).

    Sem `gross_price` utilizável, devolve None — quem chama trata isso como
    "produto por resolver" (vai para `problemas`), nunca inventa um preço.

    Não se arredonda aqui: `round(x, 2)` faria um valor com mais de 2 casas
    decimais "parecer limpo" e o crivo das 2 casas que o resto do módulo
    aplica (precos._tem_mais_de_2_casas_decimais) nunca chegaria a disparar
    neste caminho. Em vez disso, um valor com mais de 2 casas também
    devolve None — fica por resolver, não é arredondado às escondidas."""
    bruto = produto_vendus.get("gross_price")
    if bruto is None:
        return None
    try:
        valor = float(bruto)
    except (TypeError, ValueError):
        return None
    if _tem_mais_de_2_casas_decimais(valor):
        return None
    return valor


# O endereço das fotos do Vendus vem RELATIVO — `/foto/b906f77_m.png` — e é o
# detalhe que uma leitura à pressa da documentação deixa passar: um
# `<img src="/foto/b906f77_m.png">` no nosso domínio pede a foto ao NOSSO
# servidor, leva um 404 e desenha o ícone de imagem partida em cada mosaico da
# grelha. Absolutiza-se contra este anfitrião, que é o mesmo da `BASE_URL` do
# cliente (`https://www.vendus.pt/ws/v1.1/`).
_ANFITRIAO_VENDUS = "https://www.vendus.pt"


def _extrair_foto(produto_vendus: dict) -> Optional[str]:
    """O endereço da foto de um produto do Vendus — `None` quando não tem.

    **Confirmado na documentação oficial da API v1.1**
    (https://www.vendus.pt/ws/v1.1/products.doc, campo a campo): na RESPOSTA,
    `images` é um `array` («Images List») e cada item traz `xs` («Small Image
    Url», exemplo `/foto/b906f77_xs.png`) e `m` («Medium Image Url», exemplo
    `/foto/b906f77_m.png`). No PEDIDO existe um campo `image` («Either an url or
    a base64 encoded string») — que este módulo NÃO usa: o cliente do Vendus
    daqui é só de leitura (ver `vendus/cliente.py`).

    **Não foi feita uma chamada real** — não há chave Vendus neste repositório
    — e por isso o leitor não confia na forma: aceita a lista documentada e
    também um objecto solto, aguenta o campo ausente, vazio ou com itens que
    não são dicionários, e recusa tudo o que não termine num endereço `http`
    ou `https`. Essa última recusa não é zelo: o que sai daqui vai para um
    `src` de `<img>` no ecrã do balcão, e um `javascript:` nesse atributo é uma
    porta aberta por uma fonte externa.

    **Prefere o `m` ao `xs`.** A grelha do POS desenha mosaicos 4:3 e o
    diálogo do produto mostra a mesma foto — o `xs` é a miniatura da lista do
    Vendus e, esticada no mosaico, lê-se desfocada. Sem `m`, serve o `xs`
    (desfocada é melhor do que nenhuma); o que não se faz é adivinhar o nome do
    ficheiro médio a partir do pequeno."""
    imagens = produto_vendus.get("images")
    if isinstance(imagens, dict):
        imagens = [imagens]
    for item in imagens or []:
        if not isinstance(item, dict):
            continue
        for chave in ("m", "xs"):
            bruto = item.get(chave)
            if not isinstance(bruto, str) or not bruto.strip():
                continue
            endereco = bruto.strip()
            if endereco.startswith("http://") or endereco.startswith("https://"):
                return endereco
            if endereco.startswith("/") and not endereco.startswith("//"):
                return _ANFITRIAO_VENDUS + endereco
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


def subcategoria_da_reimportacao(existente: dict, categoria_id: str):
    """A subcategoria que o produto fica a ter depois de uma reimportação.

    Mantém-se a que lá estava — **excepto se o Vendus tiver mudado o produto de
    CATEGORIA**. Uma subcategoria é de uma categoria só (`Venda ao Público →
    Açaís`); com o produto a mudar de categoria, ela deixa de lhe pertencer, e
    um produto com a subcategoria de outra categoria não cabe em separador
    nenhum da grelha — desaparecia do ecrã com o artigo à venda na loja. Nesse
    caso limpa-se, e a importação diz-lhe qual foi (não se escolhe uma nova por
    ele: isso é uma decisão de quem arruma o balcão).

    Pura de propósito: é a única regra desta secção que se pode correr sem
    servidor nenhum, e é a que decide se o trabalho de alguém sobrevive."""
    subcategoria_id = existente.get("subcategoria_id")
    if not subcategoria_id:
        return None
    if existente.get("categoria_id") != categoria_id:
        return None
    return subcategoria_id


async def _sincronizar_categorias(
    db, categorias_vendus: List[dict]
) -> Tuple[Dict[str, str], List[str]]:
    """Cria as categorias do Vendus que ainda não existem localmente e
    devolve:
    - um mapa {id_da_categoria_no_vendus: id_local_da_categoria}, para ligar
      os produtos à categoria certa;
    - a lista de problemas encontrados (categorias sem id/nome, ignoradas).

    Casadas por `vendus_ref` — o ecrã deixa mudar o nome da categoria, por
    isso o nome não é uma chave estável (ver docstring do módulo). O nome
    só serve de reserva na PRIMEIRA ligação, para uma categoria criada à
    mão antes de existir `vendus_ref` (ou antes desta correcção) não ficar
    duplicada — encontrada por nome, o `vendus_ref` é gravado nela e passa
    a ser a chave a partir daí.

    NÃO toca em mais nada de uma categoria já ligada — `ordem`/`ativa`/
    `nome` são só nossas depois de gravadas (mesmo raciocínio de sempre:
    uma reimportação não pisa o que o dono arrumou aqui)."""
    existentes = await db[COLECOES["categorias"]].find({}, {"_id": 0}).to_list(500)
    por_ref = {c["vendus_ref"]: c for c in existentes if c.get("vendus_ref")}
    por_nome = {c["nome"]: c for c in existentes}
    ordem_seguinte = len(existentes)
    mapa: Dict[str, str] = {}
    problemas: List[str] = []

    for c in categorias_vendus:
        vid = str(c.get("id") or "").strip()
        nome = str(c.get("title") or c.get("name") or "").strip()
        if not vid or not nome:
            problemas.append("categoria do Vendus sem id/nome ignorada: %r" % (c,))
            continue

        existente = por_ref.get(vid)
        if existente is None:
            candidata = por_nome.get(nome)
            if candidata is not None and not candidata.get("vendus_ref"):
                existente = candidata

        if existente is not None:
            mapa[vid] = existente["id"]
            if not existente.get("vendus_ref"):
                await db[COLECOES["categorias"]].update_one(
                    {"id": existente["id"]}, {"$set": {"vendus_ref": vid}}
                )
                existente["vendus_ref"] = vid
                por_ref[vid] = existente
            continue

        try:
            dados = CategoriaEntrada(nome=nome, ordem=ordem_seguinte, ativa=True, vendus_ref=vid)
        except ValidationError as e:
            problemas.append("categoria '%s' recusada: %s" % (nome, e))
            continue
        nova = dados.model_dump()
        nova["id"] = str(uuid.uuid4())
        await db[COLECOES["categorias"]].insert_one(dict(nova))
        por_nome[nome] = nova
        por_ref[vid] = nova
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
    abortar a importação dos restantes.

    Sem correspondência por `vendus_ref`, procura-se por nome (+categoria)
    entre os produtos SEM `vendus_ref` — um produto criado à mão no
    backoffice (o ecrã vazio convida a isso: "Importe do Vendus ou crie o
    primeiro produto"). Se existir, LIGA-SE (grava-se o `vendus_ref` no que
    já lá está, preservando foto/grupos) em vez de criar um duplicado."""
    criados = 0
    atualizados = 0
    ligados = 0
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
        foto = _extrair_foto(p)

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
        ligado_agora = False
        if existente is None:
            # Sem correspondência pelo id do Vendus: talvez seja um produto
            # criado à mão (vendus_ref None/ausente) com o mesmo nome nesta
            # categoria — liga-se em vez de duplicar. `{"vendus_ref": None}`
            # casa tanto o campo a None como a sua ausência, tal como no
            # Mongo real.
            existente = await db[COLECOES["produtos"]].find_one(
                {"nome": nome, "categoria_id": categoria_id, "vendus_ref": None}, {"_id": 0}
            )
            if existente is not None:
                ligado_agora = True

        try:
            if existente is None:
                dados = ProdutoEntrada(
                    nome=nome, categoria_id=categoria_id, preco=preco, tax_id=tax_id,
                    foto_url=foto, vendus_ref=vid,
                )
                novo = dados.model_dump()
                novo["id"] = str(uuid.uuid4())
                novo["foto_origem"] = "vendus" if foto else None
                await db[COLECOES["produtos"]].insert_one(dict(novo))
                criados += 1
            else:
                # Reimportação (ou ligação por nome): nome/preço/tax_id/
                # categoria vêm do Vendus (é o que o dono mudou lá);
                # grupos_personalizacao/ativo são só nossos e têm de
                # sobreviver.
                #
                # **A FOTO deixou de ser "só nossa" e passou a ter uma regra
                # de precedência** — o dono pediu as duas coisas («pode pegar
                # as imagens do vendus» e «as que você não conseguir deixe no
                # backoffice a opção de fazer upload»), e as duas juntas
                # obrigam a decidir quem ganha. Quem AGIU aqui ganha a um
                # automatismo, e uma reimportação NUNCA apaga uma foto: o
                # quadro completo está em `fotos.foto_da_reimportacao`.
                foto_url, foto_origem = foto_da_reimportacao(existente, foto)
                # **A subcategoria é NOSSA e tem de sobreviver a isto.** O
                # `$set` abaixo grava o `ProdutoEntrada` INTEIRO por cima do
                # produto: um campo que não venha aqui é um campo apagado, e o
                # que se apagava era a arrumação da grelha do POS que alguém
                # fez à mão, sem um aviso em lado nenhum. Mesma razão da foto e
                # dos grupos de personalização, logo acima.
                subcategoria_id = subcategoria_da_reimportacao(existente, categoria_id)
                if existente.get("subcategoria_id") and not subcategoria_id:
                    problemas.append(
                        "\"%s\" mudou de categoria no Vendus e ficou sem "
                        "subcategoria — escolha-lhe uma nova, se quiser." % nome
                    )
                dados = ProdutoEntrada(
                    nome=nome, categoria_id=categoria_id, preco=preco, tax_id=tax_id,
                    subcategoria_id=subcategoria_id,
                    foto_url=foto_url,
                    grupos_personalizacao=existente.get("grupos_personalizacao") or [],
                    ativo=existente.get("ativo", True),
                    vendus_ref=vid,
                )
                await db[COLECOES["produtos"]].update_one(
                    {"id": existente["id"]},
                    {"$set": dict(dados.model_dump(), foto_origem=foto_origem)},
                )
                atualizados += 1
                if ligado_agora:
                    ligados += 1
                    problemas.append(
                        "'%s' (ref %s): ligado a produto existente criado à mão — "
                        "foto e grupos de personalização preservados" % (nome, vid)
                    )
        except ValidationError as e:
            problemas.append("'%s' (ref %s) recusado: %s" % (nome, vid, e))
            continue

    return {
        "lidos": len(produtos_vendus),
        "criados": criados,
        "atualizados": atualizados,
        "ligados": ligados,
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
        "produtos_ligados": resultado_produtos["ligados"],
        "problemas": problemas_categorias + resultado_produtos["problemas"],
    }
