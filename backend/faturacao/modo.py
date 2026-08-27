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
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pos_auth import dispositivo_atual
from .vendus.emissao import VendusModoInvalido, _modo_configurado, _modo_valido

router = APIRouter()


CHAVE = "modo_emissao"


class ModoEntrada(BaseModel):
    """O modo PARA ONDE se quer ir — nunca «alternar».

    Um botão que alterna, tocado duas vezes por engano (um duplo toque num
    ecrã táctil, um pedido repetido pela rede), passa a real e volta a testes
    sem ninguém dar por isso — e as faturas que saíram pelo meio são reais
    para sempre. Dizer para onde torna a repetição inofensiva.
    """
    modo: str

    @field_validator("modo")
    @classmethod
    def _valida(cls, v):
        # A MESMA função que a emissão usa. Aceitar aqui um valor que ela
        # depois recusa era pôr o sistema no terceiro estado por uma escrita
        # do backoffice — exactamente o que este módulo existe para evitar.
        try:
            return _modo_valido(v)
        except VendusModoInvalido as e:
            raise ValueError(str(e))


async def modo_efectivo(db) -> Optional[str]:
    """`'tests'`, `'normal'`, ou `None` quando não se sabe. **A fonte única.**

    Por esta ordem:

    1. o que estiver GUARDADO (o botão do backoffice) — é para isso que ele
       existe, mandar sem `ssh`;
    2. senão, a variável de ambiente `VENDUS_MODE` — o que vale em qualquer
       instalação onde ninguém tocou no botão. Sem esta segunda origem, o dia
       do deploy mudava o comportamento de produção sem ninguém pedir;
    3. senão, `None`.

    `None` é o terceiro estado e é exactamente o conjunto de casos em que a
    emissão se RECUSA a emitir — não um subconjunto, não um parecido: quem
    decide se um valor serve é `_modo_valido`, a mesma dos dois lados. Um
    valor estragado GUARDADO cai aqui na mesma, e não «cai para a variável de
    ambiente»: uma escrita que não se percebe não pode ser silenciosamente
    substituída por outra coisa qualquer.
    """
    # A base de dados vem de QUEM CHAMA, e não de um `obter_db()` aqui
    # dentro: quem emite já tem a sua, e ir buscar uma segunda obrigava todo o
    # caminho de emissão a conhecer mais uma ligação — e todos os testes desse
    # caminho a remendar duas coisas em vez de uma.
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE}, {"_id": 0})
    if doc and doc.get("modo") is not None:
        try:
            return _modo_valido(doc.get("modo"))
        except VendusModoInvalido:
            return None
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
    return {"modo": await modo_efectivo(obter_db())}


@router.get("/modo-de-emissao")
async def modo_de_emissao_do_backoffice(utilizador: Dict = Depends(gestor_atual)) -> dict:
    return {"modo": await modo_efectivo(obter_db())}


@router.put("/modo-de-emissao")
async def mudar_modo_de_emissao(
    dados: ModoEntrada, utilizador: Dict = Depends(gestor_atual)
) -> dict:
    """Vira o interruptor, e deixa rasto de quem o virou.

    O rasto não é burocracia: a diferença entre «alguém pôs isto a real às
    14h» e «não se sabe» é a diferença entre perceber um dia estranho e não
    perceber. Guarda-se o e-mail de quem mudou e o instante, e a leitura
    devolve-os para o ecrã os poder mostrar.
    """
    agora = datetime.now(timezone.utc).isoformat()
    await obter_db()[COLECOES["definicoes"]].update_one(
        {"id": CHAVE},
        {"$set": {"id": CHAVE, "modo": dados.modo,
                  "mudado_em": agora,
                  "mudado_por": utilizador.get("email") or utilizador.get("name")}},
        upsert=True,
    )
    return {"modo": dados.modo, "mudado_em": agora}
