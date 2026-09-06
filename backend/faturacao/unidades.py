"""**As unidades em que se mede o que sai do armazém**, e a conversão entre elas.

Dois vocabulários que se têm de encontrar:

- quem escreve a ficha pensa em `g`, `kg`, `ml`, `L`, `un` — «30 g de granola»;
- o Estoque conta os artigos em `kg`, `L`, `un` e `caixa`.

E há uma coisa que torna isto perigoso e não meramente chato: **o movimento de
stock não leva unidade nenhuma**. O `POST /integ/movimento` manda um número
cru, interpretado do lado de lá na unidade do artigo. Mandar `30` para um
artigo contado em quilos tira 30 kg de granola por dose — mil vezes a mais,
sem um erro pelo caminho.

Por isso a conversão faz-se aqui, uma vez, e ninguém a repete: uma segunda
cópia deste mapa é uma divergência à espera de acontecer, e a que ficasse para
trás errava por um factor de mil.

**A `caixa` não tem conversão e não pode ter.** Uma caixa de quê, com quantos?
Só o Estoque sabe, e nem sempre. Um artigo contado em caixas recusa-se a ser
ligado a uma gramagem, na cara de quem configura — o silêncio ali era pior:
uma ficha preenchida que nunca descontasse nada.
"""

# unidade escrita na ficha -> (família, factor para a unidade de base)
_FAMILIAS = {
    "g": ("massa", 0.001), "kg": ("massa", 1.0),
    "ml": ("volume", 0.001), "L": ("volume", 1.0),
    "un": ("contagem", 1.0),
}

# A unidade em que cada família se soma e em que o Estoque conta.
UNIDADE_BASE = {"massa": "kg", "volume": "L", "contagem": "un"}

# O caminho inverso: a unidade do artigo do Estoque -> a família dele.
# A `caixa` está de fora de propósito (ver o cabeçalho).
FAMILIA_DO_ARTIGO = {"kg": "massa", "L": "volume", "un": "contagem"}

# As que o backoffice oferece para escrever numa ficha.
UNIDADES_DE_CONSUMO = frozenset(_FAMILIAS)

# As que um artigo do Estoque pode ter e a que uma ficha se pode ligar.
UNIDADES_DE_ARTIGO = frozenset(FAMILIA_DO_ARTIGO)


def familia(unidade):
    """A família de uma unidade escrita numa ficha, ou `None` se não a souber."""
    par = _FAMILIAS.get(unidade)
    return par[0] if par else None


def em_unidade_base(quantidade, unidade):
    """`quantidade` convertida para a unidade de base da família dela.

    Devolve `None` — e não zero — quando a unidade é desconhecida: zero é uma
    medição («não gasta nada») e a ausência de medição é outra coisa. Quem
    chama tem de as poder distinguir, senão uma unidade que ninguém sabe
    converter desaparecia da conta com ar de estar contada.
    """
    par = _FAMILIAS.get(unidade)
    if par is None:
        return None
    return float(quantidade) * par[1]
