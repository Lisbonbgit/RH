"""**Os números do relatório de segunda-feira** — aritmética pura, sem Mongo,
sem IA e sem email.

Recebe os registos já lidos (`leitura.montar_registo`) e devolve o dicionário
que o email desenha. Não lê base de dados e não fala com ninguém: é isso que
deixa as contas ser testadas sem uma caixa de email pelo meio, e o desenho do
email ser visto sem inventar vendas.

**Duas regras mandam neste ficheiro.**

1. **Um valor que não chegou não vira zero.** Uma plataforma sem relatório fica
   com `estado: "nao_recebido"` e os valores a `None`. O email escreve "não
   recebido"; nunca "0,00 €", que se lê como "não vendemos nada".

2. **O total da semana é só a Uber e a Bolt.** A Glovo fecha contas de quinze
   em quinze dias: somá-la aqui juntava uma semana com uma quinzena e dava um
   número que não é o de período nenhum. Ela tem o seu próprio bloco, com o
   seu próprio período e a sua própria data de pagamento.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional

from .calendario import (
    PLATAFORMAS,
    calendario_glovo,
    dias_ate,
    periodo_da_plataforma,
    quinzena_de,
)


def _registos_do_periodo(registos: List[Dict], plataforma: str,
                         inicio: str, fim: str) -> List[Dict]:
    """**TODOS** os registos desta plataforma para este período exacto — um por
    loja.

    A comparação é pelas DUAS pontas: um relatório com o início certo e o fim
    trocado é um relatório de outro período, e aceitá-lo pelo início punha os
    números da quinzena na linha da semana.
    """
    return [r for r in registos
            if r.get("plataforma") == plataforma
            and r.get("periodo_inicio") == inicio
            and r.get("periodo_fim") == fim]


# Os campos em dinheiro que se somam entre lojas. O `moeda` fica de fora (não
# se soma), e o `pedidos` também vai aqui porque a regra é a mesma.
CAMPOS_SOMAVEIS = ("liquido", "bruto", "pedidos", "comissao", "taxas", "ajustes", "iva")


def _somar_lojas(registos: List[Dict]) -> Dict:
    """Junta os relatórios das várias lojas num só conjunto de números.

    **Uma parcela desconhecida não vira zero.** Se três lojas dizem o valor e
    a quarta não, a soma é das três — e quem lê tem de saber que foi só de
    três, que é para isso que serve o `lojas` desta mesma saída. Um campo em
    que NENHUMA loja disse nada fica a `None`, nunca a zero.

    Em cêntimos e só a euros no fim: `293.39 + 211.77 + 1720.10` em vírgula
    flutuante deixa resto, e isto aparece num email a dizer quanto se vai
    receber.
    """
    somas: Dict = {}
    for campo in CAMPOS_SOMAVEIS:
        valores = [r.get("valores", {}).get(campo) for r in registos]
        presentes = [v for v in valores if v is not None]
        if not presentes:
            somas[campo] = None
        elif campo == "pedidos":
            somas[campo] = int(sum(presentes))
        else:
            somas[campo] = round(sum(int(round(v * 100)) for v in presentes) / 100.0, 2)
    somas["moeda"] = next(
        (r.get("valores", {}).get("moeda") for r in registos
         if r.get("valores", {}).get("moeda")), "EUR")
    return somas


def _lojas_dos_registos(registos: List[Dict]) -> List[Dict]:
    """Uma linha por loja, com o que essa loja trouxe."""
    linhas = []
    for registo in registos:
        valores = registo.get("valores") or {}
        linhas.append({
            "nome": registo.get("loja") or "(loja não identificada)",
            "identificada": bool(registo.get("loja")),
            "liquido": valores.get("liquido"),
            "pedidos": valores.get("pedidos"),
        })
    linhas.sort(key=lambda l: (-(l["liquido"] or 0), l["nome"]))
    return linhas


def _periodo_anterior(tipo: str, inicio: str, fim: str) -> Dict:
    """O período imediatamente antes deste — o termo de comparação.

    Uma semana recua sete dias. Uma quinzena recua para a que acaba na véspera
    do seu início (que pode ter 13, 14, 15 ou 16 dias, conforme o mês) — por
    isso pergunta-se ao calendário em vez de subtrair quinze dias à mão.
    """
    if tipo == "semana":
        inicio_d = date.fromisoformat(inicio) - timedelta(days=7)
        fim_d = date.fromisoformat(fim) - timedelta(days=7)
    else:
        inicio_d, fim_d = quinzena_de(date.fromisoformat(inicio) - timedelta(days=1))
    return {"inicio": inicio_d.isoformat(), "fim": fim_d.isoformat()}


def variacao(agora: Optional[float], antes: Optional[float]) -> Optional[float]:
    """A variação em percentagem, ou `None` quando não há com que comparar.

    `None` e não zero: "0%" lia-se "igual à semana passada", e o que se passou
    foi que não havia semana passada nenhuma para comparar. Um `antes` a zero
    também não serve — dividir por ele dá infinito, e "+100%" sobre zero não
    quer dizer nada.
    """
    if agora is None or antes is None or not antes:
        return None
    return round(((agora - antes) / abs(antes)) * 100.0, 2)


def _linha_da_plataforma(definicao: Dict, registos: List[Dict], hoje: date) -> Dict:
    chave = definicao["chave"]
    periodo = periodo_da_plataforma(chave, hoje)
    do_periodo = _registos_do_periodo(registos, chave, periodo["inicio"], periodo["fim"])

    anterior_periodo = _periodo_anterior(periodo["tipo"], periodo["inicio"], periodo["fim"])
    antes = _registos_do_periodo(
        registos, chave, anterior_periodo["inicio"], anterior_periodo["fim"])

    valores = _somar_lojas(do_periodo)
    valores_antes = _somar_lojas(antes)
    liquido = valores.get("liquido")

    # **Três estados, e não dois.** «Recebido sem valores» não é o mesmo que
    # «não recebido»: o primeiro quer dizer que a plataforma escreveu e nós é
    # que não conseguimos ler, e é isso que manda alguém ir ver ao portal.
    if not do_periodo:
        estado = "nao_recebido"
    elif liquido is None:
        estado = "sem_valores"
    else:
        estado = "lido"

    # As lojas que reportaram agora contra as que reportaram no período
    # anterior. Menos lojas agora é um total mais pequeno por FALTA de um
    # relatório, e não por menos vendas — e sem este aviso lê-se como quebra.
    chaves_agora = {r.get("loja_chave") for r in do_periodo if r.get("loja_chave")}
    chaves_antes = {r.get("loja_chave") for r in antes if r.get("loja_chave")}
    em_falta = sorted(
        (r.get("loja") or r.get("loja_chave"))
        for r in antes if r.get("loja_chave") and r.get("loja_chave") not in chaves_agora)

    return {
        "chave": chave,
        "nome": definicao["nome"],
        "ritmo": definicao["ritmo"],
        "estado": estado,
        "periodo": periodo,
        "valores": valores,
        "lojas": _lojas_dos_registos(do_periodo),
        "lojas_que_reportaram": len(do_periodo),
        "lojas_no_periodo_anterior": len(antes),
        "lojas_em_falta": em_falta,
        "sem_loja_identificada": sum(1 for r in do_periodo if not r.get("loja")),
        "problemas": [p for r in do_periodo for p in (r.get("problemas") or [])],
        "notas": next((r.get("notas") for r in do_periodo if r.get("notas")), None),
        "origem": (do_periodo[0].get("origem") if do_periodo else {}) or {},
        "periodo_origem": next(
            (r.get("periodo_origem") for r in do_periodo
             if r.get("periodo_origem") == "calendário"), None),
        "anterior": {
            "inicio": anterior_periodo["inicio"],
            "fim": anterior_periodo["fim"],
            "liquido": valores_antes.get("liquido"),
            "pedidos": valores_antes.get("pedidos"),
            "lojas": len(antes),
        },
        # Só se compara quando as MESMAS lojas reportaram nos dois períodos:
        # três lojas contra quatro mede o relatório que faltou, não as vendas.
        "variacao": (variacao(liquido, valores_antes.get("liquido"))
                     if chaves_agora and chaves_agora == chaves_antes else None),
        "comparavel": bool(chaves_agora and chaves_agora == chaves_antes),
    }


def montar_relatorio(*, hoje: date, ate: str, registos: List[Dict],
                     avisos: Optional[List[str]] = None) -> Dict:
    """O relatório de segunda-feira, pronto a desenhar.

    `registos` são TODOS os que estão guardados nos últimos períodos (não só os
    desta semana): os do período em curso saem daqui, e os do anterior servem a
    comparação. Uma lista em vez de duas evita que quem chama passe um "agora"
    e um "antes" que não são períodos seguidos.
    """
    linhas = [_linha_da_plataforma(d, registos, hoje) for d in PLATAFORMAS]
    por_chave = {l["chave"]: l for l in linhas}

    # O total é SÓ da semana — ver a segunda regra na docstring do módulo.
    da_semana = [l for l in linhas if l["ritmo"] == "semana"]
    com_valor = [l for l in da_semana if l["valores"]["liquido"] is not None]
    em_falta = [l["nome"] for l in da_semana if l["valores"]["liquido"] is None]
    pedidos = [l["valores"]["pedidos"] for l in da_semana
               if l["valores"]["pedidos"] is not None]

    semana = periodo_da_plataforma("uber", hoje)  # a semana é a mesma para as duas
    total = {
        # `None` e não zero quando não chegou nenhum dos dois: um total a zero
        # numa segunda-feira lia-se como uma semana sem vendas.
        "liquido": round(sum(l["valores"]["liquido"] for l in com_valor), 2)
        if com_valor else None,
        "pedidos": sum(pedidos) if pedidos else None,
        # **A honestidade do número.** Com uma plataforma em falta, o total é
        # de uma só — e tem de se ler que é parcial, senão compara-se contra a
        # semana passada e conclui-se que as vendas caíram para metade.
        "completo": not em_falta,
        "em_falta": em_falta,
    }
    anterior_com_valor = [l for l in da_semana if l["anterior"]["liquido"] is not None]
    total_anterior = (round(sum(l["anterior"]["liquido"] for l in anterior_com_valor), 2)
                      if anterior_com_valor else None)
    # Só se compara o total quando as MESMAS plataformas E as mesmas LOJAS
    # reportaram nos dois períodos: uma semana com duas plataformas contra uma
    # com uma — ou quatro lojas contra três — dava uma queda inventada.
    comparavel = (total["completo"]
                  and len(anterior_com_valor) == len(da_semana)
                  and all(l["comparavel"] for l in da_semana))
    total["anterior"] = total_anterior
    total["variacao"] = variacao(total["liquido"], total_anterior) if comparavel else None

    problemas = [
        {"plataforma": l["nome"], "texto": texto}
        for l in linhas for texto in l["problemas"]
    ]

    # As lojas que reportaram no período anterior e não neste. É um aviso de
    # dinheiro: o total é menor porque falta um relatório, não porque se
    # vendeu menos.
    for linha in linhas:
        for loja in linha["lojas_em_falta"]:
            problemas.append({
                "plataforma": linha["nome"],
                "texto": "Não chegou o relatório da loja «%s» — no período "
                         "anterior ela reportou, por isso o total desta "
                         "plataforma está a menos." % loja,
            })

    return {
        "hoje": hoje.isoformat(),
        "ate": ate,
        "semana": {
            "inicio": semana["inicio"],
            "fim": semana["fim"],
            "chave": semana["chave"],
            "pagamento": semana["pagamento"],
        },
        "plataformas": linhas,
        "total_da_semana": total,
        "glovo": dict(calendario_glovo(hoje), linha=por_chave["glovo"]),
        "problemas": problemas,
        "avisos": list(avisos or []),
        "dias_ate_ao_pagamento_da_glovo": dias_ate(
            date.fromisoformat(por_chave["glovo"]["periodo"]["pagamento"]), hoje),
    }
