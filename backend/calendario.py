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
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


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


def ausentes(dia: date, ausencias: List[Dict]) -> Set[str]:
    """Os `employee_id` com ausência APROVADA (de qualquer tipo) que inclui o dia."""
    iso = dia.isoformat()
    return {a.get("employee_id") for a in ausencias
            if a.get("status") == "aprovado"
            and (a.get("start_date") or "")[:10] <= iso <= (a.get("end_date") or "")[:10]}


def _pessoa(user_id, nome, horas: Intervalo, origem: str, extra: bool = False, ida_id=None) -> Dict:
    return {"user_id": user_id, "nome": nome, "inicio": hhmm(horas[0]), "fim": hhmm(horas[1]),
            "origem": origem, "extra": extra, "ida_id": ida_id}


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

    1. a escala (`_escala`); 2. sai quem tem ausência aprovada; 3. entram as idas — a de um
    gestor soma-se à loja; a de um colaborador TIRA à escala dele as horas da ida (a Joana
    13h–15h em Benfica numa quarta deixa Oeiras com buraco só das 13h às 15h), e as horas da
    ida (recortadas ao horário) que não estavam na escala dele são «extra» (numa folga, a ida
    toda); 4. buracos = horário menos a união das horas de quem lá está («ninguém» = um
    buraco igual a abre–fecha).
    Uma ida numa loja sem horário, fechada ou por abrir não entra aqui (continua na lista das
    idas do mês). A de um colaborador com ausência aprovada nesse dia também não.
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
        if emp_id and emp_id in fora:
            # Férias aprovadas DEPOIS de a ida existir (marcá-la já de férias dá 409): não está
            # lá, por isso não tapa — nunca «coberta» numa loja vazia. A ida continua em
            # `idas[]` (vistas Pessoal e Lista). Decisão por omissão, a confirmar com o dono
            # (Tarefa 16).
            continue
        horas = (minutos(ida["inicio"]), minutos(ida["fim"]))
        estado, janela = horario_do_dia(p["lojas"].get(ida.get("location_id")), dia)
        dentro = recortar(horas, janela) if estado == "aberta" else None
        extra = False
        if emp_id:
            tirado.setdefault(emp_id, []).append(horas)
            minha = escala.get(emp_id)
            # Com as horas recortadas: chegar meia hora antes de abrir não é «extra».
            extra = bool(subtrair([dentro or horas], [minha[1]] if minha else []))
        if dentro:
            presentes.setdefault(ida["location_id"], []).append(_pessoa(
                ida.get("user_id"), user.get("name") or NOME_SEM_CONTA, dentro, "ida", extra, ida.get("id")))
    for emp_id, (loja_id, horas) in escala.items():
        for pedaco in subtrair([horas], tirado.get(emp_id, [])):
            presentes.setdefault(loja_id, []).append(_pessoa(
                p["user_do_emp"].get(emp_id), p["nome_do_emp"].get(emp_id), pedaco, "escala"))
    personalizados = dados.get("feriados", [])
    return {
        "data": iso,
        "feriados": feriados_do_dia(dia, personalizados),
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


def contagem(idas: List[Dict], lojas: Dict[str, Dict], nomes: Dict[str, str]) -> List[Dict]:
    """`[{user_id, nome, meses: [12], total}]`, do total maior para o menor. Por pessoa e por
    dia soma-se e corta-se em 1 (duas meias no mesmo dia = 1; nunca mais de 1)."""
    por_dia = {}  # type: Dict[Tuple[str, str], float]
    for ida in idas:
        chave = (ida["user_id"], ida["data"])
        por_dia[chave] = min(1.0, por_dia.get(chave, 0.0) + valor_da_ida(ida, lojas.get(ida.get("location_id"))))
    meses = {}  # type: Dict[str, List[float]]
    for (user_id, data), valor in por_dia.items():
        meses.setdefault(user_id, [0.0] * 12)[int(data[5:7]) - 1] += valor
    linhas = [{"user_id": u, "nome": nomes.get(u) or NOME_SEM_CONTA, "meses": m, "total": sum(m)}
              for u, m in meses.items()]
    return sorted(linhas, key=lambda l: (-l["total"], l["nome"].lower()))
