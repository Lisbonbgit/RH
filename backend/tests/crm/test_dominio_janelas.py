"""O horário de receção de uma loja: duas janelas HH:MM opcionais
(crm/dominio/janelas.py).

Porta de src/Dominio/Lojas/Janelas.php, com todos os casos do
tests/Unit/Dominio/JanelasTest.php do CRM autónomo (mesmos nomes nos `ids`):
início e fim vão juntos, o início vem antes do fim, e a janela 2 exige a
janela 1 e começa depois do fim dela.

Armadilhas do Python (plano §10; dossiê §2.1 e §5.6): `re.fullmatch` e `[0-9]`
(o `$` aceita um "\\n" final e o `\\d` aceita algarismos árabes), `bool` não é
uma hora, e o `+=` dos arrays do PHP não substitui um erro que já lá está (é o
`setdefault`, não a atribuição). Os erros vêm pela ordem em que o PHP os junta.
"""
import pytest

from crm.dominio.janelas import CAMPOS, erros, hora

FORMATO = "A hora tem de estar no formato HH:MM."


def _janelas(inicio1, fim1, inicio2, fim2):
    return {"janela1_inicio": inicio1, "janela1_fim": fim1, "janela2_inicio": inicio2, "janela2_fim": fim2}


def _itens(resultado):
    # O assertSame do PHPUnit compara também a ordem das chaves; o == dos
    # dicionários do Python não.
    return list(resultado.items())


def test_os_campos_sao_as_quatro_horas_pela_ordem():
    assert CAMPOS == ("janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim")


# --- hora: JanelasTest.php ---


@pytest.mark.parametrize("valor", ["00:00", "09:30", "23:59"], ids=["meia-noite", "manhã", "última do dia"])
def test_aceita_horas_hh_mm(valor):
    assert hora(valor) == (valor, None)


@pytest.mark.parametrize("valor", [None, ""], ids=["nula", "vazia (campo limpo no formulário)"])
def test_sem_hora_fica_nula(valor):
    assert hora(valor) == (None, None)


@pytest.mark.parametrize(
    "valor",
    ["9:30", "24:00", "10:60", "10:00:00", " 10:00", "10:00\n", "10", 1000, True, ["10:00"]],
    ids=[
        "sem zero à esquerda",
        "24:00",
        "minutos a mais",
        "com segundos",
        "com espaço",
        "com quebra de linha no fim",
        "só a hora",
        "número",
        "verdadeiro",
        "lista",
    ],
)
def test_recusa_o_que_nao_for_hh_mm(valor):
    assert hora(valor) == (None, FORMATO)


# --- hora: armadilhas do Python ---


@pytest.mark.parametrize(
    "valor",
    [
        "١٠:٠٠",
        "１０:００",
        "0٩:30",
        "09:3٠",
        "1０:00",
        "10:00\r",
        "10:00 ",
        "\u00a010:00",
        "10:00\t",
        "\n10:00",
        "10h00",
        "10.00",
        "10 :00",
        "-1:00",
        "+1:00",
        "10:0",
        "010:00",
        "\u00a0",
        "10:00\n10:00",
        False,
        0,
        10.0,
        {},
        {"hora": "10:00"},
        ("10:00",),
    ],
    ids=[
        "algarismos árabes (o \\d aceitava)",
        "algarismos de largura total",
        "algarismo árabe depois de um 0 (o \\d aceitava)",
        "algarismo árabe nos minutos",
        "algarismo de largura total depois de um 1",
        "retorno do carro no fim",
        "espaço no fim (não se apara)",
        "espaço sem quebra no início (não se apara)",
        "tabulação no fim",
        "quebra de linha no início",
        "com h",
        "com ponto",
        "espaço antes dos dois pontos",
        "negativa",
        "com sinal",
        "um só algarismo nos minutos",
        "três algarismos na hora",
        "só um espaço sem quebra",
        "duas horas em linhas",
        "falso",
        "zero",
        "número decimal",
        "objeto vazio",
        "objeto",
        "tuplo",
    ],
)
def test_recusa_tambem_as_armadilhas_do_python(valor):
    # Só o "" vazio é "sem hora": a hora não se apara, e um U+00A0 sozinho é
    # uma hora mal escrita.
    assert hora(valor) == (None, FORMATO)


def test_aceita_exatamente_as_1440_horas_do_dia():
    # Todas as combinações de dois algarismos: só 00–23 e 00–59 passam.
    aceites = []
    for h in range(100):
        for m in range(100):
            texto = f"{h:02d}:{m:02d}"
            valor, erro = hora(texto)
            if erro is None:
                assert valor == texto
                aceites.append((h, m))
            else:
                assert (valor, erro) == (None, FORMATO)
    assert aceites == [(h, m) for h in range(24) for m in range(60)]


def test_a_hora_aceite_e_o_proprio_texto():
    assert hora("07:05")[0] == "07:05"
    assert type(hora("07:05")[0]) is str


# --- erros: JanelasTest.php ---


@pytest.mark.parametrize(
    "janelas",
    [
        {},
        _janelas(None, None, None, None),
        _janelas("10:00", "13:00", None, None),
        _janelas("10:00", "13:00", "15:00", "19:00"),
        _janelas("10:00", "13:00", "13:01", "19:00"),
        _janelas("10:00", "10:01", None, None),
    ],
    ids=[
        "sem janelas",
        "todas nulas",
        "só a janela 1",
        "as duas",
        "a 2 começa um minuto depois da 1",
        "um minuto de janela",
    ],
)
def test_aceita_janelas_coerentes(janelas):
    assert erros(janelas) == {}


@pytest.mark.parametrize(
    "janelas, esperado",
    [
        (_janelas("10:00", None, None, None), [("janela1_fim", "Indique também o fim.")]),
        (_janelas(None, "13:00", None, None), [("janela1_inicio", "Indique também o início.")]),
        (_janelas("10:00", "10:00", None, None), [("janela1_fim", "O fim tem de ser depois do início.")]),
        (_janelas("13:00", "10:00", None, None), [("janela1_fim", "O fim tem de ser depois do início.")]),
        (_janelas(None, None, "15:00", "19:00"), [("janela2_inicio", "Preencha primeiro a janela 1.")]),
        (_janelas("10:00", "13:00", "15:00", None), [("janela2_fim", "Indique também o fim.")]),
        (_janelas("10:00", "13:00", "19:00", "15:00"), [("janela2_fim", "O fim tem de ser depois do início.")]),
        (
            _janelas("10:00", "13:00", "13:00", "19:00"),
            [("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1.")],
        ),
        (
            _janelas("10:00", "13:00", "12:00", "19:00"),
            [("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1.")],
        ),
        (
            _janelas("15:00", "19:00", "10:00", "13:00"),
            [("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1.")],
        ),
        (_janelas("10:00", None, "15:00", "19:00"), [("janela1_fim", "Indique também o fim.")]),
    ],
    ids=[
        "janela 1 só com o início",
        "janela 1 só com o fim",
        "janela 1 com início igual ao fim",
        "janela 1 com início depois do fim",
        "janela 2 sem a janela 1",
        "janela 2 só com o início",
        "janela 2 com início depois do fim",
        "janela 2 a começar no fim da 1",
        "janela 2 sobreposta à 1",
        "janela 2 antes da 1",
        "janela 1 incompleta e janela 2 completa",
    ],
)
def test_recusa_janelas_incoerentes(janelas, esperado):
    assert _itens(erros(janelas)) == esperado


def test_as_chaves_que_faltam_contam_como_nulas():
    assert erros({"janela1_inicio": "10:00", "nome": "Café Central"}) == {"janela1_fim": "Indique também o fim."}


# --- erros: armadilhas do Python e casos que o JanelasTest não cobre ---


@pytest.mark.parametrize(
    "janelas, esperado",
    [
        (_janelas(None, None, None, "19:00"), [("janela2_inicio", "Indique também o início.")]),
        (
            _janelas(None, None, "15:00", None),
            [("janela2_fim", "Indique também o fim."), ("janela2_inicio", "Preencha primeiro a janela 1.")],
        ),
        (
            _janelas("10:00", "13:00", "12:00", None),
            [
                ("janela2_fim", "Indique também o fim."),
                ("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1."),
            ],
        ),
        (
            _janelas("10:00", "13:00", "13:00", "13:00"),
            [
                ("janela2_fim", "O fim tem de ser depois do início."),
                ("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1."),
            ],
        ),
        (_janelas("10:00", "13:00", None, "12:00"), [("janela2_inicio", "Indique também o início.")]),
        (
            _janelas(None, "13:00", "10:00", "12:00"),
            [
                ("janela1_inicio", "Indique também o início."),
                ("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1."),
            ],
        ),
        (_janelas(None, "13:00", "15:00", "19:00"), [("janela1_inicio", "Indique também o início.")]),
        (
            _janelas("13:00", "10:00", "09:00", "12:00"),
            [
                ("janela1_fim", "O fim tem de ser depois do início."),
                ("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1."),
            ],
        ),
        (
            _janelas("10:00", None, None, "19:00"),
            [("janela1_fim", "Indique também o fim."), ("janela2_inicio", "Indique também o início.")],
        ),
        (_janelas("00:00", "23:59", None, None), []),
        (_janelas("09:59", "10:00", None, None), []),
        (_janelas("00:00", "11:59", "12:00", "23:59"), []),
        (_janelas("10:00", "13:00", "23:58", "23:59"), []),
    ],
    ids=[
        "janela 2 só com o fim: o início em falta não é trocado (o += do PHP)",
        "janela 2 só com o início e sem a janela 1: os dois erros, fim primeiro",
        "janela 2 sobreposta e sem fim: os dois erros, fim primeiro",
        "janela 2 vazia no fim da 1: os dois erros",
        "janela 2 só com o fim, antes do fim da 1: não se compara",
        "janela 1 só com o fim e janela 2 antes dele",
        "janela 1 só com o fim e janela 2 depois dele",
        "janela 1 ao contrário e janela 2 antes do fim dela",
        "uma ponta em cada janela",
        "o dia inteiro",
        "09:59 vem antes de 10:00 (texto com largura fixa)",
        "duas janelas a cobrir o dia",
        "a 2 no último minuto",
    ],
)
def test_combina_os_erros_como_o_php(janelas, esperado):
    assert _itens(erros(janelas)) == esperado


def test_compara_as_horas_como_os_minutos_do_dia():
    # As horas já validadas têm largura fixa: comparar o texto é comparar os
    # minutos. Todas as janelas 1 de meia em meia hora.
    horas = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
    for inicio in horas:
        for fim in horas:
            resultado = erros(_janelas(inicio, fim, None, None))
            if _minutos(inicio) < _minutos(fim):
                assert resultado == {}, (inicio, fim)
            else:
                assert resultado == {"janela1_fim": "O fim tem de ser depois do início."}, (inicio, fim)


def test_a_janela_2_comeca_estritamente_depois_do_fim_da_1():
    horas = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
    for inicio2 in horas[1:-1]:
        resultado = erros(_janelas("00:00", "12:00", inicio2, "23:59"))
        if _minutos(inicio2) > _minutos("12:00"):
            assert resultado == {}, inicio2
        else:
            assert resultado == {"janela2_inicio": "A janela 2 tem de começar depois do fim da janela 1."}, inicio2


def test_nulas_e_chaves_em_falta_sao_o_mesmo():
    assert erros({"janela2_inicio": "15:00", "janela2_fim": "19:00"}) == erros(
        _janelas(None, None, "15:00", "19:00")
    )


def test_ignora_as_outras_chaves_da_loja():
    loja = {**_janelas("10:00", "13:00", None, None), "id": "x", "nome": "Café", "janelas": [{"inicio": "x"}]}
    assert erros(loja) == {}


def test_nao_mexe_na_loja_recebida():
    loja = _janelas("10:00", None, "15:00", None)
    copia = dict(loja)
    erros(loja)
    assert loja == copia


def test_devolve_um_dicionario_novo_em_cada_chamada():
    a = erros({})
    a["janela1_fim"] = "x"
    assert erros({}) == {}


@pytest.mark.parametrize(
    "valor",
    [1000, True, False, 0, 10.0, ["10:00"], {"h": "10:00"}],
    ids=["número", "verdadeiro", "falso", "zero", "decimal", "lista", "objeto"],
)
def test_as_horas_tem_de_vir_validadas(valor):
    # O PHP (strict_types) rebentava com TypeError no `?string` da função que
    # lê as quatro horas: quem chama valida primeiro com `hora`. Aqui também
    # rebenta, em vez de comparar um número com texto em silêncio.
    with pytest.raises(TypeError):
        erros({"janela1_inicio": valor, "janela1_fim": "13:00"})
    with pytest.raises(TypeError):
        erros({"janela2_fim": valor})


def _minutos(texto):
    h, m = texto.split(":")
    return int(h) * 60 + int(m)
