"""«Isto está em teste ou está a sério?» — a pergunta, respondida pelo servidor.

O dono perguntou-a e ninguém soube responder sem ir ao servidor ler uma
variável de ambiente. Este módulo existe para o ecrã a poder fazer, e por isso
tem uma regra acima de todas: **nunca adivinhar**. Os dois enganos que ele
previne são simétricos e são os dois caros —

- em `tests` sem aviso, a operadora julga que está a vender a sério; o cliente
  leva um talão que não vale nada, **nada chega à Autoridade Tributária**, e a
  loja pensa que facturou o dia;
- em `normal` com o aviso ligado, ela julga que está a treinar e emite Faturas
  Simplificadas REAIS em nome da Fordaimon Foods.

Daí os TRÊS estados: `tests`, `normal`, e **não se sabe**. O terceiro não é um
detalhe — é o que decide se isto funciona. Uma rota que, sem conseguir apurar o
modo, respondesse `tests` (ou `normal`) escolhia um dos enganos por omissão, e
em silêncio.

**A verdade vem de onde a emissão a vai buscar**, e de mais lado nenhum:
`vendus/emissao.py::_modo_configurado`, que já se recusa a emitir quando
`VENDUS_MODE` não é explicitamente 'tests' ou 'normal' (ver a docstring de
`VendusModoInvalido`). Não há aqui um segundo `os.environ.get("VENDUS_MODE")` —
uma segunda leitura era uma segunda oportunidade para os dois lados
divergirem, e o sítio onde essa divergência dói é o ecrã a dizer uma coisa
enquanto a fatura faz outra.

**Duas rotas, dois âmbitos, e nunca uma só.** Isto diz a quem pergunta se a
empresa está a emitir a sério — não fica aberto. E as duas famílias de
autenticação deste módulo não se misturam (ver `test_protecao_rotas.py`):

- `/pos/modo-de-emissao` depende do **dispositivo**, deliberadamente NÃO do
  operador. A faixa tem de continuar de pé durante a troca de operador, e nesse
  instante o ecrã não tem token de operador nenhum;
- `/modo-de-emissao` depende do **gestor**, para o backoffice.
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends

from .auth import gestor_atual
from .pos_auth import dispositivo_atual
from .vendus.emissao import VendusModoInvalido, _modo_configurado

router = APIRouter()


def modo_de_emissao() -> Optional[str]:
    """`'tests'`, `'normal'`, ou `None` quando não se sabe.

    `None` é o terceiro estado e é exactamente o conjunto de casos em que a
    emissão se RECUSA a emitir — não um subconjunto, não um parecido: é a
    mesma função a decidir. Ausente, vazia, com maiúsculas, com um espaço ao
    fim, ou com um valor inventado, tudo cai aqui.
    """
    try:
        return _modo_configurado()
    except VendusModoInvalido:
        return None


# 200 com `modo: null`, e não um erro, quando não se sabe: do lado do ecrã um
# 500 seria indistinguível de o servidor estar em baixo, e as duas coisas têm
# de acabar no MESMO terceiro estado. Mais vale dizê-lo com todas as letras do
# que deixar o ecrã a deduzi-lo de um erro.
#
# A resposta é só o modo. Isto responde-se a um PC de balcão emparelhado, e não
# pode arrastar consigo o nome da conta Vendus, a caixa API nem o NIF.


@router.get("/pos/modo-de-emissao")
async def modo_de_emissao_do_pos(dispositivo: Dict = Depends(dispositivo_atual)) -> dict:
    return {"modo": modo_de_emissao()}


@router.get("/modo-de-emissao")
async def modo_de_emissao_do_backoffice(utilizador: Dict = Depends(gestor_atual)) -> dict:
    return {"modo": modo_de_emissao()}
