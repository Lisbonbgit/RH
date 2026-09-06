"""**O email de segunda-feira** — só HTML, sem Mongo e sem envio.

Vale aqui tudo o que já vale no email do relatório diário: tabelas aninhadas,
estilos em linha, sem `<style>`, sem flexbox, sem grid e sem variáveis de CSS,
porque o Outlook desenha com o motor do Word e o Gmail apaga metade disso.

**As peças e as cores são emprestadas do `faturacao.relatorio_email`.** Não é
acoplamento por descuido: é o email da mesma casa, com as mesmas cores tiradas
do `index.css`, e uma segunda paleta copiada para aqui divergia da primeira no
dia em que alguém mudasse a marca. O que se importa é pequeno e é puro (não lê
base de dados nem envia nada), e há um teste neste módulo que rebenta se algum
desses nomes desaparecer — para o desfecho ser um teste vermelho e não o email
de segunda-feira a não sair.

**A regra que este ficheiro não pode quebrar: o que não se sabe escreve-se por
extenso.** Não há um "0,00 €" para dizer "não chegou". Um valor ausente é um
travessão e uma frase que explica porquê.
"""
from datetime import date
from typing import Dict, List, Optional

from faturacao.relatorio_email import (
    AVISO,
    AVISO_FUNDO,
    BOM,
    CARTAO,
    FONTE,
    FUNDO,
    LARGURA,
    LINHA,
    MAU,
    PRIMARIA,
    PRIMARIA_FRACA,
    TEXTO,
    TEXTO_FRACO,
    _barra_de_proporcao,
    _cartao,
    _dia_curto,
    _euros,
    _percentagem,
    _pilula,
    _texto,
    _titulo_de_seccao,
)

# Um travessão, e não "0,00 €". Ver a docstring do módulo.
NADA = "&mdash;"


def _valor(numero) -> str:
    return _euros(numero) if numero is not None else NADA


def _sem_entidades(texto: str) -> str:
    """O mesmo texto sem as entidades HTML — para o assunto e o pré-cabeçalho,
    que são texto simples e mostrariam `&nbsp;` tal e qual."""
    return (texto.replace("&nbsp;", " ").replace("&#8239;", " ")
            .replace("&mdash;", "—").replace("&middot;", "·"))


def _intervalo(inicio: str, fim: str) -> str:
    """`24 a 30 ago`, e `31 ago a 6 set` quando o período atravessa dois meses.

    O mês do início só se escreve quando é diferente do fim: "31 a 6 set" é a
    mesma semana e lê-se como se fosse toda em Setembro — e é precisamente a
    semana em que alguém iria conferir as datas.
    """
    if str(inicio)[:7] == str(fim)[:7]:
        return "%s a %s" % (_dia_curto(inicio).split(" ")[0], _dia_curto(fim))
    return "%s a %s" % (_dia_curto(inicio), _dia_curto(fim))


def _pilula_de_pagamento(periodo: Dict, sabido: bool = True) -> str:
    """Quando entra o dinheiro — e é isto que o dono abre o email para saber.

    `sabido=False` quando o relatório não chegou: aí a data é a do calendário,
    mas o valor é desconhecido, e dizer "pago hoje" ao lado de "relatório não
    recebido" lê-se como se alguma coisa tivesse entrado.
    """
    dias = periodo.get("dias_para_pagamento")
    quando = _dia_curto(periodo.get("pagamento"))
    if not sabido:
        return _pilula("Pagamento previsto para %s"
                       % ("hoje (%s)" % quando if dias == 0 else quando),
                       TEXTO_FRACO, "#EDF1F6")
    if dias is None:
        return _pilula("Pagamento %s" % quando, TEXTO_FRACO, "#EDF1F6")
    if dias == 0:
        return _pilula("Pago hoje (%s)" % quando, BOM, "#E6F6F2")
    if dias < 0:
        return _pilula("Devia ter entrado a %s" % quando, AVISO, AVISO_FUNDO)
    return _pilula("Entra a %s &middot; faltam %d dia%s"
                   % (quando, dias, "" if dias == 1 else "s"), PRIMARIA, PRIMARIA_FRACA)


def _pilula_de_variacao(variacao: Optional[float], termo: str,
                        houve_anterior: bool = False) -> str:
    """**«Sem período anterior para comparar» só se escreve quando ele não
    existe.** Quando existe e a comparação é que não é honesta — mudaram as
    lojas que reportaram, e três contra quatro medem o relatório que faltou e
    não as vendas — a frase tem de ser outra."""
    if variacao is None:
        if houve_anterior:
            return _pilula("Comparação suspensa &mdash; mudaram as lojas",
                           AVISO, AVISO_FUNDO)
        return _pilula("Sem %s para comparar" % termo, TEXTO_FRACO, "#EDF1F6")
    if variacao >= 0:
        return _pilula("&#9650; %s vs. %s" % (_percentagem(variacao), termo),
                       BOM, "#E6F6F2")
    return _pilula("&#9660; %s vs. %s" % (_percentagem(variacao), termo),
                   MAU, "#FDECEC")


def _linha_de_valor(rotulo: str, numero, *, cor: str = TEXTO) -> str:
    return (
        '<tr><td style="padding:6px 0;font-size:13px;color:%s;">%s</td>'
        '<td align="right" style="padding:6px 0;font-size:14px;font-weight:700;'
        'color:%s;white-space:nowrap;">%s</td></tr>'
        % (TEXTO_FRACO, _texto(rotulo), cor, _valor(numero)))


def _detalhe_dos_valores(valores: Dict) -> str:
    """As cobranças por baixo do líquido. Só aparecem as linhas que o relatório
    trouxe: uma linha a `—` para cada campo que a plataforma não manda enchia o
    email de travessões e escondia os que importam."""
    linhas = []
    for rotulo, chave in (("Vendas (bruto)", "bruto"), ("Comissão", "comissao"),
                          ("Outras taxas", "taxas"), ("Ajustes e estornos", "ajustes"),
                          ("IVA", "iva")):
        if valores.get(chave) is None:
            continue
        negativo = chave in ("comissao", "taxas") or (valores[chave] or 0) < 0
        linhas.append(_linha_de_valor(rotulo, valores[chave],
                                      cor=MAU if negativo else TEXTO))
    if not linhas:
        return ""
    return ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0" style="margin-top:12px;border-top:1px solid %s;">%s</table>'
            % (LINHA, "".join(linhas)))


def _bloco_de_lojas(lojas: List[Dict]) -> str:
    if not lojas:
        return ""
    maior = max([(l.get("liquido") or 0) for l in lojas] or [1]) or 1
    partes = []
    for loja in lojas:
        partes.append(
            '<tr><td style="padding:8px 0 2px;font-size:13px;color:%s;">%s</td>'
            '<td align="right" style="padding:8px 0 2px;font-size:13px;'
            'font-weight:700;color:%s;white-space:nowrap;">%s</td></tr>'
            '<tr><td colspan="2" style="padding:0 0 4px;">%s</td></tr>'
            % (TEXTO, _texto(loja.get("nome")), TEXTO, _valor(loja.get("liquido")),
               _barra_de_proporcao(loja.get("liquido") or 0, maior)))
    return ('<div style="margin-top:14px;">%s'
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'border="0">%s</table></div>'
            % (_titulo_de_seccao("Por loja"), "".join(partes)))


def _rodape_da_origem(linha: Dict) -> str:
    """De que email saíram estes números — a linha que permite ir confirmar."""
    origem = linha.get("origem") or {}
    if not origem.get("assunto"):
        return ""
    quando = origem.get("data")
    derivado = ""
    if linha.get("periodo_origem") == "calendário":
        # O relatório não dizia o período: foi o calendário que o decidiu. Quem
        # lê tem de saber que essa parte é dedução nossa e não do documento.
        derivado = " &middot; período deduzido do calendário"
    return (
        '<p style="margin:12px 0 0;font-size:11px;color:%s;line-height:1.5;">'
        'Lido do email &laquo;%s&raquo;%s%s</p>'
        % (TEXTO_FRACO, _texto(origem["assunto"]),
           " de %s" % _dia_curto(quando) if quando else "", derivado))


def _cartao_de_plataforma(linha: Dict) -> str:
    periodo = linha["periodo"]
    cabecalho = (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
        'border="0"><tr>'
        '<td style="font-size:17px;font-weight:700;color:%s;">%s</td>'
        '<td align="right" style="font-size:12px;color:%s;white-space:nowrap;">%s</td>'
        '</tr></table>'
        % (TEXTO, _texto(linha["nome"]), TEXTO_FRACO,
           _texto(_intervalo(periodo["inicio"], periodo["fim"]))))

    if linha["estado"] in ("nao_recebido", "sem_valores"):
        # **Nenhum destes dois é zero, e não são o mesmo.** "Não recebido" é
        # não ter chegado nada; "sem valores" é ter chegado e nós não termos
        # conseguido ler — e essa distinção diz a quem lê se vale a pena ir ao
        # portal da plataforma procurar o número.
        if linha["estado"] == "nao_recebido":
            titulo = "Relatório não recebido"
            frase = ("Não chegou à caixa nenhum email com o relatório de %s. Os "
                     "valores ficam por saber &mdash; não são zero."
                     % _texto(_intervalo(periodo["inicio"], periodo["fim"])))
        else:
            quantos = linha.get("lojas_que_reportaram") or 0
            titulo = "Relatório recebido, sem valores"
            frase = ("Chegaram %d relatório%s de %s, mas não foi possível ler "
                     "deles nenhum valor. Os números estão no portal da "
                     "plataforma &mdash; aqui ficam por saber, e não são zero."
                     % (quantos, "" if quantos == 1 else "s",
                        _texto(_intervalo(periodo["inicio"], periodo["fim"]))))
        corpo = (
            '<div style="margin-top:12px;padding:12px 14px;background:%s;'
            'border-radius:10px;">'
            '<p style="margin:0;font-size:14px;font-weight:700;color:%s;">%s</p>'
            '<p style="margin:6px 0 0;font-size:13px;color:%s;line-height:1.6;">'
            '%s</p></div>'
            '<div style="margin-top:12px;">%s</div>'
            % (AVISO_FUNDO, AVISO, titulo, TEXTO, frase,
               _pilula_de_pagamento(periodo, sabido=False)))
        return _cartao(cabecalho + corpo)

    valores = linha["valores"]
    pedidos = valores.get("pedidos")
    quantas = linha.get("lojas_que_reportaram") or 0
    # **De quantas lojas é este número.** A Uber manda um relatório por loja e
    # a soma de três não é a mesma coisa que a soma de quatro — quem lê tem de
    # saber quantas entraram nela sem ir contar as linhas de baixo.
    de_quantas = (' <span style="color:%s;">&middot; %d loja%s</span>'
                  % (TEXTO_FRACO, quantas, "" if quantas == 1 else "s")) if quantas else ""
    corpo = (
        '<p style="margin:14px 0 0;font-size:11px;color:%s;letter-spacing:.6px;'
        'text-transform:uppercase;font-weight:600;">A receber%s</p>'
        '<p style="margin:4px 0 0;font-size:30px;line-height:1.1;font-weight:700;'
        'color:%s;">%s</p>'
        '<p style="margin:8px 0 0;font-size:13px;color:%s;">%s</p>'
        '<div style="margin-top:12px;">%s &nbsp;%s</div>'
        % (TEXTO_FRACO, de_quantas, TEXTO, _valor(valores.get("liquido")),
           TEXTO_FRACO,
           ("%d pedido%s" % (pedidos, "" if pedidos == 1 else "s"))
           if pedidos is not None else "N.º de pedidos não indicado",
           _pilula_de_pagamento(periodo),
           _pilula_de_variacao(
               linha.get("variacao"),
               "semana anterior" if linha["ritmo"] == "semana"
               else "quinzena anterior",
               houve_anterior=(linha.get("anterior") or {}).get("liquido") is not None)))

    nota = ""
    if linha.get("notas"):
        nota = ('<p style="margin:12px 0 0;font-size:13px;color:%s;line-height:1.6;">'
                '%s</p>' % (TEXTO, _texto(linha["notas"])))

    return _cartao(cabecalho + corpo + _detalhe_dos_valores(valores)
                   + _bloco_de_lojas(linha.get("lojas") or []) + nota
                   + _rodape_da_origem(linha))


def _cartao_do_total(total: Dict, semana: Dict) -> str:
    parcial = ""
    completo = bool(total.get("completo"))
    if completo:
        marca = _pilula_de_variacao(total.get("variacao"), "semana anterior")
    else:
        # **Não se escreve "sem semana anterior para comparar".** Semana
        # anterior há; o que não há é uma comparação honesta a fazer com um
        # total ao qual falta uma plataforma — e as duas frases significam
        # coisas diferentes para quem lê.
        marca = _pilula("Comparação suspensa &mdash; falta um relatório",
                        AVISO, AVISO_FUNDO)
        em_falta = total.get("em_falta") or []
        quais = " e ".join("da %s" % nome for nome in em_falta) or "de uma plataforma"
        parcial = (
            '<p style="margin:12px 0 0;padding:10px 12px;background:%s;color:%s;'
            'border-radius:10px;font-size:13px;line-height:1.6;">'
            '<strong>Este total está incompleto.</strong> Falta o relatório %s, '
            'por isso o número acima é só do que chegou &mdash; não o compare com '
            'uma semana inteira.</p>'
            % (AVISO_FUNDO, AVISO, _texto(quais)))
    return _cartao(
        '<p style="margin:0;font-size:11px;color:%s;letter-spacing:.6px;'
        'text-transform:uppercase;font-weight:600;">A receber esta semana '
        '(Uber Eats + Bolt Food)</p>'
        '<p style="margin:6px 0 0;font-size:38px;line-height:1.1;font-weight:700;'
        'color:%s;">%s</p>'
        '<p style="margin:8px 0 0;font-size:13px;color:%s;">%s &middot; pago hoje, '
        '%s</p>'
        '<div style="margin-top:12px;">%s</div>%s'
        % (TEXTO_FRACO, TEXTO, _valor(total.get("liquido")), TEXTO_FRACO,
           ("%d pedidos" % total["pedidos"]) if total.get("pedidos") is not None
           else "n.º de pedidos por saber",
           _texto(_dia_curto(semana["pagamento"])), marca, parcial),
        margem_topo=0)


def _cartao_da_glovo(glovo: Dict) -> str:
    """A Glovo tem sempre cartão, mesmo sem relatório nenhum: o que o dono quer
    saber ao domingo à noite é em que ponto vai a quinzena e quando entra o
    dinheiro. Isso é calendário e não depende de email nenhum ter chegado."""
    em_curso, fechada = glovo["em_curso"], glovo["fechada"]
    dias_para_fechar = em_curso.get("dias_para_fechar")
    if dias_para_fechar == 0:
        estado_curso = "fecha hoje"
    elif dias_para_fechar == 1:
        estado_curso = "fecha amanhã"
    else:
        estado_curso = "faltam %d dias para fechar" % dias_para_fechar

    if fechada.get("pago"):
        estado_fechada = _pilula("Já devia ter sido paga a %s"
                                 % _dia_curto(fechada["pagamento"]), BOM, "#E6F6F2")
    else:
        dias = fechada.get("dias_para_pagamento")
        estado_fechada = _pilula(
            "Paga a %s &middot; faltam %d dia%s"
            % (_dia_curto(fechada["pagamento"]), dias, "" if dias == 1 else "s"),
            PRIMARIA, PRIMARIA_FRACA)

    calendario = (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
        'border="0" style="margin-top:4px;"><tr>'
        '<td width="50%%" valign="top" style="padding:0 8px 0 0;">'
        '<p style="margin:0;font-size:11px;color:%(fraco)s;text-transform:uppercase;'
        'letter-spacing:.6px;font-weight:600;">Quinzena a decorrer</p>'
        '<p style="margin:4px 0 0;font-size:15px;font-weight:700;color:%(texto)s;">'
        '%(curso)s</p>'
        '<p style="margin:3px 0 0;font-size:12px;color:%(fraco)s;">%(estado_curso)s '
        '&middot; paga a %(pag_curso)s</p></td>'
        '<td width="50%%" valign="top" style="padding:0 0 0 8px;">'
        '<p style="margin:0;font-size:11px;color:%(fraco)s;text-transform:uppercase;'
        'letter-spacing:.6px;font-weight:600;">Quinzena fechada</p>'
        '<p style="margin:4px 0 0;font-size:15px;font-weight:700;color:%(texto)s;">'
        '%(fechada)s</p>'
        '<div style="margin-top:6px;">%(estado_fechada)s</div></td>'
        '</tr></table>'
        % {"fraco": TEXTO_FRACO, "texto": TEXTO,
           "curso": _texto(_intervalo(em_curso["inicio"], em_curso["fim"])),
           "estado_curso": _texto(estado_curso),
           "pag_curso": _texto(_dia_curto(em_curso["pagamento"])),
           "fechada": _texto(_intervalo(fechada["inicio"], fechada["fim"])),
           "estado_fechada": estado_fechada})

    # O ponto é o carácter, e não `&middot;`: `_titulo_de_seccao` escapa o que
    # recebe (é texto, não marcação), e a entidade saía escrita à letra.
    return _cartao(_titulo_de_seccao("Glovo · calendário de pagamentos")
                   + calendario)


def _bloco_de_problemas(problemas: List[Dict]) -> str:
    if not problemas:
        return _cartao(
            _titulo_de_seccao("Problemas e cobranças")
            + '<p style="margin:0;font-size:13px;color:%s;">Nenhum relatório '
              'assinalou problemas, cobranças inesperadas ou penalizações.</p>'
            % TEXTO_FRACO)
    linhas = "".join(
        '<tr><td valign="top" style="padding:6px 10px 6px 0;white-space:nowrap;">%s</td>'
        '<td style="padding:6px 0;font-size:13px;color:%s;line-height:1.6;">%s</td></tr>'
        % (_pilula(_texto(p["plataforma"]), AVISO, AVISO_FUNDO), TEXTO,
           _texto(p["texto"]))
        for p in problemas)
    return _cartao(
        _titulo_de_seccao("Problemas e cobranças")
        + '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
          'border="0">%s</table>' % linhas)


def _bloco_de_avisos(avisos: List[str]) -> str:
    """As falhas técnicas da própria recolha (uma caixa que não respondeu, um
    anexo que não se conseguiu abrir). Vão no fim e em letra pequena, mas vão:
    são elas que explicam um "não recebido" que não é da plataforma."""
    if not avisos:
        return ""
    itens = "".join(
        '<li style="margin:0 0 6px;">%s</li>' % _texto(a) for a in avisos[:12])
    return _cartao(
        _titulo_de_seccao("Notas da recolha")
        + '<ul style="margin:0;padding-left:18px;font-size:12px;color:%s;'
          'line-height:1.6;">%s</ul>' % (TEXTO_FRACO, itens))


def assunto(dados: Dict) -> str:
    """O assunto leva o número e o aviso de parcial — é o que se lê na lista da
    caixa de entrada sem abrir nada."""
    total = dados["total_da_semana"]
    valor = _sem_entidades(_valor(total.get("liquido")))
    fim = dados["semana"]["fim"]
    marca = "" if total.get("completo") else " (parcial)"
    return "Plataformas · semana até %s/%s · %s%s" % (fim[8:10], fim[5:7], valor, marca)


def html_do_relatorio(dados: Dict, url_do_painel: Optional[str] = None) -> str:
    """O email inteiro, a partir do dicionário de `resumo.montar_relatorio`."""
    from html import escape

    semana = dados["semana"]
    total = dados["total_da_semana"]
    por_chave = {l["chave"]: l for l in dados["plataformas"]}

    cartoes_semanais = "".join(
        _cartao_de_plataforma(l) for l in dados["plataformas"] if l["ritmo"] == "semana")

    glovo = por_chave["glovo"]
    bloco_glovo = _cartao_da_glovo(dados["glovo"]) + _cartao_de_plataforma(glovo)

    botao = ""
    if url_do_painel:
        botao = (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:22px auto 0;"><tr><td style="background:%s;'
            'border-radius:10px;">'
            '<a href="%s" style="display:inline-block;padding:12px 24px;color:#FFFFFF;'
            'font-size:14px;font-weight:600;text-decoration:none;">Ver no painel</a>'
            '</td></tr></table>' % (PRIMARIA, escape(url_do_painel, quote=True)))

    preheader = "%s a receber esta semana%s" % (
        _sem_entidades(_valor(total.get("liquido"))),
        "" if total.get("completo") else " (falta um relatório)")

    return (
        '<!doctype html><html lang="pt"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<title>Plataformas de entrega</title></head>'
        '<body style="margin:0;padding:0;background:%(fundo)s;">'
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
        'Plataformas de entrega</p>'
        '<p style="margin:4px 0 0;font-size:13px;color:%(fraco)s;">'
        'Semana de %(semana)s &middot; lido até às %(ate)s de hoje</p>'
        '</td></tr>'
        '<tr><td>%(total)s</td></tr>'
        '<tr><td>%(semanais)s</td></tr>'
        '<tr><td>%(glovo)s</td></tr>'
        '<tr><td>%(problemas)s</td></tr>'
        '<tr><td>%(avisos)s</td></tr>'
        '<tr><td>%(botao)s</td></tr>'
        '<tr><td style="padding:26px 4px 0;">'
        '<p style="margin:0;font-size:11px;color:%(fraco)s;line-height:1.6;">'
        'Gestão Lisbonb &middot; enviado automaticamente às %(ate)s de segunda-feira. '
        'Um relatório que a plataforma envie depois dessa hora só entra no email da '
        'semana seguinte &mdash; e aparece no painel logo que seja lido.</p>'
        '</td></tr></table></td></tr></table></body></html>'
        % {
            "fundo": FUNDO, "largura": LARGURA, "fonte": FONTE,
            "texto": TEXTO, "fraco": TEXTO_FRACO, "cartao": CARTAO,
            "semana": _texto(_intervalo(semana["inicio"], semana["fim"])),
            "ate": _texto(dados.get("ate") or "08:00"),
            "preheader": preheader,
            "total": _cartao_do_total(total, semana),
            "semanais": cartoes_semanais,
            "glovo": bloco_glovo,
            "problemas": _bloco_de_problemas(dados.get("problemas") or []),
            "avisos": _bloco_de_avisos(dados.get("avisos") or []),
            "botao": botao,
        })
