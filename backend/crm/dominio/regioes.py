"""Regras das regiões: o nome, a ordem e a chave dos nomes repetidos.

Porta de src/Dominio/Regioes/RegrasRegioes.php do CRM autónomo (dossiê §5.8):
`erro_nome` e `erro_ordem`. A validação do corpo, que lá estava no
`RegioesControlador::validar`, fica aqui em `criacao` (POST) e `alteracao`
(PATCH), como no validador da loja: a rota (T2.9) só lê, grava e responde.

Um nome repetido (sem distinguir maiúsculas nem acentos) recusava-o a chave
única da tabela, com a collation utf8mb4_unicode_ci do MariaDB. Aqui é o índice
único em `nome_chave` (plano §1 "Regiões"), gravado com a região: a chave é a
`texto.chave_comparacao`, a mesma que ordena os nomes, para o índice e a ordem
no ecrã nunca discordarem.
"""
from .numeros import e_inteiro_json
from .texto import aparar, chave_comparacao

# O tamanho da coluna nome do autónomo.
NOME_MAXIMO = 100

# Os limites da coluna ordem (um INT do MariaDB): fora deles, o sql_mode
# estrito recusava o valor. Ficam iguais, para o ecrã e a API não mudarem.
ORDEM_MINIMA = -2147483648
ORDEM_MAXIMA = 2147483647

# Uma região nova sem ordem fica com 0 (o padrão da coluna).
ORDEM_POR_OMISSAO = 0

MENSAGEM_NOME = "Indique o nome."
MENSAGEM_ORDEM = "A ordem tem de ser um número inteiro."


def erro_nome(nome: str) -> "str | None":
    """None se o nome tiver 1 a 100 caracteres; senão a mensagem.

    O nome chega já aparado (quem apara é a `criacao`/`alteracao`): aqui
    "   " não é vazio. Conta caracteres, não bytes (o `mb_strlen` do PHP). Um
    nome que não seja texto é um erro de programação (`TypeError`), como o
    `string $nome` do PHP em modo estrito.
    """
    if not isinstance(nome, str):
        raise TypeError(f"o nome da região tem de chegar em texto, não {type(nome).__name__}")
    if nome == "":
        return MENSAGEM_NOME
    if len(nome) > NOME_MAXIMO:
        return f"O nome tem no máximo {NOME_MAXIMO} caracteres."
    return None


def erro_ordem(ordem) -> "str | None":
    """None se a ordem for um inteiro do JSON que caiba num INT; senão a mensagem.

    Nunca "2", 2.0, `True` nem `False` (em Python um bool é um int: daí o
    `e_inteiro_json`, o `is_int` do PHP).
    """
    valida = e_inteiro_json(ordem) and ORDEM_MINIMA <= ordem <= ORDEM_MAXIMA
    return None if valida else MENSAGEM_ORDEM


def nome_chave(nome: str) -> str:
    """A chave que torna o nome único: sem maiúsculas, acentos nem espaços nas
    pontas ("Setúbal" e " SETUBAL" dão "setubal"). Os espaços do meio contam."""
    return chave_comparacao(nome)


def criacao(corpo: dict):
    """O corpo do `POST /regioes` (`{nome, ordem?}`) → `(campos, erros)`.

    Sem ordem fica `ORDEM_POR_OMISSAO`; sem nome dá "Indique o nome." (o
    `$pedido->json() + ['nome' => null, 'ordem' => 0]` do PHP: o que vem no
    corpo ganha, mesmo um null). Ver `alteracao` para o resto.
    """
    return _validar({"nome": None, "ordem": ORDEM_POR_OMISSAO, **corpo})


def alteracao(corpo: dict):
    """O corpo do `PATCH /regioes/{id}` (`{nome?, ordem?}`) → `(campos, erros)`.

    Só as chaves enviadas (conta a chave, mesmo com null). O nome perde os
    espaços das pontas (também os Unicode); o que não for texto fica "" e dá
    "Indique o nome.". As outras chaves ignoram-se. Os campos e os erros vêm
    pela ordem nome, ordem; os campos só se usam quando não há erros.
    """
    return _validar(corpo)


def _validar(corpo: dict):
    """O `RegioesControlador::validar` do autónomo, sem a exceção: devolve os erros."""
    campos = {}
    erros = {}

    if "nome" in corpo:
        nome = corpo["nome"]
        campos["nome"] = aparar(nome) if isinstance(nome, str) else ""
        erros["nome"] = erro_nome(campos["nome"])

    if "ordem" in corpo:
        campos["ordem"] = corpo["ordem"]
        erros["ordem"] = erro_ordem(corpo["ordem"])

    return campos, {campo: erro for campo, erro in erros.items() if erro is not None}
