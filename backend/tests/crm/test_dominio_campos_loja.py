"""Os campos opcionais de uma loja que se validam sozinhos
(crm/dominio/campos_loja.py).

Porta de src/Dominio/Lojas/CamposLoja.php do CRM autónomo. O PHP não tinha um
teste só para esta classe: os casos vêm do ValidadorLojaCriacaoTest.php (e os
do campo do ValidadorLojaAlteracaoTest.php), com os mesmos nomes nos `ids`,
chamando aqui cada função diretamente. O ValidadorLoja (T2.5/T2.6) junta-as.

Cada função devolve `(valor normalizado, erro)`; vazio ("" ou só espaços,
também os Unicode) ou `None` fica `None`, e o que não for texto é um erro.

Armadilhas do Python (plano §10; dossiê §2.1 e §5.2): `[0-9]` e
`re.fullmatch` (o `\\d` aceita algarismos árabes e o `$` um "\\n" final);
`mb_strlen` → `len`, `strlen` → bytes UTF-8; `bool` e números não são texto;
`array_is_list` → `isinstance(x, list)`.
"""
import pytest

from crm.dominio.campos_loja import (
    DIAS,
    SITE_MAXIMO,
    codigo_postal,
    dias_fechada,
    instagram,
    notas,
    site,
    telefone,
    texto,
)

TELEFONE = "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)."
POSTAL = "O código postal tem de ter o formato 0000-000."
MENSAGEM_DIAS = "Os dias têm de ser seg, ter, qua, qui, sex, sab ou dom."
TEXTO = "Tem de ser texto."
NOTAS = "As notas são demasiado compridas."
SITE = "O site tem de ser um endereço válido (ex.: https://exemplo.pt)."
INSTAGRAM = "O Instagram tem de ser um perfil válido (ex.: @purplehouse)."

# Os rótulos e tamanhos do ValidadorLoja::TEXTOS (a tabela fica na T2.5).
MORADA = ("A morada", 255)
LOCALIDADE = ("A localidade", 100)
PESSOA = ("A pessoa de contacto", 100)


# --- texto (morada, localidade, pessoa de contacto) ---


@pytest.mark.parametrize(
    "valor, rotulo_maximo, guardado",
    [
        ("m" * 255, MORADA, "m" * 255),
        ("  ", MORADA, None),
        ("\u00a0", MORADA, None),
        (None, MORADA, None),
        (" Rua do Salitre 1 ", MORADA, "Rua do Salitre 1"),
        ("\u3000Lisboa\u00a0", LOCALIDADE, "Lisboa"),
        ("l" * 100, LOCALIDADE, "l" * 100),
        ("p" * 100, PESSOA, "p" * 100),
        (" Ana ", PESSOA, "Ana"),
    ],
    ids=[
        "morada com 255 caracteres",
        "morada vazia",
        "morada só com um espaço sem quebra",
        "morada nula",
        "morada sem os espaços das pontas",
        "localidade sem os espaços Unicode nas pontas",
        "localidade com 100 caracteres",
        "pessoa de contacto com 100 caracteres",
        "pessoa de contacto sem os espaços das pontas",
    ],
)
def test_texto_normaliza(valor, rotulo_maximo, guardado):
    assert texto(valor, *rotulo_maximo) == (guardado, None)


@pytest.mark.parametrize(
    "valor, rotulo_maximo, erro",
    [
        ("m" * 256, MORADA, "A morada tem no máximo 255 caracteres."),
        ("l" * 101, LOCALIDADE, "A localidade tem no máximo 100 caracteres."),
        ("p" * 101, PESSOA, "A pessoa de contacto tem no máximo 100 caracteres."),
        (["Rua"], MORADA, TEXTO),
    ],
    ids=[
        "morada com 256 caracteres",
        "localidade com 101 caracteres",
        "pessoa de contacto com 101 caracteres",
        "morada que não é texto",
    ],
)
def test_texto_recusa(valor, rotulo_maximo, erro):
    assert texto(valor, *rotulo_maximo) == (None, erro)


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("é" * 255, "é" * 255),
        ("😀" * 255, "😀" * 255),
        (" " + "m" * 255 + "\u00a0", "m" * 255),
        ("\ufeffRua\u2028", "Rua"),
        ("Rua  do\u00a0Salitre", "Rua  do\u00a0Salitre"),
        ("", None),
        ("\t\u00a0 \ufeff", None),
    ],
    ids=[
        "255 letras acentuadas (conta caracteres, não bytes)",
        "255 emojis",
        "conta depois de aparar",
        "BOM e separador de linha nas pontas",
        "os espaços do meio ficam",
        "vazia",
        "só espaços misturados",
    ],
)
def test_texto_armadilhas_aceites(valor, guardado):
    assert texto(valor, *MORADA) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    [True, False, 0, 42, 1.5, {}, {"rua": "x"}, [], ("Rua",)],
    ids=["verdadeiro", "falso", "zero", "número", "decimal", "objeto vazio", "objeto", "lista vazia", "tuplo"],
)
def test_texto_o_que_nao_e_texto_e_um_erro(valor):
    assert texto(valor, *MORADA) == (None, TEXTO)


def test_texto_mensagem_com_o_rotulo_e_o_maximo():
    assert texto("abcdef", "O campo", 5) == (None, "O campo tem no máximo 5 caracteres.")
    assert texto("abcde", "O campo", 5) == ("abcde", None)
    assert texto("é" * 256, *MORADA) == (None, "A morada tem no máximo 255 caracteres.")


# --- notas ---


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("n" * 65535, "n" * 65535),
        ("", None),
        (None, None),
        (" Descarga pela porta lateral.\nFérias em agosto. ", "Descarga pela porta lateral.\nFérias em agosto."),
    ],
    ids=["notas com 65 535 bytes", "notas vazias", "notas nulas", "notas com mudança de linha no meio"],
)
def test_notas_normaliza(valor, guardado):
    assert notas(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor, erro",
    [("é" * 32768, NOTAS), (42, TEXTO), (False, TEXTO)],
    ids=["notas com mais de 65 535 bytes", "notas que não são texto", "notas falsas"],
)
def test_notas_recusa(valor, erro):
    assert notas(valor) == (None, erro)


@pytest.mark.parametrize(
    "valor, aceite",
    [
        ("é" * 32767 + "n", True),
        ("é" * 32767 + "é", False),
        ("😀" * 16383 + "nnn", True),
        ("😀" * 16383 + "nnnn", False),
        ("n" * 65536, False),
        (" " + "n" * 65535 + " ", True),
        ("\u00a0" + "n" * 65535, True),
    ],
    ids=[
        "65 535 bytes com acentos",
        "65 536 bytes com acentos",
        "65 535 bytes com emojis",
        "65 536 bytes com emojis",
        "65 536 letras",
        "conta depois de aparar",
        "o espaço sem quebra das pontas não conta",
    ],
)
def test_notas_contam_bytes_utf8(valor, aceite):
    resultado = notas(valor)
    if aceite:
        assert resultado == (valor.strip("\u00a0 "), None)
    else:
        assert resultado == (None, NOTAS)


def test_notas_com_um_surrogate_sozinho_nao_rebentam():
    # O json.loads do Python aceita "\ud800" sozinho (o json_decode do PHP
    # recusava: "Single unpaired UTF-16 surrogate"), e o str.encode("utf-8")
    # rebentava com UnicodeEncodeError (500). Conta 3 bytes, como no WTF-8.
    sozinho = "\ud800"
    assert notas("a" + sozinho + "b") == ("a" + sozinho + "b", None)
    assert notas(sozinho * 21845) == (sozinho * 21845, None)
    assert notas(sozinho * 21846) == (None, NOTAS)


@pytest.mark.parametrize(
    "valor",
    [True, 0, 1.5, [], ["nota"], {}, {"a": "b"}],
    ids=["verdadeiro", "zero", "decimal", "lista vazia", "lista", "objeto vazio", "objeto"],
)
def test_notas_o_que_nao_e_texto_e_um_erro(valor):
    assert notas(valor) == (None, TEXTO)


# --- código postal ---


@pytest.mark.parametrize(
    "valor, guardado",
    [(" 1250-198 ", "1250-198"), ("", None), (None, None), ("1250-198", "1250-198"), ("0000-000", "0000-000")],
    ids=["código postal com espaços nas pontas", "código postal vazio", "código postal nulo", "certo", "zeros"],
)
def test_codigo_postal_normaliza(valor, guardado):
    assert codigo_postal(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    ["1250198", "1250-19", "abcd-efg", "١٢٥٠-١٩٨", 1250198, "1250"],
    ids=[
        "código postal sem hífen",
        "código postal curto",
        "código postal com letras",
        "código postal com algarismos árabes",
        "código postal em número",
        "código postal só com 4 algarismos",
    ],
)
def test_codigo_postal_recusa(valor):
    assert codigo_postal(valor) == (None, POSTAL)


@pytest.mark.parametrize(
    "valor",
    [
        "１２５０-１９８",
        "۱۲۵۰-۱۹۸",
        "1250–198",
        "1250 198",
        "1250-1981",
        "01250-198",
        "1250-198\n1250-198",
        "1250 -198",
        "1250-\u00a0198",
        True,
        False,
        0,
        12.5,
        ["1250-198"],
        {"cp": "1250-198"},
    ],
    ids=[
        "algarismos de largura total",
        "algarismos persas",
        "com travessão em vez de hífen",
        "com espaço em vez de hífen",
        "algarismos a mais no fim",
        "algarismos a mais no início",
        "dois códigos em linhas",
        "espaço antes do hífen",
        "espaço sem quebra depois do hífen",
        "verdadeiro",
        "falso",
        "zero",
        "decimal",
        "lista",
        "objeto",
    ],
)
def test_codigo_postal_armadilhas_do_python(valor):
    # O que não é texto dá a mensagem do formato, não "Tem de ser texto.".
    assert codigo_postal(valor) == (None, POSTAL)


def test_codigo_postal_a_mudanca_de_linha_final_sai_ao_aparar():
    # O "\n" final é um espaço das pontas: sai ao aparar, antes de verificar
    # o formato (como no PHP).
    assert codigo_postal("1250-198\n") == ("1250-198", None)
    assert codigo_postal("\ufeff1250-198\u2028") == ("1250-198", None)


# --- telefone ---


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("912345678", "912345678"),
        ("212 345 678", "212 345 678"),
        ("+351 912 345 678 901", "+351 912 345 678 901"),
        ("+ 351 912345678", "+351 912345678"),
        ("00351 912 345 678", "00351 912 345 678"),
        ("   ", None),
        (None, None),
        (" +351  912 345   678 ", "+351 912 345 678"),
        (" 912  345 678 ", "912 345 678"),
        ("", None),
    ],
    ids=[
        "telefone só com algarismos",
        "telefone com 9 algarismos",
        "telefone com 15 algarismos",
        "telefone com espaço depois do +",
        "telefone com 00 em vez de +",
        "telefone vazio",
        "telefone nulo",
        "telefone com espaços seguidos e nas pontas (loja completa)",
        "telefone com espaços seguidos (alteração)",
        "telefone vazio (alteração)",
    ],
)
def test_telefone_normaliza(valor, guardado):
    assert telefone(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    [
        "91234567",
        "+351 912 345 678 9012",
        "912-345-678",
        "(+351) 912345678",
        "91234567a",
        "351+912345678",
        "++351912345678",
        "+",
        "912\t345678",
        912345678,
        "1234",
    ],
    ids=[
        "telefone com 8 algarismos",
        "telefone com 16 algarismos",
        "telefone com hífens",
        "telefone com parênteses",
        "telefone com letras",
        "telefone com + no meio",
        "telefone com dois +",
        "telefone só com +",
        "telefone com tabulação no meio",
        "telefone em número",
        "telefone curto (alteração)",
    ],
)
def test_telefone_recusa(valor):
    assert telefone(valor) == (None, TELEFONE)


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("+  351 912345678", "+351 912345678"),
        (" + 351 912345678", "+351 912345678"),
        ("+351 912  345 678", "+351 912 345 678"),
        ("912345678\n", "912345678"),
        ("\u00a0912 345 678\u3000", "912 345 678"),
        ("000000000", "000000000"),
        ("123456789012345", "123456789012345"),
        ("+1 2 3 4 5 6 7 8 9", "+1 2 3 4 5 6 7 8 9"),
        ("9" + " " * 50 + "12345678", "9 12345678"),
        ("\u00a0", None),
    ],
    ids=[
        "dois espaços depois do +: juntam-se e depois saem",
        "espaço antes do + sai ao aparar",
        "espaços seguidos no meio",
        "mudança de linha no fim sai ao aparar",
        "espaços Unicode nas pontas",
        "nove zeros",
        "15 algarismos seguidos",
        "um espaço entre cada algarismo",
        "muitos espaços seguidos",
        "só um espaço sem quebra (é vazio)",
    ],
)
def test_telefone_armadilhas_aceites(valor, guardado):
    assert telefone(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    [
        "٩١٢٣٤٥٦٧٨",
        "９１２３４５６７８",
        "912345678٩",
        "912 345 678 ９",
        "912\u00a0345\u00a0678",
        "912\n345678",
        "912 \t345678",
        "912\u00a0\u00a0345678",
        "912 345 678 +",
        "+ +351912345678",
        "+ ",
        "+351 912 345 678 9012 ",
        "1234567890123456",
        "912.345.678",
        "912/345678",
        "#912345678",
        True,
        False,
        912345678.0,
        ["912345678"],
        {"numero": "912345678"},
    ],
    ids=[
        "algarismos árabes (o \\d aceitava)",
        "algarismos de largura total",
        "9 algarismos e um árabe (o \\d aceitava o formato)",
        "9 algarismos e um de largura total",
        "espaço sem quebra no meio",
        "mudança de linha no meio",
        "espaço e tabulação seguidos (só os espaços se juntam)",
        "dois espaços sem quebra seguidos",
        "+ no fim",
        "+ e espaço antes de outro +",
        "só + e espaço",
        "16 algarismos com espaço no fim",
        "16 algarismos seguidos",
        "com pontos",
        "com barra",
        "com cardinal",
        "verdadeiro",
        "falso",
        "decimal",
        "lista",
        "objeto",
    ],
)
def test_telefone_armadilhas_recusadas(valor):
    assert telefone(valor) == (None, TELEFONE)


def test_telefone_tem_de_ter_entre_9_e_15_algarismos():
    for n in range(1, 21):
        valor = "1" * n
        esperado = (valor, None) if 9 <= n <= 15 else (None, TELEFONE)
        assert telefone(valor) == esperado, n
        assert telefone("+" + valor) == (("+" + valor, None) if 9 <= n <= 15 else (None, TELEFONE)), n


# --- dias fechada ---


def test_os_dias_sao_os_da_semana_pela_ordem():
    assert DIAS == ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


@pytest.mark.parametrize(
    "valor, guardado",
    [
        (["dom", "qua", "seg"], ["seg", "qua", "dom"]),
        (["seg", "ter", "qua", "qui", "sex", "sab", "dom"], ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]),
        ([], []),
        (None, []),
        (["dom", "sab"], ["sab", "dom"]),
        (["seg"], ["seg"]),
        (["dom", "sab", "sex", "qui", "qua", "ter", "seg"], ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]),
    ],
    ids=[
        "dias fechada pela ordem da semana",
        "todos os dias",
        "sem dias fechada",
        "dias fechada nulos",
        "fim de semana ao contrário (loja completa)",
        "um dia",
        "a semana ao contrário",
    ],
)
def test_dias_fechada_normaliza(valor, guardado):
    assert dias_fechada(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor, erro",
    [
        (["domingo"], MENSAGEM_DIAS),
        (["Sab"], MENSAGEM_DIAS),
        ([7], MENSAGEM_DIAS),
        ("sab,dom", MENSAGEM_DIAS),
        ({"a": "sab"}, MENSAGEM_DIAS),
        (["sab", "dom", "sab"], "Há dias repetidos."),
        (["seg", "seg"], "Há dias repetidos."),
    ],
    ids=[
        "dia desconhecido",
        "dia com maiúscula",
        "dia em número",
        "dias num texto",
        "dias num objeto",
        "dias repetidos",
        "dias repetidos (alteração)",
    ],
)
def test_dias_fechada_recusa(valor, erro):
    assert dias_fechada(valor) == (None, erro)


@pytest.mark.parametrize(
    "valor",
    [
        {},
        {"0": "sab"},
        ("sab",),
        "sab",
        "",
        True,
        0,
        [True],
        [None],
        [0],
        [6],
        [["sab"]],
        [{"dia": "sab"}],
        ["sab "],
        [" sab"],
        ["sáb"],
        ["SAB"],
        ["sab\n"],
        [""],
        ["sab", "sab", "domingo"],
        ["seg", 1],
    ],
    ids=[
        "objeto vazio (o json_decode associativo do PHP dava [])",
        "objeto com chave 0 (o PHP dava uma lista)",
        "tuplo",
        "um dia em texto",
        "texto vazio",
        "verdadeiro",
        "zero",
        "lista com verdadeiro",
        "lista com nulo",
        "lista com zero",
        "lista com a posição do sábado",
        "lista dentro da lista",
        "objeto dentro da lista",
        "espaço no fim",
        "espaço no início",
        "com acento",
        "em maiúsculas",
        "mudança de linha no fim",
        "dia vazio",
        "desconhecido e repetido: primeiro o desconhecido",
        "dia certo e número",
    ],
)
def test_dias_fechada_armadilhas_do_python(valor):
    assert dias_fechada(valor) == (None, MENSAGEM_DIAS)


def test_dias_fechada_devolve_uma_lista_nova_e_nao_mexe_na_recebida():
    recebida = ["dom", "seg"]
    guardada, erro = dias_fechada(recebida)
    assert erro is None
    assert guardada == ["seg", "dom"]
    assert type(guardada) is list
    assert recebida == ["dom", "seg"]
    guardada.append("ter")
    assert dias_fechada(None) == ([], None)
    assert dias_fechada([]) == ([], None)
    assert dias_fechada(recebida)[0] is not recebida


def test_dias_fechada_vazios_sao_uma_lista_nova_em_cada_chamada():
    primeira, _ = dias_fechada(None)
    primeira.append("seg")
    assert dias_fechada(None) == ([], None)


# --- site (2026-10-13, a pedido do dono: a ficha da loja com Instagram e site) ---


def test_o_site_guarda_ate_255_caracteres():
    assert SITE_MAXIMO == 255


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("https://exemplo.pt", "https://exemplo.pt"),
        ("http://exemplo.pt", "http://exemplo.pt"),
        ("exemplo.pt", "https://exemplo.pt"),
        ("www.exemplo.pt", "https://www.exemplo.pt"),
        ("exemplo.pt/loja", "https://exemplo.pt/loja"),
        ("exemplo.pt/loja?x=1&y=2#topo", "https://exemplo.pt/loja?x=1&y=2#topo"),
        ("  exemplo.pt  ", "https://exemplo.pt"),
        (" https://exemplo.pt　", "https://exemplo.pt"),
        ("https://exemplo.pt/", "https://exemplo.pt/"),
        ("https://loja.exemplo.com.pt/a/b", "https://loja.exemplo.com.pt/a/b"),
        ("HTTPS://Exemplo.PT/Loja", "https://exemplo.pt/Loja"),
        ("exemplo.pt:8080", "https://exemplo.pt:8080"),
        ("açaí.pt", "https://açaí.pt"),
        ("https://" + "a" * 63 + ".pt", "https://" + "a" * 63 + ".pt"),
        ("https://exemplo.pt/" + "p" * (SITE_MAXIMO - len("https://exemplo.pt/")), "https://exemplo.pt/" + "p" * 236),
        ("", None),
        ("   ", None),
        (None, None),
    ],
    ids=[
        "https",
        "http fica http",
        "só o domínio ganha https://",
        "www sem esquema",
        "domínio com caminho",
        "com query e fragmento",
        "sem os espaços das pontas",
        "sem os espaços Unicode das pontas",
        "com barra no fim",
        "subdomínio e caminho",
        "esquema e máquina ficam em minúsculas, o caminho não",
        "com porto",
        "domínio com acentos",
        "etiqueta com 63 caracteres",
        "255 caracteres",
        "vazio",
        "só espaços",
        "nulo",
    ],
)
def test_site_normaliza(valor, guardado):
    assert site(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    [
        "exemplo",
        "exemplo pt",
        "https://exemplo .pt",
        "https://exem\nplo.pt",
        "exemplo.pt\tloja",
        "https://exemplo.pt/ loja",
        "ftp://exemplo.pt",
        "mailto:loja@exemplo.pt",
        "javascript:alert(1)",
        "https://",
        "https:///exemplo.pt",
        "//exemplo.pt",
        "https://utilizador:senha@exemplo.pt",
        "https://exemplo.pt:abc",
        "https://exemplo.pt:99999",
        "https://192.168.1.1",
        "https://exemplo.pt.",
        "https://-exemplo.pt",
        "https://exemplo-.pt",
        "https://exemplo.p",
        "https://exemplo.123",
        "https://exem_plo.pt",
        "https://" + "a" * 64 + ".pt",
        "https://exemplo.pt/" + "p" * (SITE_MAXIMO - len("https://exemplo.pt/") + 1),
        "exemplo.pt/" + "p" * (SITE_MAXIMO - len("https://exemplo.pt/") + 1),
        "https://exemplo.pt/\x00",
        True,
        0,
        12.5,
        ["https://exemplo.pt"],
        {"url": "https://exemplo.pt"},
    ],
    ids=[
        "sem domínio de topo",
        "com espaço no meio",
        "espaço na máquina",
        "mudança de linha no meio",
        "tabulação",
        "espaço sem quebra no caminho",
        "ftp",
        "mailto",
        "javascript",
        "só o esquema",
        "sem máquina",
        "sem esquema e com duas barras",
        "com utilizador e senha",
        "porto com letras",
        "porto fora do intervalo",
        "endereço IP",
        "ponto no fim",
        "etiqueta a começar por hífen",
        "etiqueta a acabar em hífen",
        "domínio de topo com uma letra",
        "domínio de topo só com algarismos",
        "sublinhado na máquina",
        "etiqueta com 64 caracteres",
        "256 caracteres",
        "256 caracteres depois do https://",
        "carácter de controlo",
        "verdadeiro",
        "zero",
        "decimal",
        "lista",
        "objeto",
    ],
)
def test_site_recusa(valor):
    assert site(valor) == (None, SITE)


# --- instagram ---


@pytest.mark.parametrize(
    "valor, guardado",
    [
        ("@purplehouse", "https://www.instagram.com/purplehouse/"),
        ("purplehouse", "https://www.instagram.com/purplehouse/"),
        ("@purple.house_pt", "https://www.instagram.com/purple.house_pt/"),
        ("PurpleHouse", "https://www.instagram.com/PurpleHouse/"),
        ("  @purplehouse  ", "https://www.instagram.com/purplehouse/"),
        (" purplehouse﻿", "https://www.instagram.com/purplehouse/"),
        ("https://www.instagram.com/purplehouse/", "https://www.instagram.com/purplehouse/"),
        ("https://www.instagram.com/purplehouse", "https://www.instagram.com/purplehouse/"),
        ("https://instagram.com/purplehouse/", "https://www.instagram.com/purplehouse/"),
        ("http://www.instagram.com/purplehouse", "https://www.instagram.com/purplehouse/"),
        ("www.instagram.com/purplehouse", "https://www.instagram.com/purplehouse/"),
        ("instagram.com/purplehouse", "https://www.instagram.com/purplehouse/"),
        ("https://m.instagram.com/purplehouse/", "https://www.instagram.com/purplehouse/"),
        ("https://www.instagram.com/purplehouse/?igsh=abc123", "https://www.instagram.com/purplehouse/"),
        ("https://www.instagram.com/purplehouse?utm_source=x#y", "https://www.instagram.com/purplehouse/"),
        ("HTTPS://WWW.INSTAGRAM.COM/purplehouse/", "https://www.instagram.com/purplehouse/"),
        ("https://www.instagram.com/@purplehouse/", "https://www.instagram.com/purplehouse/"),
        ("a" * 30, "https://www.instagram.com/" + "a" * 30 + "/"),
        ("@" + "a" * 30, "https://www.instagram.com/" + "a" * 30 + "/"),
        ("1", "https://www.instagram.com/1/"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
    ids=[
        "handle com @",
        "handle sem @",
        "handle com ponto e sublinhado",
        "maiúsculas ficam como escritas",
        "sem os espaços das pontas",
        "sem os espaços Unicode das pontas",
        "URL completa",
        "URL sem barra no fim",
        "URL sem www",
        "URL em http",
        "URL sem esquema",
        "URL só com o domínio",
        "URL do telemóvel",
        "URL de partilha com query",
        "URL com query e fragmento",
        "URL em maiúsculas",
        "URL com @ no caminho",
        "handle com 30 caracteres",
        "handle com @ e 30 caracteres",
        "handle com um carácter",
        "vazio",
        "só espaços",
        "nulo",
    ],
)
def test_instagram_normaliza(valor, guardado):
    assert instagram(valor) == (guardado, None)


@pytest.mark.parametrize(
    "valor",
    [
        "@",
        "@@purplehouse",
        "purple house",
        "@purple house",
        "purple-house",
        "purple/house",
        "purplehouse/",
        "@purplehouse/",
        "@purple\nhouse",
        "açaí",
        "@purplehouse!",
        "a" * 31,
        "@" + "a" * 31,
        "https://www.instagram.com/",
        "https://www.instagram.com",
        "instagram.com",
        "www.instagram.com/",
        "https://www.instagram.com/p/ABC123/",
        "https://www.instagram.com/purplehouse/reels/",
        "https://www.instagram.com//purplehouse/",
        "https://www.facebook.com/purplehouse",
        "https://instagram.com.exemplo.pt/purplehouse",
        "https://www.instagram.com/purple house/",
        "https://www.instagram.com/" + "a" * 31 + "/",
        "purplehouse\x00",
        True,
        0,
        12.5,
        ["purplehouse"],
        {"handle": "purplehouse"},
    ],
    ids=[
        "só o @",
        "dois @",
        "handle com espaço",
        "handle com @ e espaço",
        "handle com hífen",
        "handle com barra",
        "handle com barra no fim",
        "handle com @ e barra no fim",
        "mudança de linha",
        "handle com acentos",
        "handle com ponto de exclamação",
        "handle com 31 caracteres",
        "handle com @ e 31 caracteres",
        "URL sem perfil",
        "URL sem perfil nem barra",
        "só o domínio",
        "só o domínio com www",
        "URL de uma publicação",
        "URL dos reels do perfil",
        "URL com duas barras",
        "URL de outro sítio",
        "URL de um domínio parecido",
        "URL com espaço no perfil",
        "URL com 31 caracteres no perfil",
        "carácter de controlo",
        "verdadeiro",
        "zero",
        "decimal",
        "lista",
        "objeto",
    ],
)
def test_instagram_recusa(valor):
    assert instagram(valor) == (None, INSTAGRAM)
