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


def _registo_do_periodo(registos: List[Dict], plataforma: str,
                        inicio: str, fim: str) -> Optional[Dict]:
    """O registo desta plataforma para este período exacto.

    A comparação é pelas DUAS pontas: um relatório com o início certo e o fim
    trocado é um relatório de outro período, e aceitá-lo pelo início punha os
    números da quinzena na linha da semana.
    """
    for registo in registos:
        if (registo.get("plataforma") == plataforma
                and registo.get("periodo_inicio") == inicio
                and registo.get("periodo_fim") == fim):
            return registo
    return None


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
    registo = _registo_do_periodo(registos, chave, periodo["inicio"], periodo["fim"])

    anterior_periodo = _periodo_anterior(periodo["tipo"], periodo["inicio"], periodo["fim"])
    anterior = _registo_do_periodo(
        registos, chave, anterior_periodo["inicio"], anterior_periodo["fim"])

    valores = (registo or {}).get("valores") or {}
    valores_antes = (anterior or {}).get("valores") or {}
    liquido = valores.get("liquido")

    return {
        "chave": chave,
        "nome": definicao["nome"],
        "ritmo": definicao["ritmo"],
        "estado": "lido" if registo else "nao_recebido",
        "periodo": periodo,
        "valores": {
            "liquido": liquido,
            "bruto": valores.get("bruto"),
            "pedidos": valores.get("pedidos"),
            "comissao": valores.get("comissao"),
            "taxas": valores.get("taxas"),
            "ajustes": valores.get("ajustes"),
            "iva": valores.get("iva"),
            "moeda": valores.get("moeda") or "EUR",
        },
        "lojas": (registo or {}).get("lojas") or [],
        "problemas": (registo or {}).get("problemas") or [],
        "notas": (registo or {}).get("notas"),
        "origem": (registo or {}).get("origem") or {},
        "periodo_origem": (registo or {}).get("periodo_origem"),
        "anterior": {
            "inicio": anterior_periodo["inicio"],
            "fim": anterior_periodo["fim"],
            "liquido": valores_antes.get("liquido"),
            "pedidos": valores_antes.get("pedidos"),
        },
        "variacao": variacao(liquido, valores_antes.get("liquido")),
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
    # Só se compara o total quando as MESMAS plataformas têm valor nas duas
    # semanas: uma semana com duas e outra com uma dava uma queda inventada.
    comparavel = (total["completo"]
                  and len(anterior_com_valor) == len(da_semana))
    total["anterior"] = total_anterior
    total["variacao"] = variacao(total["liquido"], total_anterior) if comparavel else None

    problemas = [
        {"plataforma": l["nome"], "texto": texto}
        for l in linhas for texto in l["problemas"]
    ]

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
