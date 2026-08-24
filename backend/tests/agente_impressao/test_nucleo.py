"""O PROGRAMA DE IMPRESSÃO DA LOJA, provado onde se pode prová-lo.

Este ficheiro corre num Mac e não tem impressora nenhuma à frente. O que ele
prova é tudo o que **decide**: a ordem dos três passos, o que acontece quando
cada um deles falha, e o que a janela diz.

**O que ele NÃO prova, e não se finge que prova:** que os bytes entram mesmo
na impressora. Isso é `agente_impressao/windows.py`, são oito linhas, e a
única forma de as ver funcionar é carregar em «Imprimir página de teste» à
frente de uma TM-m30 ou de uma TP8002. Está dito no relatório e está dito na
docstring daquele ficheiro.
"""
import json
import logging

import pytest

from agente_impressao import nucleo


# --- Um servidor de mentira, que conta o que lhe fizeram ----------------------


class ServidorFalso:
    """Não é um mock de biblioteca: é uma lista de tudo o que aconteceu, pela
    ordem em que aconteceu. É essa ORDEM que estes testes existem para provar,
    e uma lista lê-se melhor do que três contadores."""

    def __init__(self, trabalhos=(), rebentar_em=()):
        self._trabalhos = list(trabalhos)
        self._rebentar_em = set(rebentar_em)
        self.diario = []

    def recolher(self):
        self.diario.append(("recolher",))
        if "recolher" in self._rebentar_em:
            raise nucleo.ErroDoServidor("a rede da loja está em baixo")
        trabalhos, self._trabalhos = self._trabalhos, []
        return trabalhos

    def impresso(self, trabalho_id, recibo):
        self.diario.append(("impresso", trabalho_id, recibo))
        if "impresso" in self._rebentar_em:
            raise nucleo.ErroDoServidor("O servidor respondeu 409")

    def falhou(self, trabalho_id, recibo, erro):
        self.diario.append(("falhou", trabalho_id, erro))
        if "falhou" in self._rebentar_em:
            raise nucleo.ErroDoServidor("nem a queixa passou")


def _trabalho(tipo="talao", impressora=nucleo.CAIXA, dados=b"OLA", **extra):
    import base64
    t = {
        "id": "t-%s" % tipo,
        "recibo": "r-%s" % tipo,
        "impressora": impressora,
        "tipo": tipo,
        "bytes_b64": base64.b64encode(dados).decode("ascii"),
    }
    t.update(extra)
    return t


_DEFINICOES = {
    "servidor": "https://lisbonb.com",
    "device_token": "tok",
    "impressoras": {nucleo.CAIXA: "EPSON TM-m30", nucleo.COZINHA: "TP8002"},
    "loja_nome": "Colombo",
}


class ImpressoraFalsa:
    def __init__(self, rebentar_em=()):
        self.rebentar_em = set(rebentar_em)
        self.saiu = []

    def __call__(self, nome, dados):
        if nome in self.rebentar_em:
            raise OSError("a impressora %s está sem papel" % nome)
        self.saiu.append((nome, dados))


# --- 1. A ORDEM DOS TRÊS PASSOS ----------------------------------------------


def test_imprime_ANTES_de_confirmar():
    """**É a decisão inteira deste programa.**

    Confirmar primeiro tornava cada falha de impressora num cliente sem
    documento: o servidor dava o trabalho por resolvido e ninguém voltava a
    ele. Imprimir primeiro deixa uma janela em que o papel pode sair duas
    vezes — e um talão a mais é papel, um talão a menos é obrigação legal por
    cumprir."""
    servidor = ServidorFalso([_trabalho()])
    imprimir = ImpressoraFalsa()
    ordem = []
    servidor_original_impresso = servidor.impresso

    def impresso_espiado(*args):
        ordem.append("confirmou")
        return servidor_original_impresso(*args)

    def imprimir_espiado(nome, dados):
        ordem.append("imprimiu")
        return imprimir(nome, dados)

    servidor.impresso = impresso_espiado
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir_espiado) == 1
    assert ordem == ["imprimiu", "confirmou"]


def test_o_papel_vai_para_a_impressora_ESCOLHIDA_para_aquele_papel():
    """O talão do cliente na do balcão, a ficha na da cozinha. Trocá-las
    mandava o pedido do copo ao cliente e a fatura à cozinha."""
    servidor = ServidorFalso([
        _trabalho("talao", nucleo.CAIXA, b"FATURA"),
        _trabalho("pedido", nucleo.COZINHA, b"PEDIDO"),
    ])
    imprimir = ImpressoraFalsa()
    nucleo.uma_volta(servidor, _DEFINICOES, imprimir)
    assert imprimir.saiu == [("EPSON TM-m30", b"FATURA"), ("TP8002", b"PEDIDO")]


def test_os_bytes_vao_TAL_E_QUAL():
    """O talão do cliente vem certificado do Vendus. Um byte a mais à frente
    ou atrás é mexer num documento fiscal em papel."""
    certificado = bytes(range(256))
    servidor = ServidorFalso([_trabalho(dados=certificado)])
    imprimir = ImpressoraFalsa()
    nucleo.uma_volta(servidor, _DEFINICOES, imprimir)
    assert imprimir.saiu[0][1] == certificado


# --- 2. QUANDO A IMPRESSORA FALHA --------------------------------------------


def test_a_impressora_falhou_e_o_servidor_fica_a_saber():
    servidor = ServidorFalso([_trabalho()])
    imprimir = ImpressoraFalsa(rebentar_em={"EPSON TM-m30"})
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 0
    assert ("falhou", "t-talao", "a impressora EPSON TM-m30 está sem papel") in servidor.diario
    # E nunca se diz que imprimiu o que não imprimiu.
    assert not any(d[0] == "impresso" for d in servidor.diario)


def test_uma_impressora_avariada_NAO_cala_a_outra():
    """A impressora do balcão sem papel não pode deixar a cozinha sem a ficha
    — é a razão de o servidor criar dois trabalhos e não um."""
    servidor = ServidorFalso([
        _trabalho("talao", nucleo.CAIXA),
        _trabalho("pedido", nucleo.COZINHA, b"PEDIDO"),
    ])
    imprimir = ImpressoraFalsa(rebentar_em={"EPSON TM-m30"})
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 1
    assert imprimir.saiu == [("TP8002", b"PEDIDO")]


def test_sem_impressora_escolhida_diz_o_que_falta_em_vez_de_calar():
    """Um programa por configurar que engolisse os trabalhos em silêncio
    deixava a loja a vender sem papel e sem ninguém a saber porquê."""
    servidor = ServidorFalso([_trabalho("pedido", nucleo.COZINHA)])
    meias = {**_DEFINICOES, "impressoras": {nucleo.CAIXA: "EPSON TM-m30"}}
    imprimir = ImpressoraFalsa()
    assert nucleo.uma_volta(servidor, meias, imprimir) == 0
    assert imprimir.saiu == []
    (_, _, erro), = [d for d in servidor.diario if d[0] == "falhou"]
    assert "cozinha" in erro


def test_bytes_ilegiveis_nao_viram_papel_em_branco():
    """Zero bytes a sair da impressora é uma folha em branco e a operadora a
    pensar que o sistema imprimiu."""
    servidor = ServidorFalso([_trabalho(), _trabalho("pedido", nucleo.COZINHA)])
    servidor._trabalhos = [{**_trabalho(), "bytes_b64": "isto-nao-e-base64!!"}]
    imprimir = ImpressoraFalsa()
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 0
    assert imprimir.saiu == []
    assert any(d[0] == "falhou" for d in servidor.diario)


def test_um_talao_CORROMPIDO_nao_sai_mutilado():
    """O caso que interessa não é o lixo óbvio — é o que se decodifica na
    mesma, sem se queixar, e sai da impressora com bytes a menos.

    `QUJD*REVG` tem um caractere que não é base64. Sem validação, ele é
    DEITADO FORA em silêncio e o resto decodifica-se como se nada fosse: para
    um talão certificado do Vendus, isso é um documento fiscal em papel com o
    QR mutilado e o ATCUD partido, entregue ao cliente como se estivesse bom.

    Melhor nenhum papel — que é visível no POS e se reimprime — do que um
    papel errado que ninguém desconfia."""
    servidor = ServidorFalso([{**_trabalho(), "bytes_b64": "QUJD*REVG"}])
    imprimir = ImpressoraFalsa()
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 0
    assert imprimir.saiu == []
    assert any(d[0] == "falhou" for d in servidor.diario)


def test_um_trabalho_vazio_tambem_nao():
    servidor = ServidorFalso([{**_trabalho(), "bytes_b64": ""}])
    imprimir = ImpressoraFalsa()
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 0
    assert imprimir.saiu == []


# --- 3. QUANDO A REDE FALHA --------------------------------------------------


def test_a_confirmacao_perdida_NAO_faz_reimprimir_agora():
    """O papel já saiu. Quem o devolve à fila é o servidor, quando o
    arrendamento expirar — tentar outra vez aqui, no mesmo segundo, era a
    mesma repetição sem esperar por ninguém.

    E a volta não rebenta: os outros trabalhos que vinham atrás continuam."""
    servidor = ServidorFalso(
        [_trabalho("talao", nucleo.CAIXA), _trabalho("pedido", nucleo.COZINHA, b"P")],
        rebentar_em={"impresso"},
    )
    imprimir = ImpressoraFalsa()
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 2
    assert [n for n, _ in imprimir.saiu] == ["EPSON TM-m30", "TP8002"]


def test_nem_a_queixa_passar_rebenta_a_volta():
    """Se nem o `falhou` chegar ao servidor, o arrendamento trata do assunto
    sozinho ao fim de um minuto — o trabalho volta à fila na mesma."""
    servidor = ServidorFalso(
        [_trabalho(), _trabalho("pedido", nucleo.COZINHA, b"P")],
        rebentar_em={"falhou"},
    )
    imprimir = ImpressoraFalsa(rebentar_em={"EPSON TM-m30"})
    assert nucleo.uma_volta(servidor, _DEFINICOES, imprimir) == 1


def test_nao_conseguir_BUSCAR_sobe_porque_e_isso_que_acende_o_aviso():
    """Ao contrário de tudo o resto, um erro a buscar SOBE — é o que faz a
    janela gritar «sem ligação ao servidor». Engoli-lo aqui dava um programa
    verde e calado com a loja a vender sem papel."""
    servidor = ServidorFalso(rebentar_em={"recolher"})
    with pytest.raises(nucleo.ErroDoServidor):
        nucleo.uma_volta(servidor, _DEFINICOES, ImpressoraFalsa())


# --- 4. A ESPERA -------------------------------------------------------------


def test_sem_falhas_pergunta_ao_ritmo_normal():
    assert nucleo.espera_apos_falhas(0) == nucleo.INTERVALO_SEGUNDOS


def test_com_falhas_espera_cada_vez_mais_ate_um_tecto():
    """Uma loja com a internet em baixo não martela o servidor a tarde
    inteira — mas o tecto é curto, porque o que interessa é voltar depressa ao
    normal assim que a linha voltar."""
    esperas = [nucleo.espera_apos_falhas(n) for n in range(1, 12)]
    assert esperas == sorted(esperas), "a espera nunca pode encurtar com mais falhas"
    assert esperas[0] > nucleo.INTERVALO_SEGUNDOS
    assert max(esperas) == nucleo.ESPERA_MAXIMA_SEGUNDOS
    assert esperas[-1] == nucleo.ESPERA_MAXIMA_SEGUNDOS


def test_pergunta_de_TRES_em_TRES_segundos_e_nunca_espera_mais_de_um_minuto():
    """**Os dois números à mão, e é de propósito** — o mesmo que se fez ao
    `FALHAS_ATE_AVISAR`: os testes acima comparam as constantes consigo
    próprias e por isso nenhum deles pode falhar pelo VALOR delas.

    Posto a 30 s, tudo fica verde e o talão do cliente sai meio minuto depois
    de ele pagar; e os «cinco minutos para pôr papel» que o servidor promete
    (`impressao._MAX_TENTATIVAS`) — uma conta feita com estes 3 segundos —
    passam a cinquenta. O tecto é curto pela mesma razão: o que interessa é
    voltar depressa ao normal assim que a linha voltar, não poupar pedidos a
    um servidor que já não os está a receber."""
    assert nucleo.espera_apos_falhas(0) == 3
    assert max(nucleo.espera_apos_falhas(n) for n in range(1, 20)) == 60


# --- 5. O QUE A JANELA DIZ ---------------------------------------------------


def test_por_configurar_diz_o_que_falta_fazer():
    assert nucleo.estado_legivel({}, 0) == nucleo.MSG_POR_CONFIGURAR
    assert nucleo.ha_problema({}, 0) is True


def test_a_trabalhar_diz_de_que_loja_e():
    texto = nucleo.estado_legivel(_DEFINICOES, 0)
    assert "Colombo" in texto
    assert nucleo.ha_problema(_DEFINICOES, 0) is False


def test_uma_falha_isolada_NAO_grita():
    """A rede solta um soluço e volta. Um programa que gritasse a cada soluço
    ensinava a operadora a fechá-lo — que é o pior desfecho possível."""
    assert nucleo.ha_problema(_DEFINICOES, 1) is False


def test_grita_a_TERCEIRA_falha_seguida_e_nao_antes():
    """O número escrito à mão, e é de propósito: os testes à volta usam
    `nucleo.FALHAS_ATE_AVISAR`, por isso nenhum deles pode falhar pelo valor
    dela. Posta a 99999, a suite ficava verde e a janela nunca gritava — um
    programa de impressão silenciosamente morto, que é o desfecho que este
    programa existe para não ter. Posta a 1, gritava a cada soluço da rede e
    ensinava a operadora a fechá-lo."""
    assert nucleo.ha_problema(_DEFINICOES, 2) is False, (
        "Dois soluços da rede não são uma avaria.")
    assert nucleo.ha_problema(_DEFINICOES, 3) is True, (
        "Três falhas seguidas (uns dez segundos) já é alguém que tem de saber.")


def test_falhas_seguidas_GRITAM():
    """Um programa de impressão silenciosamente morto é pior do que nenhum."""
    texto = nucleo.estado_legivel(_DEFINICOES, nucleo.FALHAS_ATE_AVISAR, "timed out")
    assert nucleo.MSG_SEM_SERVIDOR in texto
    assert "timed out" in texto
    assert nucleo.ha_problema(_DEFINICOES, nucleo.FALHAS_ATE_AVISAR) is True


# --- 6. AS DEFINIÇÕES --------------------------------------------------------


def test_um_ficheiro_partido_NAO_impede_o_programa_de_abrir(tmp_path):
    """O PC foi abaixo a meio da gravação. O programa tem de abrir a pedir
    configuração — e não rebentar em silêncio, deixando a loja a achar que
    está a imprimir."""
    caminho = tmp_path / "definicoes.json"
    caminho.write_text('{"servidor": "https://lisbo', encoding="utf-8")
    assert nucleo.ler_definicoes(str(caminho)) == {}
    assert nucleo.esta_configurado(nucleo.ler_definicoes(str(caminho))) is False


def test_um_ficheiro_que_nao_existe_tambem_nao(tmp_path):
    assert nucleo.ler_definicoes(str(tmp_path / "nao-existe.json")) == {}


def test_o_que_se_grava_e_o_que_se_le(tmp_path):
    caminho = str(tmp_path / "sub" / "definicoes.json")
    nucleo.gravar_definicoes(_DEFINICOES, caminho)
    assert nucleo.ler_definicoes(caminho) == _DEFINICOES


@pytest.mark.parametrize("em_falta", ["servidor", "device_token", "impressoras"])
def test_falta_uma_coisa_e_NAO_esta_configurado(em_falta):
    d = {k: v for k, v in _DEFINICOES.items() if k != em_falta}
    assert nucleo.esta_configurado(d) is False


def test_uma_impressora_so_nao_chega():
    """As duas ou nenhuma: com só a da caixa, a cozinha ficava a receber
    trabalhos que nunca saíam."""
    d = {**_DEFINICOES, "impressoras": {nucleo.CAIXA: "EPSON TM-m30"}}
    assert nucleo.esta_configurado(d) is False


# --- 7. A CONVERSA COM O SERVIDOR --------------------------------------------


class RespostaFalsa:
    def __init__(self, corpo):
        self._corpo = json.dumps(corpo).encode("utf-8")

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_o_token_do_dispositivo_vai_no_cabecalho_certo():
    """`X-Device-Token` e não `Authorization` — é a mesma autorização que o
    POS usa no browser (`faturacao/pos_auth.dispositivo_atual`), e o
    `Authorization` é do JWT de gestão, que aqui nunca serviria."""
    vistos = []

    def abrir(pedido, timeout):
        vistos.append(pedido)
        return RespostaFalsa({"trabalhos": []})

    nucleo.Servidor("https://lisbonb.com/", "abc123", abrir=abrir).recolher()
    (pedido,) = vistos
    assert pedido.get_header("X-device-token") == "abc123"

    # O CAMINHO não se afirma aqui, e é de propósito: este ficheiro só tem
    # acesso ao que o próprio `nucleo.py` escreve, e uma afirmação assim
    # («o caminho é o caminho») nunca pode falhar pelo valor dele — foi
    # exactamente por isso que os cinco endereços viveram meses a apontar
    # para rotas que não existiam. Quem os confronta com a tabela de rotas a
    # sério do FastAPI é `backend/tests/faturacao/test_caminhos_do_pos.py`.


def test_um_endereco_com_barra_a_mais_nao_parte_o_caminho():
    """O funcionário escreve o endereço à mão uma vez. Uma barra a mais no fim
    não pode ser a diferença entre a loja imprimir e não imprimir."""
    vistos = []

    def abrir(pedido, timeout):
        vistos.append(pedido.full_url)
        return RespostaFalsa({"trabalhos": []})

    nucleo.Servidor("https://lisbonb.com///", "t", abrir=abrir).recolher()
    (url,) = vistos
    # A propriedade é UMA: não sobra barra nenhuma. O caminho em si é
    # verificado contra as rotas reais noutro sítio (ver o teste acima).
    assert url.startswith("https://lisbonb.com/")
    assert "//" not in url[len("https://"):], (
        "O endereço ficou com uma barra a mais: %s" % url)


def test_sem_endereco_configurado_queixa_se_em_vez_de_rebentar_com_urllib():
    with pytest.raises(nucleo.ErroDoServidor):
        nucleo.Servidor("", "t").recolher()


def test_o_codigo_de_emparelhamento_vai_em_maiusculas_e_sem_espacos():
    """O gestor lê o código ao telefone e o funcionário escreve-o como o
    ouviu. O servidor compara-o em maiúsculas (`pos_auth.emparelhar`) — e um
    espaço colado no fim, do copiar-colar, não pode custar um código de uso
    único."""
    vistos = []

    def abrir(pedido, timeout):
        vistos.append(json.loads(pedido.data.decode("utf-8")))
        return RespostaFalsa({"device_token": "t", "loja_id": "l"})

    nucleo.Servidor("https://lisbonb.com", abrir=abrir).emparelhar("  a1b2c3d4 ")
    assert vistos == [{"codigo": "A1B2C3D4"}]


def test_o_servidor_a_responder_lixo_e_um_erro_do_servidor_e_nao_um_crash():
    """Um proxy da loja a devolver uma página de erro em HTML não pode matar
    o ciclo — tem de virar «sem ligação» e voltar a tentar."""
    class RespostaEmHtml(RespostaFalsa):
        def __init__(self):
            self._corpo = b"<html>502 Bad Gateway</html>"

    with pytest.raises(nucleo.ErroDoServidor):
        nucleo.Servidor(
            "https://lisbonb.com", "t", abrir=lambda p, t: RespostaEmHtml()).recolher()


def test_o_PRIMEIRO_duplo_clique_num_PC_NOVO_consegue_abrir_o_log(tmp_path, monkeypatch):
    """O passo 4 do manual: copiar o `.exe` para o PC e fazer duplo clique.

    A pasta `%APPDATA%\\AgenteImpressaoLacai` só nasce quando se GRAVAM as
    definições — e no primeiro arranque ainda não há definições nenhumas. O
    `logging.basicConfig` do arranque rebentava ali com `FileNotFoundError`, e
    com `console=False` no `.exe` isso não dá erro nenhum: não acontece
    **nada**. Quem foi à loja ficava a olhar para um duplo clique sem
    resposta.

    A prova é abrir o ficheiro do MESMO modo que o `logging` o abre — um teste
    que só olhasse para a string do caminho passava com a pasta inexistente,
    que é exactamente o defeito."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert not (tmp_path / "Roaming").exists(), "o PC é novo: não há nada lá"

    logging.FileHandler(nucleo.caminho_do_log(), encoding="utf-8").close()
