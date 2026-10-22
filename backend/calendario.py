"""**Calendário das lojas** — onde falta gente, calculado (nunca guardado).

O dono quer que o calendário faça sozinho a conta que a Carol e a Débora faziam de cabeça
(desenho `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`, secção 2): com o
horário de cada loja, a escala de cada pessoa, as ausências aprovadas no RH e as idas
marcadas, diz onde falta gente.

**Este módulo não fala com o Mongo nem com o FastAPI, e é de propósito** (o mesmo princípio
do `bolso.py`): as rotas vivem no `server.py` e trazem para aqui listas de dicionários; aqui
fica só a matemática, que assim se testa com listas em memória.

Horas em minutos desde a meia-noite; intervalos `(inicio, fim)` semiabertos. Dias da semana
0 = segunda … 6 = domingo, como o `work_days` do RH. Horários que passam da meia-noite estão
fora do âmbito (nenhuma loja passa hoje).
"""
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

Intervalo = Tuple[int, int]

GESTORES = ("admin", "gerente")
ESCALAVEIS = ("admin", "gerente", "colaborador")
NOME_SEM_CONTA = "(conta removida)"
NOME_SEM_LOJA = "(loja removida)"
# Sempre com `fullmatch`: o `$` de um `match` aceita uma quebra de linha no fim («13:00\n»).
_HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def minutos(hhmm_: str) -> int:
    horas, mins = hhmm_.split(":")
    return int(horas) * 60 + int(mins)


def hhmm(total: int) -> str:
    return "%02d:%02d" % (total // 60, total % 60)


def hora_curta(hhmm_: str) -> str:
    """«10:00» -> «10h», «11:30» -> «11h30» — como se escreve numa mensagem."""
    horas, mins = hhmm_.split(":")
    return "%dh" % int(horas) if mins == "00" else "%dh%s" % (int(horas), mins)


def data_curta(iso: str) -> str:
    return "%s/%s" % (iso[8:10], iso[5:7])


def primeiro_nome(nome: Optional[str]) -> str:
    partes = (nome or "").split()
    return partes[0] if partes else ""


def unir(intervalos: List[Intervalo]) -> List[Intervalo]:
    """A união, ordenada; intervalos encostados juntam-se e os vazios desaparecem."""
    fora = []  # type: List[Intervalo]
    for inicio, fim in sorted(i for i in intervalos if i[0] < i[1]):
        if fora and inicio <= fora[-1][1]:
            fora[-1] = (fora[-1][0], max(fora[-1][1], fim))
        else:
            fora.append((inicio, fim))
    return fora


def subtrair(base: List[Intervalo], tirar: List[Intervalo]) -> List[Intervalo]:
    """`base` menos `tirar`, em intervalos. É daqui que saem os buracos."""
    resto = unir(base)
    for t_inicio, t_fim in unir(tirar):
        novo = []
        for inicio, fim in resto:
            if t_fim <= inicio or t_inicio >= fim:
                novo.append((inicio, fim))
                continue
            if inicio < t_inicio:
                novo.append((inicio, t_inicio))
            if t_fim < fim:
                novo.append((t_fim, fim))
        resto = novo
    return resto


def recortar(intervalo: Intervalo, janela: Intervalo) -> Optional[Intervalo]:
    """A parte de `intervalo` dentro de `janela`; `None` se não se tocarem (encostar não é tocar)."""
    inicio, fim = max(intervalo[0], janela[0]), min(intervalo[1], janela[1])
    return (inicio, fim) if inicio < fim else None


def horario_do_dia(loja: Optional[Dict], dia: date) -> Tuple[str, Optional[Intervalo]]:
    """O estado da loja nesse dia e, se abre, as horas.

    Estados: `sem_horario` (a loja não entra no calendário: Pizzaria, escritórios, loja
    apagada), `por_abrir` (antes de `aberta_desde`), `fechada` (o dia da semana está em
    `fechada`) e `aberta` (com a excepção desse dia da semana, ou o horário geral).
    Feriado NÃO fecha a loja — decisão do dono.
    """
    horario = (loja or {}).get("horario")
    if not horario:
        return "sem_horario", None
    desde = loja.get("aberta_desde")
    if desde and dia.isoformat() < desde:
        return "por_abrir", None
    semana = dia.weekday()
    if semana in (horario.get("fechada") or []):
        return "fechada", None
    excecao = next((e for e in horario.get("excecoes") or [] if e.get("dia") == semana), None)
    fonte = excecao or horario
    return "aberta", (minutos(fonte["abre"]), minutos(fonte["fecha"]))


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo anónimo gregoriano — o mesmo do `server._easter_sunday`)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> Dict[date, str]:
    """Os feriados nacionais COM NOME.

    O `server.get_pt_holidays` devolve as mesmas datas num `set` (os nomes estão lá em
    comentários) e guarda-as numa cache que o saldo de férias usa; este dicionário é
    construído à parte para não lhe tocar. Um teste confere que as datas são as mesmas.
    """
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Ano Novo",
        p - timedelta(days=2): "Sexta-feira Santa",
        p: "Páscoa",
        date(ano, 4, 25): "Dia da Liberdade",
        date(ano, 5, 1): "Dia do Trabalhador",
        p + timedelta(days=60): "Corpo de Deus",
        date(ano, 6, 10): "Dia de Portugal",
        date(ano, 8, 15): "Assunção de Nossa Senhora",
        date(ano, 10, 5): "Implantação da República",
        date(ano, 11, 1): "Todos os Santos",
        date(ano, 12, 1): "Restauração da Independência",
        date(ano, 12, 8): "Imaculada Conceição",
        date(ano, 12, 25): "Natal",
    }


def _cai_no_dia(feriado: Dict, dia: date) -> bool:
    # Compara números e nunca constrói a data: um personalizado de 30/02 (o formulário
    # aceita-o) simplesmente nunca cai em dia nenhum, em vez de dar um 500.
    try:
        return (int(feriado["month"]), int(feriado["day"])) == (dia.month, dia.day)
    except (KeyError, TypeError, ValueError):
        return False


def feriados_do_dia(dia: date, personalizados: List[Dict]) -> List[str]:
    """Os do dia inteiro: o nacional (se houver) e os personalizados de âmbito grupo."""
    nomes = []
    nacional = feriados_nacionais(dia.year).get(dia)
    if nacional:
        nomes.append(nacional)
    nomes += [h.get("name") or "Feriado" for h in personalizados
              if not h.get("company_id") and not h.get("location_id") and _cai_no_dia(h, dia)]
    return nomes


def feriados_da_loja(dia: date, personalizados: List[Dict], loja: Dict) -> List[str]:
    """Os personalizados da empresa da loja ou da própria loja (a regra «OU» do saldo de férias)."""
    return [h.get("name") or "Feriado" for h in personalizados
            if _cai_no_dia(h, dia) and (
                (h.get("company_id") and h.get("company_id") == loja.get("company_id"))
                or (h.get("location_id") and h.get("location_id") == loja.get("id")))]


def escala_vazia_no_feriado(dia: date, personalizados: List[Dict], loja: Dict) -> bool:
    """Num feriado DA LOJA (nacional, do grupo, da empresa ou dela) a escala não põe lá ninguém:
    coloca-se à mão (decisão do dono, 2026-10-16). Uma regra só, para o cálculo e o `escala_de`."""
    return bool(feriados_do_dia(dia, personalizados) or feriados_da_loja(dia, personalizados, loja))


# --- A escala: quem está em cada loja, num dia, pela escala fixa do RH ----------------------


def atribuicao_do_dia(atribuicoes: List[Dict], dia: date) -> Optional[Dict]:
    """A regra do `find_schedule_assignment` do `server.py`: a primeira, por data de início,
    que cobre o dia (`end_date` vazio = sem fim)."""
    iso = dia.isoformat()
    for a in sorted(atribuicoes, key=lambda a: a.get("start_date") or ""):
        inicio = (a.get("start_date") or "")[:10]
        fim = (a.get("end_date") or "")[:10]
        if inicio and inicio <= iso and (not fim or iso <= fim):
            return a
    return None


def _preparar(dados: Dict) -> Dict:
    """Os índices que cada dia consulta, construídos uma vez por pedido."""
    atribuicoes = {}  # type: Dict[str, List[Dict]]
    for a in dados.get("atribuicoes", []):
        atribuicoes.setdefault(a.get("employee_id"), []).append(a)
    utilizadores = {u["id"]: u for u in dados.get("utilizadores", [])}
    lojas = {l["id"]: l for l in dados.get("lojas", [])}
    empregados = dados.get("empregados", [])
    return {
        "lojas": lojas,
        "lojas_ordenadas": sorted(lojas.values(), key=lambda l: (l.get("name") or "").lower()),
        "empregados": empregados,
        "nome_do_emp": {e["id"]: e.get("name") for e in empregados},
        "atribuicoes": atribuicoes,
        "modelos": {m["id"]: m for m in dados.get("modelos", [])},
        "utilizadores": utilizadores,
        "user_do_emp": {u["employee_id"]: u["id"] for u in utilizadores.values() if u.get("employee_id")},
    }


def _escala(dia: date, p: Dict) -> Dict[str, Tuple[str, Intervalo]]:
    """`{employee_id: (location_id, horas)}` de quem trabalha neste dia pela escala.

    Parte de `employees` e não das atribuições: quem sai é apagado e as atribuições dele
    ficam órfãs (desenho, medido 6). Dias = `atribuição.work_days or modelo.work_days` (o
    recurso do «Em falta»). A entrada de `dias` desse dia diz a loja (vazia = a da ficha) e
    as horas (vazias = o horário da loja). Uma entrada para uma loja fechada, sem horário ou
    por abrir ignora-se; as horas recortam-se ao horário.
    """
    semana = dia.weekday()
    fora = {}
    for emp in p["empregados"]:
        atribuicao = atribuicao_do_dia(p["atribuicoes"].get(emp["id"], []), dia)
        if not atribuicao:
            continue
        modelo = p["modelos"].get(atribuicao.get("template_id")) or {}
        if semana not in (atribuicao.get("work_days") or modelo.get("work_days") or []):
            continue
        entrada = next((d for d in modelo.get("dias") or [] if d.get("dia") == semana), {})
        loja_id = entrada.get("location_id") or emp.get("location_id")
        estado, janela = horario_do_dia(p["lojas"].get(loja_id), dia)
        if estado != "aberta":
            continue
        if entrada.get("inicio") and entrada.get("fim"):
            pedido = (minutos(entrada["inicio"]), minutos(entrada["fim"]))
        else:
            pedido = janela
        horas = recortar(pedido, janela)
        if horas:
            fora[emp["id"]] = (loja_id, horas)
    return fora


def _aprovada_entre(a: Dict, de: str, ate: str) -> bool:
    """A ausência está APROVADA (de qualquer tipo) e toca [de, ate] (AAAA-MM-DD). A regra é só
    esta: os buracos, o 409 de «está de férias» e a lista do mês usam-na, para não divergirem."""
    return (a.get("status") == "aprovado"
            and (a.get("start_date") or "")[:10] <= ate and (a.get("end_date") or "")[:10] >= de)


def ausentes(dia: date, ausencias: List[Dict]) -> Set[str]:
    """Os `employee_id` com ausência APROVADA (de qualquer tipo) que inclui o dia."""
    iso = dia.isoformat()
    return {a.get("employee_id") for a in ausencias if _aprovada_entre(a, iso, iso)}


def escala_de(dia: date, dados: Dict, emp_id: str, p: Optional[Dict] = None) -> Optional[Tuple[str, Intervalo]]:
    """`(location_id, horas)` da escala dessa ficha nesse dia, depois das ausências aprovadas e
    do feriado da loja; `None` se não está na escala (folga, ausência, feriado)."""
    p = p or _preparar(dados)
    minha = _escala(dia, p).get(emp_id)
    if not minha or emp_id in ausentes(dia, dados.get("ausencias", [])):
        return None
    if escala_vazia_no_feriado(dia, dados.get("feriados", []), p["lojas"][minha[0]]):
        return None
    return minha


def _pessoa(user_id, nome, horas: Intervalo, origem: str, extra: bool = False, ida_id=None,
            troca_id=None, no_lugar_de=None, turno_inteiro=None) -> Dict:
    """`turno_inteiro`: na escala, se a linha é o turno inteiro da pessoa nesse dia (só esse se
    troca por turnos); `None` fora da escala."""
    return {"user_id": user_id, "nome": nome, "inicio": hhmm(horas[0]), "fim": hhmm(horas[1]),
            "origem": origem, "extra": extra, "ida_id": ida_id, "troca_id": troca_id, "no_lugar_de": no_lugar_de,
            "turno_inteiro": turno_inteiro}


def quem_sai(ida: Dict, nome_do_emp: Dict[str, str]) -> Optional[str]:
    """O nome de quem sai numa troca (o da ficha, como na linha da escala); `None` fora das trocas."""
    sai = ida.get("no_lugar_de_emp")
    return (nome_do_emp.get(sai) or NOME_SEM_CONTA) if sai else None


def _loja_do_dia(loja: Dict, dia: date, pessoas: List[Dict], personalizados: List[Dict]) -> Dict:
    estado, janela = horario_do_dia(loja, dia)
    pessoas = sorted(pessoas, key=lambda x: (x["inicio"], x["nome"] or ""))
    buracos = []
    if janela:
        ocupado = [(minutos(x["inicio"]), minutos(x["fim"])) for x in pessoas]
        buracos = [{"inicio": hhmm(a), "fim": hhmm(b)} for a, b in subtrair([janela], ocupado)]
    return {
        "location_id": loja["id"], "nome": loja.get("name"), "estado": estado,
        "abre": hhmm(janela[0]) if janela else None, "fecha": hhmm(janela[1]) if janela else None,
        "feriados": feriados_da_loja(dia, personalizados, loja),
        "pessoas": pessoas, "buracos": buracos,
    }


def dia_do_calendario(dia: date, dados: Dict, p: Optional[Dict] = None) -> Dict:
    """Um dia: para cada loja com horário (as por abrir não aparecem), quem lá está e os buracos.

    1. a escala (`_escala`), que num feriado DA LOJA (nacional, do grupo, da empresa ou dela)
    não põe lá ninguém — a loja fica aberta e com buraco até se marcarem idas; o «extra» das
    idas mede-se na mesma contra a escala normal; 2. sai quem tem ausência aprovada; 3. entram
    as idas — a de um gestor soma-se à loja; a de um colaborador TIRA à escala dele as horas da ida (a Joana
    13h–15h em Benfica numa quarta deixa Oeiras com buraco só das 13h às 15h), e as horas da
    ida (recortadas ao horário) que não estavam na escala dele são «extra» (numa folga, a ida
    toda); uma troca (`no_lugar_de_emp`, de gestor ou colaborador) tira também as horas à escala
    de quem sai, se ela é na loja da troca; 4. buracos = horário menos a união das horas de quem
    lá está («ninguém» = um buraco igual a abre–fecha).
    Uma ida numa loja sem horário, fechada ou por abrir não entra aqui (continua na lista das
    idas do mês). A de um colaborador com ausência aprovada DEPOIS de a ida existir (marcá-la
    já de férias dá 409) entra como as outras até um gestor a apagar — decisão do dono; a
    ausência tira-lhe só a escala, e por isso a ida dele nesse dia é toda «extra».
    """
    p = p or _preparar(dados)
    escala = _escala(dia, p)
    fora = ausentes(dia, dados.get("ausencias", []))
    for emp_id in fora:
        escala.pop(emp_id, None)
    iso = dia.isoformat()
    presentes = {}  # type: Dict[str, List[Dict]]
    tirado = {}  # type: Dict[str, List[Intervalo]]
    for ida in (i for i in dados.get("idas", []) if i.get("data") == iso):
        user = p["utilizadores"].get(ida.get("user_id")) or {}
        emp_id = user.get("employee_id") if user.get("role") == "colaborador" else None
        horas = (minutos(ida["inicio"]), minutos(ida["fim"]))
        estado, janela = horario_do_dia(p["lojas"].get(ida.get("location_id")), dia)
        dentro = recortar(horas, janela) if estado == "aberta" else None
        extra = False
        if emp_id:
            tirado.setdefault(emp_id, []).append(horas)
            minha = escala.get(emp_id)
            # Com as horas recortadas: chegar meia hora antes de abrir não é «extra».
            extra = bool(subtrair([dentro or horas], [minha[1]] if minha else []))
        # Uma troca tira as horas à escala de quem sai só se ela é NA LOJA DA TROCA: se a escala
        # dele mudou depois de loja, a troca fica uma ida à vista e não abre um buraco noutra loja.
        sai = ida.get("no_lugar_de_emp")
        if sai and (escala.get(sai) or (None,))[0] == ida.get("location_id"):
            tirado.setdefault(sai, []).append(horas)
        if ida.get("troca_id"):
            # O «no lugar de» já diz o que se passou: numa troca, «extra» é só quem entra com
            # ausência aprovada nesse dia (regra B: a troca fica até uma admin a desfazer).
            extra = bool(emp_id) and emp_id in fora
        if dentro:
            presentes.setdefault(ida["location_id"], []).append(_pessoa(
                ida.get("user_id"), user.get("name") or NOME_SEM_CONTA, dentro, "ida", extra, ida.get("id"),
                ida.get("troca_id"), quem_sai(ida, p["nome_do_emp"])))
    personalizados = dados.get("feriados", [])
    do_dia = feriados_do_dia(dia, personalizados)
    for emp_id, (loja_id, horas) in escala.items():
        if escala_vazia_no_feriado(dia, personalizados, p["lojas"][loja_id]):
            continue
        for pedaco in subtrair([horas], tirado.get(emp_id, [])):
            presentes.setdefault(loja_id, []).append(_pessoa(
                p["user_do_emp"].get(emp_id), p["nome_do_emp"].get(emp_id), pedaco, "escala",
                turno_inteiro=pedaco == horas))
    return {
        "data": iso,
        "feriados": do_dia,
        "lojas": [_loja_do_dia(loja, dia, presentes.get(loja["id"], []), personalizados)
                  for loja in p["lojas_ordenadas"]
                  if horario_do_dia(loja, dia)[0] in ("aberta", "fechada")],
    }


def calendario_do_mes(ano: int, mes: int, dados: Dict) -> List[Dict]:
    p = _preparar(dados)
    return [dia_do_calendario(date(ano, mes, d), dados, p) for d in range(1, monthrange(ano, mes)[1] + 1)]


# --- A contagem: quantos dias cada pessoa fez (e vai fazer) no ano --------------------------


def valor_da_ida(ida: Dict, loja: Optional[Dict]) -> float:
    """1 dia se as horas DENTRO do horário da loja nesse dia forem pelo menos metade das horas
    de abertura; 0,5 se forem menos. Uma ida numa loja que entretanto ficou sem horário (ou
    fechada nesse dia, ou apagada) vale 1 — não há com que comparar e a ida aconteceu."""
    _estado, janela = horario_do_dia(loja, date.fromisoformat(ida["data"]))
    if not janela:
        return 1.0
    dentro = recortar((minutos(ida["inicio"]), minutos(ida["fim"])), janela)
    feitas = dentro[1] - dentro[0] if dentro else 0
    return 1.0 if feitas * 2 >= janela[1] - janela[0] else 0.5


def contagem(idas: List[Dict], lojas: Dict[str, Dict], nomes: Dict[str, str],
             papeis: Optional[Dict[str, str]] = None) -> List[Dict]:
    """`[{user_id, nome, meses: [12], total}]`, do total maior para o menor. Por pessoa e por
    dia soma-se e corta-se em 1 (duas meias no mesmo dia = 1; nunca mais de 1). Com `papeis`
    (`{user_id: role}`), uma troca só conta quando quem entra é gestor (decisão do dono)."""
    por_dia = {}  # type: Dict[Tuple[str, str], float]
    for ida in idas:
        if papeis is not None and ida.get("troca_id") and papeis.get(ida["user_id"]) not in GESTORES:
            continue
        chave = (ida["user_id"], ida["data"])
        por_dia[chave] = min(1.0, por_dia.get(chave, 0.0) + valor_da_ida(ida, lojas.get(ida.get("location_id"))))
    meses = {}  # type: Dict[str, List[float]]
    for (user_id, data), valor in por_dia.items():
        meses.setdefault(user_id, [0.0] * 12)[int(data[5:7]) - 1] += valor
    linhas = [{"user_id": u, "nome": nomes.get(u) or NOME_SEM_CONTA, "meses": m, "total": sum(m)}
              for u, m in meses.items()]
    return sorted(linhas, key=lambda l: (-l["total"], l["nome"].lower()))


# --- As regras de uma ida (as rotas levantam 400/409 com estes textos) ---------------------

AUSENCIAS = {"ferias": "de férias", "folga": "de folga", "doenca": "de baixa",
             "falta": "com falta marcada", "ausencia": "ausente"}


def limites_do_mes(ano: int, mes: int) -> Tuple[str, str]:
    return date(ano, mes, 1).isoformat(), date(ano, mes, monthrange(ano, mes)[1]).isoformat()


def validar_pedido(datas: List[str], user_ids: List[str]) -> Optional[str]:
    if not 1 <= len(datas) <= 31:
        return "Escolha entre 1 e 31 dias."
    if not 1 <= len(user_ids) <= 2:
        return "Escolha uma ou duas pessoas."
    if len(set(datas)) != len(datas):
        return "Há dias repetidos no pedido."
    if len(set(user_ids)) != len(user_ids):
        return "Há pessoas repetidas no pedido."
    return None


def validar_horas(inicio, fim) -> Optional[str]:
    if not all(isinstance(h, str) and _HHMM.fullmatch(h) for h in (inicio, fim)):
        return "As horas escrevem-se HH:MM (por exemplo 13:00)."
    if minutos(inicio) >= minutos(fim):
        return "A hora de fim tem de ser depois da hora de início."
    return None


def validar_ida(dia: date, loja: Optional[Dict], inicio, fim) -> Optional[str]:
    """Horas válidas; loja com horário e aberta nesse dia; horas a TOCAR no horário (as que
    saem dele aceitam-se e recortam-se no cálculo e na contagem)."""
    erro = validar_horas(inicio, fim)
    if erro:
        return erro
    if not loja:
        return "Essa loja não existe."
    nome = loja.get("name") or "A loja"
    estado, janela = horario_do_dia(loja, dia)
    quando = data_curta(dia.isoformat())
    if estado == "sem_horario":
        return "%s não tem horário e não entra no calendário." % nome
    if estado == "por_abrir":
        return "%s só abre a %s." % (nome, data_curta(loja["aberta_desde"]))
    if estado == "fechada":
        return "%s está fechada a %s. Escolha outro dia." % (nome, quando)
    if not recortar((minutos(inicio), minutos(fim)), janela):
        return "%s abre das %s às %s a %s: as horas da ida têm de tocar nesse horário." % (
            nome, hora_curta(hhmm(janela[0])), hora_curta(hhmm(janela[1])), quando)
    return None


def choques(novas: List[Dict], existentes: List[Dict], ignorar_id: Optional[str] = None) -> List[Tuple[Dict, Dict]]:
    """Pares (nova, existente) da MESMA pessoa no MESMO dia com horas sobrepostas — ninguém
    está em dois sítios ao mesmo tempo. Horas encostadas (13h–17h e 17h–22h) não chocam."""
    pares = []
    for nova in novas:
        horas = (minutos(nova["inicio"]), minutos(nova["fim"]))
        for outra in existentes:
            if ignorar_id and outra.get("id") == ignorar_id:
                continue
            if (outra["user_id"] == nova["user_id"] and outra["data"] == nova["data"]
                    and recortar(horas, (minutos(outra["inicio"]), minutos(outra["fim"])))):
                pares.append((nova, outra))
    return pares


def mensagem_de_choque(nova: Dict, outra: Dict, utilizadores: Dict[str, Dict], nomes_lojas: Dict[str, str]) -> str:
    # Sem artigo («Débora já está…», não «A Débora…»): o RH não guarda o género.
    return "%s já está em %s das %s às %s a %s." % (
        primeiro_nome((utilizadores.get(nova["user_id"]) or {}).get("name")) or "Esta pessoa",
        nomes_lojas.get(outra["location_id"]) or NOME_SEM_LOJA,
        hora_curta(outra["inicio"]), hora_curta(outra["fim"]), data_curta(outra["data"]))


def ausencias_que_impedem(novas: List[Dict], utilizadores: Dict[str, Dict], ausencias: List[Dict]) -> List[str]:
    """Um colaborador não se marca num dia em que tem ausência APROVADA (os gestores não têm
    ficha nem ausências no RH)."""
    linhas = []
    for nova in novas:
        user = utilizadores.get(nova["user_id"]) or {}
        if user.get("role") != "colaborador":
            continue
        for a in ausencias:
            if a.get("employee_id") == user.get("employee_id") and _aprovada_entre(a, nova["data"], nova["data"]):
                linha = "%s está %s a %s." % (primeiro_nome(user.get("name")),
                                              AUSENCIAS.get(a.get("leave_type"), "ausente"), data_curta(nova["data"]))
                if linha not in linhas:
                    linhas.append(linha)
                break
    return linhas


# --- As regras de uma troca (desenho das trocas, «Recusas»; as rotas levantam 400/409) ------

ESCOLHA_OUTRA = "Escolha outra pessoa."


def _troca_de(emp_id: str, idas: List[Dict], iso: str, loja_id: str,
              horas: Optional[Intervalo] = None) -> Optional[Dict]:
    """A ida de uma troca já feita no lugar dessa ficha nesse dia, na loja da escala ACTUAL dela
    (a condição do `dia_do_calendario`: uma troca que ficou noutra loja não lhe tira nada); com
    `horas`, só se se sobrepõem."""
    for ida in idas:
        if (ida.get("no_lugar_de_emp") == emp_id and ida.get("data") == iso
                and ida.get("location_id") == loja_id and (
                horas is None or recortar(horas, (minutos(ida["inicio"]), minutos(ida["fim"]))))):
            return ida
    return None


def _ja_ha_troca(nome: str, ida: Dict, p: Dict) -> str:
    quem = primeiro_nome((p["utilizadores"].get(ida.get("user_id")) or {}).get("name"))
    # O «(conta removida)» já traz os parênteses.
    return "Já há uma troca para %s a %s %s." % (
        nome, data_curta(ida["data"]), "(%s)" % quem if quem else NOME_SEM_CONTA)


def _fora_da_escala(nome: str, dia: date) -> str:
    return "%s não está na escala a %s." % (nome, data_curta(dia.isoformat()))


def recusa_da_troca(dia: date, dados: Dict, sai_emp: str, sai_nome: Optional[str], entra_user: str,
                    inicio, fim, idas_do_dia: List[Dict]) -> Optional[Tuple[int, str]]:
    """A troca simples: `(400|409, frase)` ou `None`. O papel e a ausência de quem entra (e o
    choque com outra ida dele) são do servidor, com as regras das idas."""
    p = _preparar(dados)
    if sai_emp and (p["utilizadores"].get(entra_user) or {}).get("employee_id") == sai_emp:
        return 400, ESCOLHA_OUTRA
    erro = validar_horas(inicio, fim)
    if erro:
        return 400, erro
    nome = primeiro_nome(sai_nome) or "Esta pessoa"
    minha = escala_de(dia, dados, sai_emp, p)
    if not minha:
        return 409, _fora_da_escala(nome, dia)
    horas = (minutos(inicio), minutos(fim))
    if horas[0] < minha[1][0] or horas[1] > minha[1][1]:
        return 409, "As horas da troca têm de estar dentro das de %s (%s–%s)." % (
            nome, hora_curta(hhmm(minha[1][0])), hora_curta(hhmm(minha[1][1])))
    outra = _troca_de(sai_emp, idas_do_dia, dia.isoformat(), minha[0], horas)
    if outra:
        return 409, _ja_ha_troca(nome, outra, p)
    return None


def turnos_da_troca_entre_si(dia: date, dados: Dict, emp_a: str, emp_b: str) -> Tuple:
    """`(ida_a, ida_b)` — cada pessoa vai para a loja e as horas da outra, turnos inteiros, «no
    lugar» dela — ou a recusa `(400|409, frase)`. As idas da troca vêm de `dados["idas"]`."""
    if emp_a == emp_b:
        return 400, ESCOLHA_OUTRA
    p = _preparar(dados)
    iso = dia.isoformat()
    nomes = {e: primeiro_nome(p["nome_do_emp"].get(e)) or "Esta pessoa" for e in (emp_a, emp_b)}
    turnos = {}
    for emp_id in (emp_a, emp_b):
        turnos[emp_id] = escala_de(dia, dados, emp_id, p)
        if not turnos[emp_id]:
            return 409, _fora_da_escala(nomes[emp_id], dia)
    if turnos[emp_a] == turnos[emp_b]:
        return 400, ESCOLHA_OUTRA
    for emp_id in (emp_a, emp_b):
        outra = _troca_de(emp_id, dados.get("idas", []), iso, turnos[emp_id][0])
        if outra:
            return 409, _ja_ha_troca(nomes[emp_id], outra, p)

    def _ida(quem, de):
        loja_id, (inicio, fim) = turnos[de]
        return {"data": iso, "location_id": loja_id, "user_id": p["user_do_emp"].get(quem),
                "inicio": hhmm(inicio), "fim": hhmm(fim), "no_lugar_de_emp": de}

    return _ida(emp_a, emp_b), _ida(emp_b, emp_a)


# --- A resposta do mês (GET /api/bolso/calendario) -----------------------------------------


def pessoas_escalaveis(utilizadores: List[Dict], fichas: Set[str]) -> List[Dict]:
    """Quem pode ser escalado numa ida: gestores primeiro (todos), depois os colaboradores cuja
    ficha está em `fichas`, por nome. O contabilista lê o calendário mas não pode ser escalado."""
    escolhidas = [u for u in utilizadores if u.get("role") in GESTORES
                  or (u.get("role") == "colaborador" and u.get("employee_id") in fichas)]
    escolhidas.sort(key=lambda u: (u.get("role") not in GESTORES, (u.get("name") or "").lower()))
    return [{"id": u["id"], "nome": u.get("name") or NOME_SEM_CONTA,
             "tipo": "gestor" if u.get("role") in GESTORES else "colaborador"} for u in escolhidas]


def resposta_do_mes(ano: int, mes: int, dados: Dict, eu: Optional[str], pode_marcar: bool,
                    pode_trocar: bool = False) -> Dict:
    """O mês inteiro, como o ecrã o lê. `idas[]` leva as idas do mês com os nomes — é daqui
    que se montam a vista Pessoal e as idas da Lista (uma ida numa loja que entretanto perdeu
    o horário continua a aparecer aqui, e não em `dias`)."""
    inicio, fim = limites_do_mes(ano, mes)
    lojas = {l["id"]: l for l in dados.get("lojas", [])}
    utilizadores = {u["id"]: u for u in dados.get("utilizadores", [])}
    empregados = {e["id"]: e for e in dados.get("empregados", [])}
    nome_do_emp = {e_id: e.get("name") for e_id, e in empregados.items()}
    idas = sorted((i for i in dados.get("idas", []) if inicio <= i["data"] <= fim),
                  key=lambda i: (i["data"], i["inicio"]))
    # O grupo tem empresas sem calendário (a pizzaria, com uma «Loja Alfragide» homónima): as
    # ausências e os colaboradores contam só os das empresas das lojas COM horário, pela empresa
    # da FICHA — não pela loja dela, que os colaboradores «sem loja» não têm.
    empresas = {l.get("company_id") for l in lojas.values() if l.get("horario")}
    fichas = {e["id"] for e in empregados.values() if e.get("company_id") in empresas}

    def _ficha(a):
        return empregados.get(a.get("employee_id")) or {}

    ausencias = sorted((a for a in dados.get("ausencias", [])
                        if a.get("employee_id") in fichas and _aprovada_entre(a, inicio, fim)),
                       key=lambda a: a.get("start_date") or "")

    return {
        "ano": ano, "mes": mes, "eu": eu, "pode_marcar": pode_marcar, "pode_trocar": pode_trocar,
        "dias": calendario_do_mes(ano, mes, dados),
        "idas": [{"id": i.get("id"), "data": i["data"], "location_id": i.get("location_id"),
                  "user_id": i.get("user_id"), "inicio": i["inicio"], "fim": i["fim"],
                  "nome": (utilizadores.get(i.get("user_id")) or {}).get("name") or NOME_SEM_CONTA,
                  "loja": (lojas.get(i.get("location_id")) or {}).get("name") or NOME_SEM_LOJA,
                  "troca_id": i.get("troca_id"), "no_lugar_de": quem_sai(i, nome_do_emp)}
                 for i in idas],
        "ausencias": [{"nome": _ficha(a).get("name") or NOME_SEM_CONTA, "tipo": a.get("leave_type"),
                       "inicio": (a.get("start_date") or "")[:10], "fim": (a.get("end_date") or "")[:10],
                       "loja": (lojas.get(_ficha(a).get("location_id")) or {}).get("name"),
                       "location_id": _ficha(a).get("location_id")}
                      for a in ausencias],
        "lojas": [{"id": l["id"], "nome": l.get("name")}
                  for l in sorted(lojas.values(), key=lambda l: (l.get("name") or "").lower()) if l.get("horario")],
        "pessoas": pessoas_escalaveis(dados.get("utilizadores", []), fichas),
    }
