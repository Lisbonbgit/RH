"""A forma única dos erros do CRM.

Um erro do CRM é uma `HTTPException` cujo `detail` é um objeto
`{"codigo", "mensagem", "campos"?, …extra}` (plano §4, dossiê §6). O FastAPI
devolve-o como `{"detail": {...}}`. O frontend (lib/crm/api.js, T1.10)
decide pelo `codigo` e mostra a `mensagem`, em pt-PT; `campos` leva o erro de
cada campo para aparecer junto dele. Os erros herdados da autenticação do
portal (`faturacao.auth`, HTTPBearer) continuam em texto e o frontend
normaliza os dois.

Porta de src/Http/ErroApi.php do CRM autónomo. As funções DEVOLVEM a exceção
(quem chama faz `raise erro(...)`), para se poder testar a forma sem rota.
"""
from fastapi import HTTPException

# Tabela "Códigos de erro do CRM" (plano §4 e dossiê §6): o código decide o
# estado HTTP. Um código novo acrescenta-se lá e aqui (o teste compara-a com a
# tabela), e só então se pode usar.
ESTADOS = {
    "json_invalido": 400,
    "sem_acesso_crm": 403,
    "sem_permissao": 403,
    "nao_encontrado": 404,
    "validacao": 422,
    "duplicado": 409,
    "conflito": 409,
    "regiao_repetida": 409,
    "regiao_com_lojas": 409,
    "loja_com_historico": 409,
    "ja_membro": 409,
    "admin_master": 409,
    "morada_indisponivel": 503,
    # F3 (plano F3 §4; T3.19): as recusas de escrever numa rota. O
    # `rota_em_curso` entra aqui e não na T3.20 (correção "T3.19 / T3.20").
    "ja_na_rota": 409,
    "rota_cheia": 409,
    "rota_fechada": 409,
    "rota_em_curso": 409,
}

MENSAGEM_VALIDACAO = "Verifique os campos assinalados."
MENSAGEM_JSON_INVALIDO = "O pedido não é JSON válido."


def erro(estado: int, codigo: str, mensagem: str, **extra) -> HTTPException:
    """O erro `codigo` com o estado HTTP `estado` e a `mensagem` para a pessoa.

    `extra` acrescenta chaves ao objeto (ex.: `lojas=[…]` no duplicado). Um
    código fora da tabela, ou um estado que não é o do código, é um erro de
    programação (ValueError) e não chega ao cliente: o contrato com o
    frontend não muda por engano.
    """
    if codigo not in ESTADOS:
        raise ValueError(f"Código de erro do CRM desconhecido: {codigo!r}")
    if ESTADOS[codigo] != estado:
        raise ValueError(f"O código {codigo!r} tem o estado {ESTADOS[codigo]}, não {estado}")
    return HTTPException(status_code=estado, detail={"codigo": codigo, "mensagem": mensagem, **extra})


def validacao(campos: dict) -> HTTPException:
    """422 com a mensagem geral e o erro de cada campo, pela ordem recebida
    (a ordem dos campos do formulário). Guarda uma cópia de `campos`."""
    return erro(422, "validacao", MENSAGEM_VALIDACAO, campos=dict(campos))


def nao_encontrado(mensagem: str) -> HTTPException:
    """404 com a mensagem da entidade ("Loja não encontrada.", "Região não
    encontrada.", "Membro não encontrado.")."""
    return erro(404, "nao_encontrado", mensagem)
