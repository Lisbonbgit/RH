"""**Os números do relatório diário** — aritmética pura, sem Mongo e sem email.

O dono quer, todos os dias às 23:30, saber o que as lojas fizeram sem ter de
abrir o portal: a faturação geral e por loja, quanto está em cada caixa e no
caixa geral, o artigo mais vendido partido pelos tamanhos, e os tipos de
pagamento por loja e no total.

**A regra que este módulo não pode quebrar: não há somas novas aqui.**

- a faturação sai de `dashboard._valor_documento` — a mesma que o Dashboard
  usa, com a nota de crédito a subtrair e o documento anulado a não contar;
- o caixa e os pagamentos saem de `caixa._resumo_do_turno` — a MESMA função
  que serve o Ponto de Caixa e o Z.

São funções privadas de outros módulos e importam-se assim de propósito. A
alternativa era reescrever as somas aqui, e uma terceira contabilidade sobre a
mesma gaveta é a maneira mais certa de um dia o email e o Z discordarem — com
o dono sem forma de saber qual deles mente. Vale mais o acoplamento explícito
do que duas verdades.

Não lê base de dados e não envia nada: recebe listas e devolve um dicionário.
É isso que deixa as contas de dinheiro ser testadas sem email nenhum, e o
desenho do email ser visto sem inventar vendas.
"""
import unicodedata
from typing import Dict, List, Optional

from .caixa import _resumo_do_turno
from .caixa_math import _centimos
from .dashboard import _campo_valor, _valor_documento

# **Que personalização é que parte um artigo em dois.** O dono criou UM artigo
# "Açaí" e pôs-lhe dentro os tamanhos (mini, small, regular, supreme); um
# "Nutella 2×" é um extra e não uma variante — parti-lo por aí dava um top com
# uma linha por combinação, ilegível e falso.
#
# ponytail: heurística pelo NOME do grupo, porque não há no catálogo nenhum
# campo que diga "este grupo define a variante". Comparação sem acentos e sem
# maiúsculas, e por conter e não por igualar, para apanhar "Tamanho",
# "Tamanhos" e "Tamanho do açaí". Upgrade: um interruptor por grupo no
# backoffice ("este grupo é uma variante") no dia em que um grupo de variante
# não se chamar tamanho — `grupos_de_variante` já entra por parâmetro para
# esse dia não obrigar a mexer aqui.
_PALAVRAS_DE_VARIANTE = ("tamanho", "size")


def _sem_acentos(texto) -> str:
    normalizado = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def _e_grupo_de_variante(grupo_nome, grupos_de_variante: Optional[List[str]]) -> bool:
    nome = _sem_acentos(grupo_nome)
    if not nome:
        return False
    if grupos_de_variante is not None:
        return any(_sem_acentos(g) == nome for g in grupos_de_variante)
    return any(palavra in nome for palavra in _PALAVRAS_DE_VARIANTE)


def _dia_do_documento(doc: Dict) -> str:
    """O dia em que o documento foi emitido, no fuso em que foi gravado.

    `emitido_em` é uma string ISO ("2026-08-26T14:30:00+01:00") e os primeiros
    dez caracteres são a data local — que é o que interessa: o dia de uma loja
    de Alfragide é o dia de Alfragide, não o dia UTC. Cortar a string em vez de
    a descodificar evita reconstruir um `datetime` só para lhe pedir a data de
    volta, e um valor estranho dá "" (não casa com dia nenhum) em vez de
    rebentar o relatório inteiro por causa de um documento.
    """
    return str(doc.get("emitido_em") or "")[:10]


def _soma_documentos(documentos: List[Dict], campo: str) -> float:
    """Em cêntimos inteiros e só a euros no fim.

    `0.29 + 1.15 + 10.20` em vírgula flutuante dá 11.639999999999999, e um dia
    de cinco lojas tem centenas de documentos — o resto aparecia no email.
    Mesmo cuidado de `caixa_math.por_tipo_de_pagamento`.
    """
    total = sum(_centimos(_valor_documento(d, campo)) for d in documentos)
    return round(total / 100.0, 2)


def _variacao(hoje: float, ontem: float) -> Optional[float]:
    """`None`, e não zero, quando não há ontem com que comparar: "0%" no email
    lia-se "igual a ontem", que é falso."""
    if not ontem:
        return None
    return round(((hoje - ontem) / abs(ontem)) * 100.0, 2)


def _junta_pagamentos(listas: List[List[Dict]]) -> List[Dict]:
    """As linhas de pagamento de várias lojas somadas por TIPO.

    Um "Multibanco" de Alfragide e outro de Oeiras são a mesma linha no total —
    é essa a pergunta do dono: quanto entrou por cada meio, na empresa. A chave
    é o `tipo_pagamento_id` com o nome como recurso, exactamente como em
    `caixa_math.por_tipo_de_pagamento`: um pagamento sem id não pode
    desaparecer da conta, porque dinheiro que se cala é o pior desfecho.
    """
    linhas: Dict = {}
    for lista in listas:
        for p in lista or []:
            chave = p.get("tipo_pagamento_id") or p.get("nome")
            linha = linhas.get(chave)
            if linha is None:
                linha = linhas[chave] = {
                    "tipo_pagamento_id": p.get("tipo_pagamento_id"),
                    "nome": p.get("nome"),
                    "centimos": 0,
                    "quantos": 0,
                }
            # Cêntimos por hábito da casa, e não por necessidade medida: o
            # que chega aqui já vem arredondado a 2 casas por
            # `por_tipo_de_pagamento`, e o `round` do fim taparia o ruído de
            # qualquer maneira — tentei mutar isto para vírgula flutuante e
            # NENHUM teste ficou vermelho, porque o defeito não é observável
            # por esta porta. Fica porque custa zero e porque no dia em que
            # alguém chamar isto com valores em cru (um `total` em texto vindo
            # de uma reconciliação) é a diferença entre somar e rebentar.
            linha["centimos"] += _centimos(p.get("total"))
            linha["quantos"] += p.get("quantos") or 0
    saida = [
        {
            "tipo_pagamento_id": l["tipo_pagamento_id"],
            "nome": l["nome"],
            "total": round(l["centimos"] / 100.0, 2),
            "quantos": l["quantos"],
        }
        for l in linhas.values()
    ]
    # Do que mais entrou para o que menos, com o nome a desempatar — a mesma
    # ordem determinística do Z, para duas leituras não trocarem as linhas.
    saida.sort(key=lambda l: (-l["total"], l["nome"] or ""))
    return saida


def _caixa_das_sessoes(turnos: List[Dict]) -> Dict:
    """O esperado, o contado e a diferença de um conjunto de turnos.

    **O contado só soma os turnos FECHADOS**, e diz-se quantos ficaram por
    fechar. Somar o contado de um turno aberto (que ninguém contou) com o de um
    fechado dava um número que não é o de lado nenhum — e a diferença
    resultante mandava alguém procurar uma falta que não existe.
    """
    if not turnos:
        return {"estado": "sem_turno", "esperado": None, "contado": None,
                "diferenca": None, "turnos_abertos": 0}

    esperado_c = 0
    contado_c = 0
    abertos = 0
    algum_fechado = False
    for t in turnos:
        resumo = _resumo_do_turno(
            t["sessao"], t.get("movimentos") or [], t.get("vendas") or [],
            t.get("notas_credito") or [])
        esperado_c += _centimos(resumo["esperado"])
        if t["sessao"].get("estado") == "aberta":
            abertos += 1
        else:
            algum_fechado = True
            contado_c += _centimos(t["sessao"].get("contado"))

    esperado_v = round(esperado_c / 100.0, 2)
    if not algum_fechado:
        return {"estado": "aberto", "esperado": esperado_v, "contado": None,
                "diferenca": None, "turnos_abertos": abertos}
    contado_v = round(contado_c / 100.0, 2)
    return {
        # "aberto" ganha a "fechado" quando há dos dois: o que o leitor precisa
        # de saber é que ALGUMA coisa ficou por fechar, não que o resto fechou.
        "estado": "aberto" if abertos else "fechado",
        "esperado": esperado_v,
        "contado": contado_v,
        # A diferença compara o contado com o esperado DOS TURNOS CONTADOS —
        # nunca com o esperado total, que inclui gavetas que ninguém contou.
        "diferenca": round(
            (contado_c - sum(
                _centimos(_resumo_do_turno(
                    t["sessao"], t.get("movimentos") or [], t.get("vendas") or [],
                    t.get("notas_credito") or [])["esperado"])
                for t in turnos if t["sessao"].get("estado") != "aberta")) / 100.0, 2),
        "turnos_abertos": abertos,
    }


def _artigos_vendidos(turnos: List[Dict], grupos_de_variante) -> List[Dict]:
    """O top de artigos, com a repartição por tamanho por baixo de cada um.

    Só as vendas EMITIDAS, pela mesma regra de `por_tipo_de_pagamento`: uma
    conta ainda aberta no balcão não vendeu nada a ninguém.
    """
    artigos: Dict = {}
    for turno in turnos:
        for venda in turno.get("vendas") or []:
            if venda.get("estado") != "emitida":
                continue
            for linha in venda.get("linhas") or []:
                nome = linha.get("produto_nome") or "(sem nome)"
                quantidade = int(linha.get("quantidade") or 0)
                artigo = artigos.get(nome)
                if artigo is None:
                    artigo = artigos[nome] = {
                        "nome": nome, "quantidade": 0, "variantes": {}}
                artigo["quantidade"] += quantidade
                for opcao in linha.get("opcoes") or []:
                    if not _e_grupo_de_variante(opcao.get("grupo_nome"), grupos_de_variante):
                        continue
                    v = opcao.get("nome") or "(sem nome)"
                    artigo["variantes"][v] = artigo["variantes"].get(v, 0) + quantidade

    saida = []
    for artigo in artigos.values():
        variantes = [{"nome": n, "quantidade": q} for n, q in artigo["variantes"].items()]
        variantes.sort(key=lambda v: (-v["quantidade"], v["nome"]))
        saida.append({
            "nome": artigo["nome"],
            "quantidade": artigo["quantidade"],
            "variantes": variantes,
        })
    saida.sort(key=lambda a: (-a["quantidade"], a["nome"]))
    return saida


def montar_relatorio(
    *,
    dia: str,
    ate: str,
    lojas: List[Dict],
    documentos: List[Dict],
    turnos: List[Dict],
    com_iva: bool = True,
    grupos_de_variante: Optional[List[str]] = None,
) -> Dict:
    """Os números do dia, prontos a desenhar.

    `documentos` traz os dos ÚLTIMOS DIAS (não só os de hoje): o de hoje sai
    daqui, o de ontem serve a comparação, e o resto desenha as colunas. Um só
    parâmetro em vez de três listas evita que quem chama consiga passar um
    "hoje" e um "ontem" que não são dias seguidos.

    `turnos` são as sessões de caixa do dia, cada uma com o que
    `_resumo_do_turno` precisa: `{sessao, movimentos, vendas, notas_credito}`.
    """
    campo = _campo_valor(com_iva)
    dias = sorted({_dia_do_documento(d) for d in documentos if _dia_do_documento(d)})
    docs_de_hoje = [d for d in documentos if _dia_do_documento(d) == dia]
    # Ontem é o dia ANTERIOR COM DADOS, e não `dia - 1` no calendário: uma
    # segunda-feira a seguir a um domingo fechado comparava-se contra zero e
    # dizia "+100%" todas as semanas.
    anteriores = [d for d in dias if d < dia]
    dia_de_ontem = anteriores[-1] if anteriores else None
    docs_de_ontem = [d for d in documentos if _dia_do_documento(d) == dia_de_ontem] \
        if dia_de_ontem else []

    faturacao = _soma_documentos(docs_de_hoje, campo)
    faturacao_ontem = _soma_documentos(docs_de_ontem, campo)

    turnos_por_loja: Dict = {}
    for t in turnos:
        turnos_por_loja.setdefault(t["sessao"].get("loja_id"), []).append(t)

    linhas_de_loja = []
    for loja in lojas:
        docs = [d for d in docs_de_hoje if d.get("loja_id") == loja["id"]]
        da_loja = turnos_por_loja.get(loja["id"], [])
        pagamentos = _junta_pagamentos([
            _resumo_do_turno(t["sessao"], t.get("movimentos") or [],
                             t.get("vendas") or [], t.get("notas_credito") or [])["pagamentos"]
            for t in da_loja])
        total = _soma_documentos(docs, campo)
        linhas_de_loja.append({
            "id": loja["id"],
            "nome": loja.get("nome") or loja["id"],
            "faturacao": total,
            "documentos": len(docs),
            # Uma loja que desaparecia do relatório lia-se como "não existe" em
            # vez de "não vendeu" — e é precisamente a que o dono quer ver.
            "sem_vendas": not docs,
            "caixa": _caixa_das_sessoes(da_loja),
            "pagamentos": pagamentos,
        })
    linhas_de_loja.sort(key=lambda l: (-l["faturacao"], l["nome"]))

    return {
        "dia": dia,
        "ate": ate,
        "com_iva": com_iva,
        "ha_vendas": bool(docs_de_hoje),
        "geral": {
            "faturacao": faturacao,
            "faturacao_ontem": faturacao_ontem,
            "dia_de_ontem": dia_de_ontem,
            "variacao": _variacao(faturacao, faturacao_ontem),
            "documentos": len(docs_de_hoje),
            "caixa": _caixa_das_sessoes(turnos),
            "pagamentos": _junta_pagamentos([l["pagamentos"] for l in linhas_de_loja]),
        },
        "serie": [
            {"data": d, "valor": _soma_documentos(
                [x for x in documentos if _dia_do_documento(x) == d], campo),
             "hoje": d == dia}
            for d in dias
        ],
        "lojas": linhas_de_loja,
        "artigos": _artigos_vendidos(turnos, grupos_de_variante),
    }
