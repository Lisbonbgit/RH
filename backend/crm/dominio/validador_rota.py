"""A validação dos pedidos às rotas: o dia, o intervalo e os corpos (F3).

O CRM autónomo não tem código de rotas: as regras e as mensagens vêm do plano
F3 (§1 e §4). Como o `validador_loja`, cada função devolve `(dados, erros)`,
com os erros `{campo: mensagem pt-PT}` do 422 `validacao`; os dados só se
usam quando não há erros e são sempre estruturas novas (o corpo não muda).
Os dias são `date` (`datas.ler_data`) e o `hoje` vem de `relogio.hoje()`.

O que depende da rota guardada não se vê aqui, mas na rota HTTP depois de a
ler (o 422 "contra a rota", plano §4): os ids que não estão na rota
(`MENSAGEM_NAO_ESTA_NA_ROTA`) e a coerência das horas sobre os valores já
juntos com os guardados (`coerencia_horas`).

Armadilhas (plano §10): o `bool` nunca conta como inteiro nem o `1.0` como
`1` (`numeros.e_inteiro_json`); as coordenadas arredondam-se às 6 casas
meio-para-longe-do-zero (`numeros.arredondar`, nunca o `round()`) e só depois
se veem contra Portugal continental; os uuid4 são o texto minúsculo exato
(`ids.e_uuid4`), por isso nunca chega ao Mongo um operador (`{"$gt": ""}`).
"""
from datetime import date

from . import janelas
from .datas import MAXIMO_DIAS_FUTURO, ler_data, somar_dias
from .geo import MENSAGEM_PORTUGAL, contem_latitude, contem_longitude
from .ids import e_uuid4
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .rotas import MOTIVOS

# O intervalo do `GET /rotas` por omissão (hoje − 14 a hoje + 60) e o máximo,
# em dias de calendário com os dois extremos incluídos.
INTERVALO_DIAS_ANTES = 14
INTERVALO_DIAS_DEPOIS = 60
INTERVALO_MAXIMO_DIAS = 120

# O tempo de serviço de uma paragem, em minutos inteiros.
TEMPO_SERVICO_MINIMO = 1
TEMPO_SERVICO_MAXIMO = 240

# As chaves do PATCH, pela ordem dos dados e dos erros (os `paragens.<id>…`
# entram no lugar de `paragens`); as outras ignoram-se.
CHAVES_ALTERACAO = (
    "versao", "hora_saida", "hora_regresso_limite", "inicio", "fim", "evitar_portagens", "ordem", "paragens",
    "retirar", "estado",
)
# O que o escritório muda numa paragem pelo PATCH, por esta ordem; as outras
# chaves (os campos do terreno, `ordem`, as horas…) ignoram-se.
CHAVES_PARAGEM = ("motivo", "tempo_servico_min", "manter_fechada", "nao_cabe")

# As mensagens do plano F3 §4.
MENSAGEM_DATA = "Indique o dia no formato AAAA-MM-DD."
MENSAGEM_HORIZONTE = "Escolha um dia até um ano a partir de hoje."
MENSAGEM_FIM_ANTES_DO_INICIO = "O fim do intervalo tem de ser depois do início."
MENSAGEM_INTERVALO_LONGO = f"O intervalo tem no máximo {INTERVALO_MAXIMO_DIAS} dias."
MENSAGEM_LOJA = "Escolha uma loja."
MENSAGEM_MOTIVO = "Escolha um motivo: entrega, amostra, acompanhamento ou angariação."
MENSAGEM_VERSAO_OBRIGATORIA = "Indique a versão da rota que recebeu."
MENSAGEM_VERSAO_INVALIDA = "A versão da rota não é válida."
MENSAGEM_HORA_VAZIA = "Indique a hora."
MENSAGEM_COERENCIA_HORAS = "A hora limite de regresso tem de ser depois da hora de saída."
MENSAGEM_SIM_OU_NAO = "Escolha sim ou não."
MENSAGEM_PONTO = "Escolha a fábrica ou um ponto no mapa."
MENSAGEM_LATITUDE = "A latitude tem de ser um número."
MENSAGEM_LONGITUDE = "A longitude tem de ser um número."
MENSAGEM_ORDEM = "A ordem tem de ser uma lista de paragens, sem repetidas."
MENSAGEM_NAO_ESTA_NA_ROTA = "Esta paragem não está na rota."
MENSAGEM_PARAGENS = "Indique as alterações de cada paragem."
MENSAGEM_VAI_SER_RETIRADA = "Esta paragem vai ser retirada."
MENSAGEM_TEMPO_SERVICO = (
    f"O tempo de serviço é um número inteiro de minutos, de {TEMPO_SERVICO_MINIMO} a {TEMPO_SERVICO_MAXIMO}."
)
MENSAGEM_NAO_CABE = "Só se pode pôr de volta na rota."
MENSAGEM_RETIRAR = "Indique as paragens a retirar, sem repetidas."
MENSAGEM_ESTADO = "Só se pode marcar a rota como planeada."


def data_do_caminho(texto, hoje: date):
    """O dia do caminho `/rotas/{data}`: `(date, {})` ou `(None, {"data": erro})`.

    O texto tem de ser exatamente `AAAA-MM-DD` (`datas.ler_data`) e o dia no
    máximo `MAXIMO_DIAS_FUTURO` dias depois de hoje (o último aceite é hoje +
    365). O passado é válido aqui: ler uma rota antiga é normal, e as escritas
    dão o 409 `rota_fechada` depois.
    """
    _exigir_dia(hoje)
    dia = ler_data(texto)
    if dia is None:
        return None, {"data": MENSAGEM_DATA}
    if dia > somar_dias(hoje, MAXIMO_DIAS_FUTURO):
        return None, {"data": MENSAGEM_HORIZONTE}
    return dia, {}


def intervalo(de, ate, hoje: date):
    """Os dias do `GET /rotas?de=&ate=`: `((de, ate), {})` ou `(None, erros)`.

    Um parâmetro em falta (`None`) é o da omissão: hoje − 14 e hoje + 60,
    cada um por si. Um parâmetro presente, mesmo vazio (`?de=`), tem de ser
    um dia `AAAA-MM-DD`. Com os dois dias lidos, o fim não pode vir antes do
    início (o mesmo dia é um intervalo de um dia) e o intervalo tem no máximo
    120 dias de calendário, contando os dois extremos; estes dois erros ficam
    em `ate`.
    """
    _exigir_dia(hoje)
    inicio = somar_dias(hoje, -INTERVALO_DIAS_ANTES) if de is None else ler_data(de)
    fim = somar_dias(hoje, INTERVALO_DIAS_DEPOIS) if ate is None else ler_data(ate)

    erros = {}
    if inicio is None:
        erros["de"] = MENSAGEM_DATA
    if fim is None:
        erros["ate"] = MENSAGEM_DATA
    elif inicio is not None:
        if fim < inicio:
            erros["ate"] = MENSAGEM_FIM_ANTES_DO_INICIO
        elif (fim - inicio).days + 1 > INTERVALO_MAXIMO_DIAS:
            erros["ate"] = MENSAGEM_INTERVALO_LONGO

    if erros:
        return None, erros
    return (inicio, fim), {}


def adicao(corpo: dict):
    """O corpo do `POST /rotas/{data}/paragens`: `({loja_id, motivo, versao, com_versao}, erros)`.

    - `loja_id`: um uuid4 em texto ("Escolha uma loja.");
    - `motivo`: em falta ou `null` → `None` (a rota escolhe-o pela fase da
      loja, `rotas.motivo_por_fase`); senão um dos `MOTIVOS`;
    - `versao`: em falta → `com_versao: False` (o cartão do mapa não conhece
      a versão: a rota lê, grava condicionada e tenta de novo); `null` →
      `(None, True)` ("julgo que ainda não há rota"); um inteiro ≥ 1 →
      `(n, True)`; o resto ("A versão da rota não é válida.") fica `None`,
      com `com_versao: True`.

    Os erros vêm por esta ordem; as outras chaves ignoram-se. Um valor com
    erro fica `None` nos dados.
    """
    _exigir_corpo(corpo)
    erros = {}

    loja_id = corpo.get("loja_id")
    if not e_uuid4(loja_id):
        loja_id = None
        erros["loja_id"] = MENSAGEM_LOJA

    motivo = corpo.get("motivo")
    if motivo is not None and not _e_motivo(motivo):
        motivo = None
        erros["motivo"] = MENSAGEM_MOTIVO

    com_versao = "versao" in corpo
    versao = corpo.get("versao")
    if versao is not None and not _e_versao(versao):
        versao = None
        erros["versao"] = MENSAGEM_VERSAO_INVALIDA

    return {"loja_id": loja_id, "motivo": motivo, "versao": versao, "com_versao": com_versao}, erros


def so_versao(corpo: dict):
    """O corpo do `recalcular` e do `otimizar`: `({"versao": n}, {})`, com a
    versão obrigatória (um inteiro ≥ 1), ou `({}, {"versao": erro})`. As
    outras chaves ignoram-se."""
    _exigir_corpo(corpo)
    versao = corpo.get("versao")
    if not _e_versao(versao):
        return {}, {"versao": MENSAGEM_VERSAO_OBRIGATORIA}
    return {"versao": versao}, {}


def alteracao(corpo: dict):
    """O corpo do `PATCH /rotas/{data}`: `(dados, erros)` só com as chaves enviadas.

    Os dados e os erros vêm pela ordem de `CHAVES_ALTERACAO` (os erros
    `paragens.<id>…` no lugar de `paragens`, pela ordem do corpo); as chaves
    desconhecidas ignoram-se. Um valor com erro não entra nos dados.

    - `versao`: obrigatória, um inteiro ≥ 1;
    - `hora_saida`, `hora_regresso_limite`: "HH:MM" (vazia: "Indique a
      hora."). Não se comparam aqui: a rota junta-as com as guardadas e
      chama `coerencia_horas`;
    - `inicio`, `fim`: `null` (a fábrica das definições) ou `{lat, lng}`,
      arredondados às 6 casas antes de se verem contra Portugal; as outras
      chaves do ponto ignoram-se;
    - `evitar_portagens`: `true`/`false`;
    - `ordem`, `retirar`: listas de uuid4 sem repetidos. Os ids de
      `retirar` saem da `ordem` (correção "T3.4 / T3.20": o retirar ganha,
      como o `juntarAlteracoes` do browser);
    - `paragens`: `{id: {motivo?, tempo_servico_min?, manter_fechada?,
      nao_cabe?}}`, com as chaves uuid4 e só esses quatro campos (os do
      terreno e os outros ignoram-se). `nao_cabe` só aceita `false` ("Pôr na
      rota"). Uma paragem que também vem em `retirar` não se altera ("Esta
      paragem vai ser retirada.");
    - `estado`: só `"planeada"` ("Guardar rota").
    """
    _exigir_corpo(corpo)
    a_retirar = _ids_em(corpo.get("retirar"))
    dados = {}
    erros = {}

    for chave in CHAVES_ALTERACAO:
        if chave == "versao":
            versao, erros_versao = so_versao(corpo)
            dados.update(versao)
            erros.update(erros_versao)
        elif chave == "paragens":
            if chave in corpo:
                paragens, erros_paragens = _paragens(corpo[chave], a_retirar)
                if paragens is not None:
                    dados[chave] = paragens
                erros.update(erros_paragens)
        elif chave in corpo:
            valor, erro = _VALIDAR[chave](corpo[chave])
            if erro is None:
                dados[chave] = valor
            else:
                erros[chave] = erro

    if "ordem" in dados and "retirar" in dados:
        retiradas = set(dados["retirar"])
        dados["ordem"] = [id_ for id_ in dados["ordem"] if id_ not in retiradas]

    return dados, erros


def coerencia_horas(saida: str, regresso: str) -> dict:
    """`{"hora_regresso_limite": erro}` se o regresso limite não for depois da
    saída (a mesma hora também é erro), senão `{}`.

    Recebe os valores do dia já juntos com os guardados, cada um "HH:MM"
    válido ("HH:MM" tem largura fixa: comparar o texto é comparar a hora). O
    resto é um erro de programação: `ValueError`.
    """
    for valor in (saida, regresso):
        if not isinstance(valor, str) or janelas.hora(valor) != (valor, None):
            raise ValueError(f"A coerência compara horas já validadas (HH:MM), não {valor!r}.")
    if regresso <= saida:
        return {"hora_regresso_limite": MENSAGEM_COERENCIA_HORAS}
    return {}


def _e_versao(valor) -> bool:
    """Um inteiro ≥ 1 do JSON, de 64 bits (nunca um bool, `1.0` nem `"1"`)."""
    return e_inteiro_json(valor) and valor >= 1


def _e_motivo(valor) -> bool:
    return isinstance(valor, str) and valor in MOTIVOS


def _hora(valor):
    hora, erro = janelas.hora(valor)
    if hora is None and erro is None:
        return None, MENSAGEM_HORA_VAZIA
    return hora, erro


def _ponto(valor):
    """`null` (a fábrica) ou `{lat, lng}` às 6 casas, em Portugal continental."""
    if valor is None:
        return None, None
    if not isinstance(valor, dict):
        return None, MENSAGEM_PONTO
    lat = valor.get("lat")
    lng = valor.get("lng")
    if not e_numero_json(lat):
        return None, MENSAGEM_LATITUDE
    if not e_numero_json(lng):
        return None, MENSAGEM_LONGITUDE
    lat = arredondar(lat, 6)
    lng = arredondar(lng, 6)
    if not (contem_latitude(lat) and contem_longitude(lng)):
        return None, MENSAGEM_PORTUGAL
    return {"lat": lat, "lng": lng}, None


def _sim_ou_nao(valor):
    return (valor, None) if type(valor) is bool else (None, MENSAGEM_SIM_OU_NAO)


def _lista_de_ids(valor, mensagem: str):
    """Uma lista nova de uuid4 sem repetidos. Os uuid4 veem-se antes dos
    repetidos: um elemento que não se pode pôr num conjunto nunca chega lá."""
    if not isinstance(valor, list) or not all(e_uuid4(id_) for id_ in valor) or len(set(valor)) != len(valor):
        return None, mensagem
    return list(valor), None


def _estado(valor):
    return (valor, None) if isinstance(valor, str) and valor == "planeada" else (None, MENSAGEM_ESTADO)


def _motivo(valor):
    return (valor, None) if _e_motivo(valor) else (None, MENSAGEM_MOTIVO)


def _tempo_servico(valor):
    if e_inteiro_json(valor) and TEMPO_SERVICO_MINIMO <= valor <= TEMPO_SERVICO_MAXIMO:
        return valor, None
    return None, MENSAGEM_TEMPO_SERVICO


def _nao_cabe(valor):
    return (False, None) if valor is False else (None, MENSAGEM_NAO_CABE)


_VALIDAR = {
    "hora_saida": _hora,
    "hora_regresso_limite": _hora,
    "inicio": _ponto,
    "fim": _ponto,
    "evitar_portagens": _sim_ou_nao,
    "ordem": lambda valor: _lista_de_ids(valor, MENSAGEM_ORDEM),
    "retirar": lambda valor: _lista_de_ids(valor, MENSAGEM_RETIRAR),
    "estado": _estado,
}

_VALIDAR_PARAGEM = {
    "motivo": _motivo,
    "tempo_servico_min": _tempo_servico,
    "manter_fechada": _sim_ou_nao,
    "nao_cabe": _nao_cabe,
}


def _paragens(valor, a_retirar: set):
    """`(alterações por id, erros)` das `paragens` do PATCH.

    Um valor que não é um objeto, ou com uma chave que não é um uuid4, recusa
    tudo em `paragens` (sem repetir a chave no erro) e os dados ficam `None`.
    Depois, por cada paragem, pela ordem do corpo: a que vai ser retirada ou
    cujas alterações não são um objeto fica de fora, com o erro em
    `paragens.<id>`; nas outras, cada campo com erro fica em
    `paragens.<id>.<campo>`.
    """
    if not isinstance(valor, dict) or not all(e_uuid4(id_) for id_ in valor):
        return None, {"paragens": MENSAGEM_PARAGENS}

    dados = {}
    erros = {}
    for id_, alteracoes in valor.items():
        if id_ in a_retirar:
            erros[f"paragens.{id_}"] = MENSAGEM_VAI_SER_RETIRADA
            continue
        if not isinstance(alteracoes, dict):
            erros[f"paragens.{id_}"] = MENSAGEM_PARAGENS
            continue
        campos = {}
        for campo in CHAVES_PARAGEM:
            if campo in alteracoes:
                novo, erro = _VALIDAR_PARAGEM[campo](alteracoes[campo])
                if erro is None:
                    campos[campo] = novo
                else:
                    erros[f"paragens.{id_}.{campo}"] = erro
        dados[id_] = campos
    return dados, erros


def _ids_em(valor) -> set:
    """Os uuid4 de uma lista (mesmo com repetidos ou outros valores), para
    ver as paragens que também vêm em `retirar`; o que não for lista → vazio."""
    if not isinstance(valor, list):
        return set()
    return {id_ for id_ in valor if e_uuid4(id_)}


def _exigir_corpo(corpo):
    # O `corpo_json` só deixa passar objetos JSON: outra coisa é um erro de programação.
    if not isinstance(corpo, dict):
        raise TypeError(f"O corpo do pedido é um dicionário, não {type(corpo).__name__}.")


def _exigir_dia(hoje):
    # Um `datetime` também é um `date` (subclasse), e o instante UTC daria o dia errado.
    if type(hoje) is not date:
        raise TypeError("O hoje das rotas é um datetime.date.")
