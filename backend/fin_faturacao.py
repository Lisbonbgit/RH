"""**A faturação do nosso POS a entrar no Financeiro, loja a loja.**

Desde que o módulo de faturação entrou nas cinco lojas da L'Açaí (27/08/2026),
**todas as Faturas Simplificadas saem pela mesma caixa API do Vendus** — e, do
lado do Vendus, essa caixa pertence a UMA loja só ("Faturação Fordaimon
Foods"). O sync do Vendus casa lojas com unidades **pelo nome**, não encontrava
unidade nenhuma com esse nome, e saltava-a: a partir de 30/08 as vendas da
L'Açaí deixaram de entrar no `fin_sales`, com o painel a mostrar menos dinheiro
e nenhum erro (a queixa ia só para o log do cron).

Este módulo resolve isso pela raiz: **o dinheiro passa a vir de onde ele
nasce**, o nosso `fat_documentos`, que sabe a loja de cada documento — coisa
que o Vendus, com uma caixa só, não tem como saber. Medido contra a API real
em 2026-09-06, quatro dias seguidos, **diferença de 0,00 € em todos**.

## As regras da soma (as mesmas dos dois lados, senão nada bate)

- **anulados fora** (`anulado`);
- **notas de crédito com sinal negativo** — vivem na mesma colecção com
  `tipo: "NC"` e total POSITIVO; somá-las sem olhar ao tipo transforma uma
  devolução de 24,90 € num acréscimo de 24,90 €, um erro do dobro;
- **`modo: "tests"` fora** — documento de ensaio não é dinheiro. Mas
  **`modo` a `None` CONTA**: é o que fica nos documentos recuperados pela
  verificação ou pela reconciliação, e filtrar por `== "normal"` apagava
  receita real;
- **o dia é o de LISBOA**, não o de UTC. `emitido_em` é ISO em UTC; uma venda
  das 00:30 de Lisboa no Verão é ainda 23:30 do dia anterior em UTC, e cortar
  o dia sem converter punha-a no dia errado — todos os dias, na hora a que as
  lojas fecham.

## A armadilha que este ficheiro tem de continuar a evitar

`fin_sales` é somado por quem lê **sem filtrar `source`**. Estas linhas entram
com `source: "faturacao"` e as do sync do Vendus com `source: "vendus"`, e as
duas somam-se. **Nos dias 27–29/08 isso é o que se quer** — nesses três dias
umas lojas ainda faturavam pelo POS do Vendus e outras já pelo nosso, são
documentos diferentes de lojas diferentes. De 30/08 em diante o Vendus não tem
nada nestas lojas, por isso não há nada para duplicar.

**O que NÃO se pode fazer nunca é criar uma unidade no Financeiro com o nome
da loja da caixa única ("Faturação Fordaimon Foods").** Nesse dia o sync do
Vendus passaria a gravar por essa unidade o total das cinco lojas, ao lado do
que este módulo já grava por loja — e o painel mostrava **o dobro** da
faturação da L'Açaí, com um número perfeitamente credível.

## O que este módulo NÃO traz, e é preciso saber

**O custo (CMV) não vem daqui.** O `fat_documentos` não guarda as linhas dos
artigos, e o custo que o sync do Vendus calculava lia o custo de cada produto
documento a documento. As linhas escritas aqui levam `amount_cost` a `None` —
não a zero — para o DRE não passar a mostrar uma margem de 100% como se fosse
um facto apurado.
"""
import logging
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from faturacao.periodos import LISBON_TZ

logger = logging.getLogger(__name__)

# A origem destas linhas em `fin_sales`. É por ela que a gravação é
# idempotente sem tocar no que o Vendus ou o lançamento manual escreveram.
FONTE = "faturacao"

# O documento de ensaio do Vendus parece uma fatura e não é nenhuma.
MODO_DE_ENSAIO = "tests"


def _sem_acentos(texto) -> str:
    """Para casar "L'açaí Belém" com "L'açaí Belem" — que é a diferença real
    entre o nome no nosso módulo e o nome no Vendus."""
    cru = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in cru if unicodedata.category(c) != "Mn").strip().lower()


def dia_de_lisboa(emitido_em) -> Optional[str]:
    """O dia (YYYY-MM-DD) a que esta venda pertence, no relógio de Lisboa.

    Devolve `None` quando não se consegue ler a data — e quem chama trata
    isso como documento por classificar, nunca o atira para o dia de hoje.
    """
    if not emitido_em:
        return None
    if isinstance(emitido_em, datetime):
        d = emitido_em
    else:
        try:
            d = datetime.fromisoformat(str(emitido_em).replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(LISBON_TZ).strftime("%Y-%m-%d")


def sinal_do_documento(doc: Dict) -> int:
    """−1 numa nota de crédito, +1 no resto."""
    return -1 if str(doc.get("tipo") or "").strip().upper() == "NC" else 1


def agregar(documentos: List[Dict]) -> Dict:
    """Soma os documentos por (loja, dia). Puro: sem Mongo, sem rede.

    Devolve `{(loja_id, dia): {"bruto", "liquido", "docs", "liquido_completo"}}`
    mais uma lista de queixas, porque nada aqui desaparece em silêncio.

    `liquido_completo` é falso assim que UM documento do dia não trouxer
    `total_liquido`. Nesse caso o valor sem IVA do dia não se escreve de todo,
    em vez de se escrever a soma dos outros: um líquido a que falta uma parte
    é menor do que a verdade, e é dele que sai a taxa de IVA implícita e o
    relatório do IVA. Menos informação é honesto; informação errada não é.
    """
    baldes: Dict = {}
    queixas: List[str] = []

    for doc in documentos:
        if doc.get("anulado"):
            continue
        if doc.get("modo") == MODO_DE_ENSAIO:
            continue

        dia = dia_de_lisboa(doc.get("emitido_em"))
        if not dia:
            queixas.append(
                "documento %s sem data legível (`emitido_em`) — não foi somado"
                % (doc.get("numero") or doc.get("id"))
            )
            continue

        loja_id = doc.get("loja_id")
        if not loja_id:
            queixas.append(
                "documento %s sem loja — não foi somado"
                % (doc.get("numero") or doc.get("id"))
            )
            continue

        bruto = doc.get("total_bruto")
        if bruto is None:
            queixas.append(
                "documento %s sem `total_bruto` — não foi somado"
                % (doc.get("numero") or doc.get("id"))
            )
            continue

        sinal = sinal_do_documento(doc)
        balde = baldes.setdefault(
            (loja_id, dia),
            {"bruto": 0.0, "liquido": 0.0, "docs": 0, "liquido_completo": True},
        )
        balde["bruto"] += sinal * float(bruto)
        balde["docs"] += 1

        liquido = doc.get("total_liquido")
        if liquido is None:
            balde["liquido_completo"] = False
        else:
            balde["liquido"] += sinal * float(liquido)

    return {"baldes": baldes, "queixas": queixas}


def taxa_implicita(bruto: float, liquido: Optional[float]) -> Optional[float]:
    """A taxa de IVA implícita do dia — a MESMA conta que o sync do Vendus
    faz (`(g/n − 1) × 100`), para as linhas das duas origens serem lidas da
    mesma maneira pelos relatórios que já existem.

    **Não é uma taxa do CIVA e não se deve ler como tal**: é a média do dia
    de uma loja que vende a 13% e a 23%. O que está certo é o imposto
    liquidado (`amount − amount_net`); a decomposição por taxa precisa das
    linhas dos artigos, que este caminho não tem.
    """
    if not liquido or liquido <= 0:
        return None
    return round((bruto / liquido - 1) * 100, 2)


def linhas_para_fin_sales(baldes: Dict, unidades_por_loja: Dict, agora: str) -> List[Dict]:
    """Transforma os baldes em linhas de `fin_sales`, com a MESMA forma das
    que o sync do Vendus escreve — é isso que faz o painel, o DRE e os
    relatórios funcionarem sem uma linha nova do lado deles.

    Um dia cujo total dê exactamente 0,00 € não gera linha, pela mesma regra
    do outro escritor: um dia sem vendas não é uma venda de zero euros. (Um
    dia em que as devoluções anulem as vendas cai aqui também — e é o certo:
    o líquido do dia foi mesmo zero.)
    """
    linhas = []
    for (loja_id, dia), balde in sorted(baldes.items()):
        unidade = unidades_por_loja.get(loja_id)
        if not unidade:
            continue  # quem chama já se queixou desta loja
        bruto = round(balde["bruto"], 2)
        if bruto == 0:
            continue
        liquido = round(balde["liquido"], 2) if balde["liquido_completo"] else None
        linhas.append({
            "id": str(uuid.uuid4()),
            "company_id": unidade["company_id"],
            "unit_id": unidade["id"],
            "date": dia,
            "amount": bruto,
            "amount_net": liquido,
            # O custo NÃO vem daqui (ver o cabeçalho). `None` e não `0.0`:
            # um zero seria lido como "custo apurado, deu zero" e punha o DRE
            # a mostrar 100% de margem como se fosse um facto.
            "amount_cost": None,
            "net_nocost": 0.0,
            "vat_rate": taxa_implicita(bruto, liquido),
            "note": unidade.get("nome_da_loja"),
            "source": FONTE,
            "created_by": None,
            "created_at": agora,
        })
    return linhas


async def _unidades_por_loja(db) -> Dict:
    """Casa cada loja do módulo de faturação com a unidade do Financeiro que
    tem o mesmo nome, e devolve também as que não casaram.

    Pelo NOME, e não por um campo de ligação, porque é o que existe hoje: o
    `fat_lojas.empresa_id` é opcional e está por preencher, e o formulário do
    backoffice nem mostra o campo. A empresa vem da UNIDADE que casou — assim
    não há nenhum NIF escrito à mão neste ficheiro.
    """
    lojas = await db.fat_lojas.find({}, {"_id": 0, "id": 1, "nome": 1}).to_list(500)
    unidades = await db.fin_units.find(
        {}, {"_id": 0, "id": 1, "name": 1, "company_id": 1}
    ).to_list(2000)

    por_nome: Dict[str, List[Dict]] = {}
    for u in unidades:
        por_nome.setdefault(_sem_acentos(u.get("name")), []).append(u)

    mapa, nomes, queixas = {}, {}, []
    for loja in lojas:
        nomes[loja["id"]] = loja.get("nome")
        candidatas = por_nome.get(_sem_acentos(loja.get("nome")), [])
        if len(candidatas) == 1:
            mapa[loja["id"]] = {
                "id": candidatas[0]["id"],
                "company_id": candidatas[0]["company_id"],
                "nome_da_loja": loja.get("nome"),
            }
        elif len(candidatas) > 1:
            # Duas unidades com o mesmo nome: escolher uma à sorte era pôr o
            # dinheiro de uma loja na outra, e ninguém daria por isso.
            queixas.append(
                "a loja '%s' casa com %d unidades do Financeiro — ambígua, não "
                "foi gravada." % (loja.get("nome"), len(candidatas))
            )
        # Uma loja SEM unidade não se queixa aqui: só interessa quando tem
        # dinheiro no intervalo, e aí a queixa diz quanto (ver `sincronizar`).
        # Queixar-se sempre enchia o registo de ruído por lojas que nunca
        # venderam — e um aviso que aparece todos os dias deixa de se ler.
    return mapa, nomes, queixas


async def sincronizar(db, desde: str, ate: str) -> Dict:
    """Lê `fat_documentos` no intervalo [desde, ate] (dias de Lisboa) e grava
    o resultado em `fin_sales` com `source: "faturacao"`.

    **A gravação é idempotente e cirúrgica**: apaga só as linhas desta
    ORIGEM, desta empresa/unidade e destes dias, e insere as novas. Nunca
    toca no que o Vendus escreveu (`source: "vendus"`) nem no lançamento
    manual — é isso que faz os dias 27–29/08, em que as duas origens são
    complementares, continuarem certos.

    A janela de leitura em UTC é propositadamente MAIS LARGA do que os dias
    pedidos (um dia para cada lado) e o corte fino é feito a seguir, pelo dia
    de Lisboa: um documento das 23:30 UTC pertence já ao dia seguinte em
    Lisboa, e uma janela justa deixava-o de fora do dia a que pertence.
    """
    mapa, nomes, queixas = await _unidades_por_loja(db)

    inicio_utc = "%sT00:00:00" % _dia_antes(desde)
    fim_utc = "%sT23:59:59.999999+00:00" % _dia_depois(ate)
    documentos = await db.fat_documentos.find(
        {"emitido_em": {"$gte": inicio_utc, "$lte": fim_utc}},
        {"_id": 0, "id": 1, "numero": 1, "tipo": 1, "modo": 1, "anulado": 1,
         "total_bruto": 1, "total_liquido": 1, "loja_id": 1, "emitido_em": 1},
    ).to_list(200000)

    agregado = agregar(documentos)
    queixas.extend(agregado["queixas"])

    # Fora da janela pedida (os documentos do dia a mais que se leu de
    # propósito) não se grava — mas leram-se para o corte de Lisboa ser
    # exacto nas pontas.
    baldes = {
        chave: balde for chave, balde in agregado["baldes"].items()
        if desde <= chave[1] <= ate
    }
    # Uma loja com dinheiro no intervalo e sem unidade no Financeiro não pode
    # passar por um aviso genérico: diz-se QUANTO é que não está a entrar. É
    # esta frase que teria poupado a semana em que a faturação da L'Açaí ficou
    # de fora — a queixa existia, mas não dizia que eram mil e quinhentos euros
    # por dia.
    sem_unidade = {}
    for (loja_id, _dia), balde in baldes.items():
        if loja_id in mapa:
            continue
        sem_unidade[loja_id] = round(sem_unidade.get(loja_id, 0.0) + balde["bruto"], 2)
    for loja_id, valor in sorted(sem_unidade.items(), key=lambda x: -x[1]):
        queixas.append(
            "a loja '%s' tem %.2f EUR neste intervalo e NÃO entrou: não há "
            "unidade no Financeiro com este nome." % (nomes.get(loja_id, loja_id), valor)
        )

    agora = datetime.now(timezone.utc).isoformat()
    linhas = linhas_para_fin_sales(baldes, mapa, agora)

    # Uma passagem por unidade: apaga o intervalo desta origem e insere.
    por_unidade: Dict = {}
    for linha in linhas:
        por_unidade.setdefault((linha["company_id"], linha["unit_id"]), []).append(linha)

    # As unidades que TINHAM linhas nossas neste intervalo e agora não têm
    # nenhuma também têm de ser limpas — senão uma venda anulada ficava lá
    # para sempre.
    conhecidas = {(u["company_id"], u["id"]) for u in mapa.values()}
    escritas = 0
    for chave in conhecidas:
        company_id, unit_id = chave
        await db.fin_sales.delete_many({
            "source": FONTE,
            "company_id": company_id,
            "unit_id": unit_id,
            "date": {"$gte": desde, "$lte": ate},
        })
        novas = por_unidade.get(chave) or []
        if novas:
            await db.fin_sales.insert_many(novas)
            escritas += len(novas)

    total = round(sum(l["amount"] for l in linhas), 2)
    logger.info(
        "[fin-faturacao] %s..%s: %d linha(s), %.2f EUR, %d queixa(s)",
        desde, ate, escritas, total, len(queixas),
    )
    return {
        "since": desde,
        "until": ate,
        "written": escritas,
        "total": total,
        "documentos": len(documentos),
        "errors": queixas,
    }


def _dia_antes(dia: str) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(dia) - timedelta(days=1)
    return d.isoformat()


def _dia_depois(dia: str) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(dia) + timedelta(days=1)
    return d.isoformat()
