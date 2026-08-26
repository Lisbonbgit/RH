"""**O email do relatório diário** — só HTML, sem Mongo e sem envio.

Um email não é uma página. O Gmail apaga `<svg>` e `<style>`; o Outlook
desenha com o motor do Word (sem flexbox, sem grid); nenhum dos dois percebe
CSS variables. Por isso aqui não há nada disso: tabelas aninhadas, estilos em
linha, e as alturas das colunas do gráfico calculadas em PIXÉIS deste lado —
uma altura em percentagem não é fiável em cliente de email nenhum, e a coluna
aparece com zero de altura.

Recebe o dicionário de `relatorio_diario.montar_relatorio` e devolve uma
string. Não faz contas com dinheiro: os números chegam feitos. Se um valor
está errado, o erro está lá e não aqui — e é lá que tem teste.

**As cores são as do sistema**, convertidas dos tokens de `index.css` para
hexadecimais fixos (um email não tem variáveis). Estão todas aqui em cima
para se mudarem num sítio só.
"""
from html import escape
from typing import Dict, List, Optional

# --- A paleta, tirada de frontend/src/index.css ------------------------------
FUNDO = "#F7FAFD"          # --background
CARTAO = "#FFFFFF"         # --card
TEXTO = "#0E1B2A"          # --foreground
TEXTO_FRACO = "#65778B"    # --muted-foreground
PRIMARIA = "#1468F0"       # --primary
PRIMARIA_FRACA = "#E9F4FB"  # --accent
LINHA = "#DFE7F1"          # --border
BOM = "#1DA58A"            # --success
MAU = "#E74040"            # --destructive
AVISO = "#B45309"          # âmbar, o mesmo tom dos avisos do backoffice
AVISO_FUNDO = "#FEF7EC"

# Pilha de tipos de sistema: nenhuma fonte carregada de fora (o Outlook não a
# vai buscar, e um email que espera por um tipo desenha-se duas vezes).
FONTE = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
         "'Helvetica Neue',Arial,sans-serif")

LARGURA = 600
ALTURA_GRAFICO = 96
MESES = ("jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez")


def _euros(valor) -> str:
    """`1 234,56 €` — o formato português, escrito à mão.

    Sem `Intl` nem `locale`: o `locale` do processo é global e mudá-lo num
    servidor que faz mais coisas é uma armadilha para outra pessoa. São seis
    linhas e não dependem de que locales estão instalados no contentor.
    """
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    inteiro, _, decimal = ("%.2f" % abs(numero)).partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    # Espaço fino insecável entre os milhares: é o que a norma portuguesa usa
    # e o que não deixa "1 234" partir-se em duas linhas no telemóvel.
    return "%s%s&nbsp;€" % ("-" if numero < 0 else "", "&#8239;".join(grupos) + "," + decimal)


def _percentagem(valor) -> str:
    """`19,45%` — com vírgula, como tudo o resto neste email. `"%.2f"`
    dá ponto, e um relatório português com um ponto decimal lê-se como um
    descuido de quem o escreveu."""
    return ("%.2f" % abs(float(valor or 0))).replace(".", ",") + "%"


# Texto que vem da base de dados (nomes de lojas, de produtos, de tipos de
# pagamento) é DADO e nunca marcação. `quote=False` porque isto entra em
# nós de texto e não em atributos: escapar o apóstrofo de "L'açaí" não
# acrescenta segurança nenhuma e enche o email de `&#x27;`. Dentro de um
# atributo usa-se o `escape` normal, com as aspas escapadas.
def _texto(valor) -> str:
    return escape(str(valor if valor is not None else ""), quote=False)


def _dia_curto(data: Optional[str]) -> str:
    """`2026-08-26` -> `26 ago`."""
    texto = str(data or "")
    if len(texto) < 10:
        return texto
    try:
        return "%d %s" % (int(texto[8:10]), MESES[int(texto[5:7]) - 1])
    except (ValueError, IndexError):
        return texto


def _dia_por_extenso(data: Optional[str]) -> str:
    """`2026-08-26` -> `26 de agosto de 2026`."""
    texto = str(data or "")
    if len(texto) < 10:
        return texto
    completos = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
    try:
        return "%d de %s de %s" % (int(texto[8:10]), completos[int(texto[5:7]) - 1], texto[:4])
    except (ValueError, IndexError):
        return texto


def _altura_da_coluna(valor, maximo, altura_max: int) -> int:
    """A altura de uma coluna, em pixéis.

    **Um dia a zero continua a ver-se.** Com altura 0 a coluna desaparece e o
    leitor conta treze colunas onde devia contar catorze — e um dia sem vendas
    é exactamente o que ele precisa de notar. Fica com 2 px: um risco, não uma
    barra.

    Um máximo a zero (uma loja nova, um dia de encerramento geral) não pode
    dividir por zero e derrubar o email da noite inteira.
    """
    try:
        v = float(valor or 0)
        m = float(maximo or 0)
    except (TypeError, ValueError):
        return 2
    if m <= 0 or v <= 0:
        return 2
    return max(2, int(round((v / m) * altura_max)))


def _pilula(texto: str, cor: str, fundo: str) -> str:
    return (
        '<span style="display:inline-block;padding:3px 9px;border-radius:999px;'
        'background:%s;color:%s;font-size:12px;font-weight:700;'
        'line-height:1.2;white-space:nowrap;">%s</span>' % (fundo, cor, texto))


def _barra_de_proporcao(parte: float, total: float, cor: str = PRIMARIA) -> str:
    """A fatia que uma linha ocupa do total, como uma barra fina.

    Duas células de tabela e não um `<div>` com largura em percentagem dentro
    de outro: o Outlook ignora larguras percentuais em `div`, mas respeita-as
    numa `<td>`. É a diferença entre a barra aparecer e não aparecer.
    """
    try:
        pct = max(0, min(100, int(round((float(parte) / float(total)) * 100)))) if total else 0
    except (TypeError, ValueError, ZeroDivisionError):
        pct = 0
    resto = 100 - pct
    celulas = ''
    if pct:
        celulas += ('<td width="%d%%" style="background:%s;height:4px;'
                    'font-size:0;line-height:0;border-radius:2px;">&nbsp;</td>' % (pct, cor))
    if resto:
        celulas += ('<td width="%d%%" style="background:%s;height:4px;'
                    'font-size:0;line-height:0;">&nbsp;</td>' % (resto, LINHA))
    return ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0" style="border-collapse:collapse;table-layout:fixed;">'
            '<tr>%s</tr></table>' % celulas)


def _cartao(conteudo: str, margem_topo: int = 16) -> str:
    return (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:separate;margin-top:%dpx;">'
        '<tr><td style="background:%s;border:1px solid %s;border-radius:14px;padding:20px;">'
        '%s</td></tr></table>' % (margem_topo, CARTAO, LINHA, conteudo))


def _titulo_de_seccao(texto: str) -> str:
    return (
        '<p style="margin:0 0 14px;font-size:11px;font-weight:700;color:%s;'
        'letter-spacing:1.2px;text-transform:uppercase;">%s</p>'
        % (TEXTO_FRACO, _texto(texto)))


def _grafico(serie: List[Dict]) -> str:
    """As colunas dos últimos dias.

    Alturas em pixéis (ver `_altura_da_coluna`) e uma coluna por `<td>`, com o
    conteúdo alinhado ao fundo — é o único arranjo que se comporta igual no
    Gmail, no Outlook e no Mail do iPhone.

    **Só três etiquetas**: a primeira, a última e a de hoje. Catorze datas por
    baixo de catorze colunas de 24 px sobrepõem-se e não se lêem nenhumas.
    """
    if not serie:
        return ""
    maximo = max((s.get("valor") or 0) for s in serie)
    ultimos = len(serie) - 1
    colunas = []
    etiquetas = []
    for i, ponto in enumerate(serie):
        hoje = bool(ponto.get("hoje"))
        altura = _altura_da_coluna(ponto.get("valor"), maximo, ALTURA_GRAFICO)
        cor = PRIMARIA if hoje else PRIMARIA_FRACA
        colunas.append(
            '<td valign="bottom" style="padding:0 2px;">'
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0"><tr><td data-coluna="%s" style="height:%dpx;background:%s;'
            'border-radius:4px 4px 0 0;font-size:0;line-height:0;">&nbsp;</td></tr></table>'
            '</td>' % (escape(str(ponto.get("data") or "")), altura, cor))
        mostrar = hoje or i == 0 or i == ultimos
        etiquetas.append(
            '<td align="center" style="padding:6px 0 0;font-size:10px;'
            'color:%s;font-weight:%s;white-space:nowrap;">%s</td>'
            % (PRIMARIA if hoje else TEXTO_FRACO,
               "700" if hoje else "400",
               _dia_curto(ponto.get("data")) if mostrar else "&nbsp;"))
    return (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;table-layout:fixed;">'
        '<tr>%s</tr><tr>%s</tr></table>' % ("".join(colunas), "".join(etiquetas)))


def _numero_grande(valor, etiqueta: str, cor: str = TEXTO) -> str:
    return (
        '<p style="margin:0;font-size:11px;color:%s;letter-spacing:.6px;'
        'text-transform:uppercase;font-weight:600;">%s</p>'
        '<p style="margin:4px 0 0;font-size:20px;font-weight:700;color:%s;">%s</p>'
        % (TEXTO_FRACO, _texto(etiqueta), cor,
           _euros(valor) if valor is not None else "&mdash;"))


def _bloco_caixa(caixa: Dict, compacto: bool = False) -> str:
    """Esperado, contado e a diferença — os três lado a lado.

    **A diferença nunca é só cor.** Leva o sinal e a palavra ("falta" /
    "sobra"), porque quem não distingue verde de vermelho tem de ler a mesma
    coisa — e porque metade dos clientes de email inverte as cores no modo
    escuro.
    """
    estado = caixa.get("estado")
    if estado == "sem_turno":
        return ('<p style="margin:0;font-size:13px;color:%s;">'
                'Sem turno de caixa aberto neste dia.</p>' % TEXTO_FRACO)

    diferenca = caixa.get("diferenca")
    if diferenca is None:
        pilula = _pilula("Turno ainda aberto", AVISO, AVISO_FUNDO)
    elif abs(diferenca) < 0.005:
        pilula = _pilula("Gaveta certa", BOM, "#E6F6F2")
    elif diferenca < 0:
        pilula = _pilula("Falta %s" % _euros(abs(diferenca)), MAU, "#FDECEC")
    else:
        pilula = _pilula("Sobra %s" % _euros(diferenca), BOM, "#E6F6F2")

    tamanho = "13px" if compacto else "20px"
    # **Ao lado do contado vai o esperado COMPARÁVEL com ele** — o dos turnos
    # que alguém contou, e não o das lojas todas. Ver `_caixa_das_sessoes`: o
    # par errado convidava a uma subtracção que dava outro número, e o leitor
    # concluía que o relatório se enganou.
    esperado = caixa.get("esperado_contado")
    if esperado is None:
        esperado = caixa.get("esperado")
    rotulo_esperado = "Esperado (contados)" if caixa.get("turnos_abertos") else "Esperado"

    celula = (
        '<td width="50%%" valign="top" style="padding:0 8px 0 0;">'
        '<p style="margin:0;font-size:11px;color:%s;text-transform:uppercase;'
        'letter-spacing:.6px;font-weight:600;">%s</p>'
        '<p style="margin:3px 0 0;font-size:%s;font-weight:700;color:%s;">%s</p></td>')
    por_contar = ""
    if caixa.get("turnos_abertos") and caixa.get("esperado_aberto"):
        por_contar = (
            '<p style="margin:8px 0 0;font-size:12px;color:%s;">'
            'Por contar: <strong>%s</strong> em %d turno%s ainda aberto%s.</p>'
            % (AVISO, _euros(caixa.get("esperado_aberto")), caixa["turnos_abertos"],
               "" if caixa["turnos_abertos"] == 1 else "s",
               "" if caixa["turnos_abertos"] == 1 else "s"))
    return (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0">'
        '<tr>%s%s</tr></table>%s'
        '<div style="margin-top:10px;">%s</div>'
        % (celula % (TEXTO_FRACO, rotulo_esperado, tamanho, TEXTO,
                     _euros(esperado) if esperado is not None else "&mdash;"),
           celula % (TEXTO_FRACO, "Contado", tamanho, TEXTO,
                     _euros(caixa.get("contado")) if caixa.get("contado") is not None else "&mdash;"),
           por_contar, pilula))


def _linhas_de_pagamento(pagamentos: List[Dict], total: float) -> str:
    if not pagamentos:
        return ('<p style="margin:0;font-size:13px;color:%s;">'
                'Sem pagamentos registados.</p>' % TEXTO_FRACO)
    linhas = []
    for p in pagamentos:
        linhas.append(
            '<tr><td style="padding:7px 0 3px;font-size:14px;color:%s;">%s</td>'
            '<td align="right" style="padding:7px 0 3px;font-size:14px;'
            'font-weight:700;color:%s;white-space:nowrap;">%s</td></tr>'
            '<tr><td colspan="2" style="padding:0 0 4px;">%s</td></tr>'
            % (TEXTO, _texto(p.get("nome") or "—"), TEXTO,
               _euros(p.get("total")),
               _barra_de_proporcao(p.get("total") or 0, total)))
    return ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0">%s</table>' % "".join(linhas))


def _cartao_de_loja(loja: Dict, maior: float) -> str:
    faturacao = loja.get("faturacao") or 0
    cabecalho = (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td style="font-size:16px;font-weight:700;color:%s;">%s</td>'
        '<td align="right" style="font-size:18px;font-weight:700;color:%s;'
        'white-space:nowrap;">%s</td></tr>'
        '<tr><td colspan="2" style="padding:8px 0 2px;">%s</td></tr>'
        '<tr><td colspan="2" style="padding:2px 0 0;font-size:12px;color:%s;">%s</td></tr>'
        '</table>'
        % (TEXTO, _texto(loja.get("nome")), PRIMARIA, _euros(faturacao),
           _barra_de_proporcao(faturacao, maior),
           TEXTO_FRACO,
           "sem vendas neste dia" if loja.get("sem_vendas")
           else "%d documento%s" % (loja.get("documentos") or 0,
                                    "" if loja.get("documentos") == 1 else "s")))
    corpo = (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin-top:14px;border-top:1px solid %s;">'
        '<tr><td width="50%%" valign="top" style="padding:14px 10px 0 0;">%s</td>'
        '<td width="50%%" valign="top" style="padding:14px 0 0 10px;">'
        '<p style="margin:0 0 2px;font-size:11px;color:%s;text-transform:uppercase;'
        'letter-spacing:.6px;font-weight:600;">Pagamentos</p>%s</td></tr></table>'
        % (LINHA, _bloco_caixa(loja.get("caixa") or {}, compacto=True), TEXTO_FRACO,
           _linhas_de_pagamento(loja.get("pagamentos") or [], faturacao or 1)))
    return _cartao(cabecalho + corpo)


def _bloco_artigos(artigos: List[Dict]) -> str:
    if not artigos:
        return ('<p style="margin:0;font-size:13px;color:%s;">'
                'Sem artigos vendidos neste dia.</p>' % TEXTO_FRACO)
    maior = max((a.get("quantidade") or 0) for a in artigos) or 1
    blocos = []
    for artigo in artigos[:6]:
        quantidade = artigo.get("quantidade") or 0
        variantes = ""
        if artigo.get("variantes"):
            pedacos = [
                '<span style="display:inline-block;margin:4px 6px 0 0;padding:3px 9px;'
                'border-radius:999px;background:%s;color:%s;font-size:12px;">'
                '%s <strong style="color:%s;">%d</strong></span>'
                % (PRIMARIA_FRACA, TEXTO_FRACO, _texto(v.get("nome")),
                   TEXTO, v.get("quantidade") or 0)
                for v in artigo["variantes"][:5]]
            variantes = '<div style="margin-top:2px;">%s</div>' % "".join(pedacos)
        blocos.append(
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0" style="margin-bottom:14px;">'
            '<tr><td style="font-size:15px;font-weight:600;color:%s;">%s</td>'
            '<td align="right" style="font-size:15px;font-weight:700;color:%s;'
            'white-space:nowrap;">%d un.</td></tr>'
            '<tr><td colspan="2" style="padding:7px 0 0;">%s</td></tr>'
            '<tr><td colspan="2">%s</td></tr></table>'
            % (TEXTO, _texto(artigo.get("nome")), TEXTO, quantidade,
               _barra_de_proporcao(quantidade, maior), variantes))
    return "".join(blocos)


def html_do_relatorio(dados: Dict, url_do_painel: Optional[str] = None) -> str:
    """O email inteiro, pronto a enviar."""
    geral = dados.get("geral") or {}
    lojas = dados.get("lojas") or []
    faturacao = geral.get("faturacao") or 0
    variacao = geral.get("variacao")

    if variacao is None:
        marca = _pilula("Sem dia anterior para comparar", TEXTO_FRACO, "#EDF1F6")
    elif variacao >= 0:
        marca = _pilula("&#9650; %s vs. ontem" % _percentagem(variacao), BOM, "#E6F6F2")
    else:
        marca = _pilula("&#9660; %s vs. ontem" % _percentagem(variacao), MAU, "#FDECEC")

    ontem = ('<p style="margin:10px 0 0;font-size:13px;color:%s;">Ontem (%s): '
             '<strong style="color:%s;">%s</strong></p>'
             % (TEXTO_FRACO, _dia_curto(geral.get("dia_de_ontem")), TEXTO,
                _euros(geral.get("faturacao_ontem")))
             ) if geral.get("dia_de_ontem") else ""

    aviso_sem_vendas = "" if dados.get("ha_vendas") else (
        '<p style="margin:12px 0 0;padding:10px 12px;background:%s;color:%s;'
        'border-radius:10px;font-size:13px;">Não houve vendas registadas neste dia.</p>'
        % (AVISO_FUNDO, AVISO))

    heroi = _cartao(
        '<p style="margin:0;font-size:11px;color:%s;letter-spacing:.6px;'
        'text-transform:uppercase;font-weight:600;">Faturação do dia%s</p>'
        '<p style="margin:6px 0 0;font-size:38px;line-height:1.1;font-weight:700;'
        'color:%s;">%s</p>'
        '<div style="margin-top:12px;">%s</div>%s%s'
        '<div style="margin-top:18px;">%s</div>'
        % (TEXTO_FRACO, "" if dados.get("com_iva") else " (sem IVA)", TEXTO,
           _euros(faturacao), marca, ontem, aviso_sem_vendas,
           _grafico(dados.get("serie") or [])),
        margem_topo=0)

    caixa_geral = geral.get("caixa") or {}
    abertos = caixa_geral.get("turnos_abertos") or 0
    # A nota de quantos turnos ficaram abertos vive no `_bloco_caixa`, junto
    # dos números a que diz respeito — repeti-la aqui era dizer duas vezes a
    # mesma coisa em dois sítios que podiam divergir.
    nota_abertos = ""
    bloco_caixa_geral = _cartao(
        _titulo_de_seccao("Caixa · todas as lojas")
        + _bloco_caixa(caixa_geral) + nota_abertos)

    maior_loja = max([l.get("faturacao") or 0 for l in lojas] or [1]) or 1
    cartoes_de_loja = "".join(_cartao_de_loja(l, maior_loja) for l in lojas)
    titulo_lojas = (
        '<p style="margin:26px 0 0;font-size:11px;font-weight:700;color:%s;'
        'letter-spacing:1.2px;text-transform:uppercase;">Por loja</p>' % TEXTO_FRACO
    ) if lojas else ""

    bloco_pagamentos = _cartao(
        _titulo_de_seccao("Pagamentos · total")
        + _linhas_de_pagamento(geral.get("pagamentos") or [], faturacao or 1))

    bloco_artigos = _cartao(
        _titulo_de_seccao("Mais vendidos")
        + _bloco_artigos(dados.get("artigos") or []))

    botao = ""
    if url_do_painel:
        botao = (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:22px auto 0;"><tr>'
            '<td style="background:%s;border-radius:10px;">'
            '<a href="%s" style="display:inline-block;padding:12px 24px;color:#FFFFFF;'
            'font-size:14px;font-weight:600;text-decoration:none;">Ver no painel</a>'
            '</td></tr></table>' % (PRIMARIA, escape(url_do_painel, quote=True)))

    return (
        '<!doctype html><html lang="pt"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<title>Relatório diário</title></head>'
        '<body style="margin:0;padding:0;background:%(fundo)s;">'
        # O pré-cabeçalho: a linha que o Gmail mostra ao lado do assunto na
        # caixa de entrada. Sem ela, mostra o primeiro texto que encontrar —
        # que aqui seria "FATURAÇÃO DO DIA".
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        '%(preheader)s</div>'
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
        'border="0" style="background:%(fundo)s;"><tr><td align="center" '
        'style="padding:28px 12px 36px;">'
        '<table role="presentation" width="%(largura)d" cellpadding="0" cellspacing="0" '
        'border="0" style="width:100%%;max-width:%(largura)dpx;font-family:%(fonte)s;'
        'color:%(texto)s;">'
        '<tr><td style="padding:0 0 18px;">'
        '<p style="margin:0;font-size:19px;font-weight:700;color:%(texto)s;">'
        'Relatório diário</p>'
        '<p style="margin:4px 0 0;font-size:13px;color:%(fraco)s;">%(dia)s '
        '&middot; até às %(ate)s</p>'
        '</td></tr>'
        '<tr><td>%(heroi)s</td></tr>'
        '<tr><td>%(caixa)s</td></tr>'
        '<tr><td>%(titulo_lojas)s%(lojas)s</td></tr>'
        '<tr><td>%(pagamentos)s</td></tr>'
        '<tr><td>%(artigos)s</td></tr>'
        '<tr><td>%(botao)s</td></tr>'
        '<tr><td style="padding:26px 4px 0;">'
        '<p style="margin:0;font-size:11px;color:%(fraco)s;line-height:1.6;">'
        'Gestão Lisbonb &middot; enviado automaticamente às %(ate)s. '
        'Uma venda feita depois dessa hora entra no dia seguinte.</p>'
        '</td></tr></table></td></tr></table></body></html>'
        % {
            "fundo": FUNDO, "largura": LARGURA, "fonte": FONTE,
            "texto": TEXTO, "fraco": TEXTO_FRACO,
            "dia": _texto(_dia_por_extenso(dados.get("dia"))),
            "ate": _texto(dados.get("ate")),
            "preheader": "%s de faturação%s" % (
                _euros(faturacao).replace("&nbsp;", " ").replace("&#8239;", " "),
                "" if dados.get("ha_vendas") else " — sem vendas"),
            "heroi": heroi, "caixa": bloco_caixa_geral,
            "titulo_lojas": titulo_lojas, "lojas": cartoes_de_loja,
            "pagamentos": bloco_pagamentos, "artigos": bloco_artigos,
            "botao": botao,
        })
