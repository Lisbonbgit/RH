"""Catálogo e tipos de pagamento em LEITURA para o ecrã do POS (Plano 2C).

Existe porque o balcão e o backoffice não partilham autenticação: `GET
/categorias`, `GET /produtos`, `GET /grupos-personalizacao` (catalogo.py) e
`GET /tipos-pagamento` (pagamentos.py) dependem TODAS de `gestor_atual` — o
JWT de gestão que o POS, por desenho, nunca tem (ver o cabeçalho de
`frontend/src/lib/pos.js` e `faturacao/pos_auth.py`: o balcão só tem
X-Device-Token e X-Operator-Token). Sem estas duas rotas, a grelha de
produtos só carregava com a sessão de um gestor aberta na mesma aba —
exactamente o que a Task 2 do Plano 2A proibiu ao separar os dois
mecanismos.

Nada aqui escreve, e nada aqui reimplementa uma regra: o que torna um
produto vendável é `precos.erros_do_produto`, a MESMA função do ecrã
"Produtos sem IVA" do backoffice e de `venda.py::juntar_linha`.

O fio condutor das duas rotas: **nada desaparece do ecrã em silêncio**. Um
produto sem IVA e um tipo de pagamento ainda por mapear ao Vendus vêm na
resposta, marcados e com a razão à vista, em vez de serem filtrados fora.
Um botão que não existe não se explica a si próprio — a operadora ficava a
olhar para uma grelha onde "falta um artigo" sem ter o que dizer ao gestor.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends

from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import erros_do_produto

router = APIRouter()

# Os mesmos tectos que catalogo.py e pagamentos.py já usam nas rotas de
# gestão — não são números novos. O POS lê exactamente o mesmo catálogo que
# o backoffice: dois limites diferentes para a mesma colecção davam um ecrã
# a mostrar mais (ou menos) artigos do que a lista onde eles se gerem.
LIMITE_PRODUTOS = 2000
LIMITE_CATEGORIAS = 200
LIMITE_GRUPOS = 200
LIMITE_TIPOS_PAGAMENTO = 100


def _categoria_publica(categoria: Dict) -> Dict:
    """Só os campos que os separadores do topo usam.

    Dicionário construído campo a campo, nunca o documento cru — é isto, e
    não a projecção do find, que garante que nenhum `_id` do Mongo (que nem
    sequer é serializável em JSON) sai daqui: a projecção só funciona
    enquanto todos os finds estiverem escritos certos, o dicionário explícito
    não depende de nada. Vale para os três blocos da resposta.
    """
    return {
        "id": categoria["id"],
        "nome": categoria.get("nome"),
        "ordem": categoria.get("ordem", 0),
    }


def _produto_publico(produto: Dict) -> Dict:
    """O produto como a grelha o vê, incluindo o que o impede de ser vendido.

    `vendavel`/`erros` saem de `precos.erros_do_produto` e não de uma
    verificação escrita aqui: é a mesma função que alimenta o ecrã "Produtos
    sem IVA" do backoffice e que `venda.py::juntar_linha` usa para recusar a
    linha com 422. Uma segunda cópia da regra acabava, mais dia menos dia, a
    desenhar como vendável um artigo que a venda recusa — e a operadora
    descobria-o ao tocar-lhe, com o cliente à frente.

    Um produto mal configurado NÃO é escondido da grelha, de propósito.
    Escondê-lo fá-lo-ia desaparecer sem ninguém perceber porquê: tocar nele
    nunca chegaria a acontecer, mas também ninguém ficava a saber que ele
    existia e estava mal — nem a operadora, nem o gestor a quem ela tem de o
    dizer. Vem morto e com a razão escrita ("Sem IVA definido"), que é
    precisamente a frase que ela repete a quem o pode corrigir.
    """
    erros = erros_do_produto(produto)
    return {
        "id": produto["id"],
        "nome": produto.get("nome"),
        "categoria_id": produto.get("categoria_id"),
        "preco": produto.get("preco"),
        "tax_id": produto.get("tax_id"),
        "foto_url": produto.get("foto_url"),
        # Ids dos grupos tal como estão gravados no produto — o ecrã casa-os
        # com `grupos_personalizacao` da resposta. Um id que lá não apareça é
        # um grupo entretanto desactivado, e o ecrã fica sem essas
        # personalizações para oferecer. Isso NÃO é acrescentado a `erros`:
        # `erros_do_produto` é a única fonte dessa lista, e uma regra escrita
        # aqui era já a segunda cópia que este módulo existe para evitar.
        "grupos_personalizacao": produto.get("grupos_personalizacao") or [],
        "vendavel": not erros,
        "erros": erros,
    }


def _grupo_publico(grupo: Dict) -> Dict:
    """O grupo de personalização com as opções desactivadas já de fora.

    `min_select`/`max_select` vão como estão, sem serem "acertados" ao
    número de opções que sobrou. Consequência real e deliberada: um grupo
    com `min_select=1` cujas opções foram TODAS desactivadas fica impossível
    de satisfazer, e o ecrã tem de conseguir dizê-lo. Baixar aqui o
    `min_select` seria o servidor a inventar uma configuração que o gestor
    não fez — o grupo passava a parecer bem e o açaí saía sem o topping que
    alguém quis exigir. Quem está mal é o catálogo; corrige-se no
    backoffice, não em silêncio a caminho do balcão.
    """
    opcoes = [o for o in (grupo.get("opcoes") or []) if o.get("ativa", True)]
    return {
        "id": grupo["id"],
        "nome": grupo.get("nome"),
        "min_select": grupo.get("min_select", 0),
        "max_select": grupo.get("max_select", 0),
        "opcoes": [
            {"id": o.get("id"), "nome": o.get("nome"), "preco": o.get("preco", 0)}
            for o in opcoes
        ],
    }


@router.get("/pos/catalogo")
async def catalogo_do_pos(_: Dict = Depends(operador_atual)) -> dict:
    """Tudo o que a grelha precisa, num só pedido.

    Um pedido e não três: isto é o arranque do ecrã, com fila à frente, e
    três idas ao servidor davam uma grelha a montar-se aos bocados (os
    separadores antes dos produtos, os produtos antes das personalizações).

    Só o que está activo. O filtro vai dentro do próprio `find`, e não numa
    lista por compreensão a seguir, porque o tecto do `to_list` conta
    documentos LIDOS: com o catálogo cheio de artigos desactivados de anos
    anteriores, filtrar depois deixava artigos ACTIVOS de fora do limite sem
    nada a avisar.

    Cuidado com o género do campo: a categoria tem `ativa` (ver
    `catalogo.py::CategoriaEntrada`), o produto e o grupo têm `ativo`.
    Trocar um pelo outro não dá erro nenhum — dá uma lista vazia, porque
    nenhum documento casa com um campo que não existe.
    """
    db = obter_db()

    categorias = await (
        db[COLECOES["categorias"]]
        .find({"ativa": True}, {"_id": 0})
        .sort("ordem", 1)
        .to_list(LIMITE_CATEGORIAS)
    )
    # Por nome, como no backoffice: a grelha do balcão pagina, e uma ordem
    # estável é o que permite à operadora saber que o Açaí Grande está
    # sempre no mesmo sítio.
    produtos = await (
        db[COLECOES["produtos"]]
        .find({"ativo": True}, {"_id": 0})
        .sort("nome", 1)
        .to_list(LIMITE_PRODUTOS)
    )
    grupos = await (
        db[COLECOES["grupos_personalizacao"]]
        .find({"ativo": True}, {"_id": 0})
        .sort("nome", 1)
        .to_list(LIMITE_GRUPOS)
    )

    return {
        "categorias": [_categoria_publica(c) for c in categorias],
        "produtos": [_produto_publico(p) for p in produtos],
        "grupos_personalizacao": [_grupo_publico(g) for g in grupos],
    }


@router.get("/pos/tipos-pagamento")
async def tipos_pagamento_do_pos(_: Dict = Depends(operador_atual)) -> List[dict]:
    """Os botões de pagamento do ecrã de finalizar.

    `pronto` é o que impede a pior versão deste ecrã: `fiscal.py::finalizar`
    recusa com 422 um tipo de pagamento sem `vendus_payment_method_id`, e
    sem este sinalizador a operadora escolhia "Glovo", carregava em EMITIR
    À FRENTE DO CLIENTE, e só aí descobria que o tipo nunca tinha sido
    mapeado. Com ele, o botão continua lá — mesmo raciocínio do `vendavel`
    dos produtos: um tipo que desaparece não se explica a si próprio — mas
    inutilizável e com a razão à vista.

    O `vendus_payment_method_id` em si NUNCA sai daqui, só o booleano que
    diz se existe: é configuração interna da ligação ao Vendus e o ecrã do
    balcão não tem nada que a ver — nem para a mostrar, nem para a devolver
    de volta em algum sítio.

    `da_troco` é o que faz o ecrã de finalizar mostrar (ou esconder) o campo
    do valor recebido e o troco — não se calcula troco de um Multibanco.
    """
    db = obter_db()
    tipos = await (
        db[COLECOES["tipos_pagamento"]]
        .find({"ativo": True}, {"_id": 0})
        .sort("ordem", 1)
        .to_list(LIMITE_TIPOS_PAGAMENTO)
    )
    return [
        {
            "id": t["id"],
            "nome": t.get("nome"),
            "tipo_fiscal": t.get("tipo_fiscal"),
            "da_troco": bool(t.get("da_troco")),
            "ordem": t.get("ordem", 0),
            "pronto": bool(t.get("vendus_payment_method_id")),
        }
        for t in tipos
    ]
