"""**As fotos dos produtos** — as que vêm do Vendus e as que o dono carrega.

O pedido do dono: «em produtos no backoffice ainda não consigo colocar as
imagens dos produtos. você consegue puxar do Vendus?» … «pode pegar as imagens
do vendus. as que você não conseguir deixe no backoffice a opção de fazer
upload.»

**O que foi confirmado da API do Vendus, e onde** (documentação oficial da v1.1,
https://www.vendus.pt/ws/v1.1/products.doc, lida na íntegra):

- **pedido**: `image`, `string`, exemplo `https://www.site.com/img/1.png`,
  descrição «Image — Either an url or a base64 encoded string». (Nós NÃO
  escrevemos: o cliente do Vendus deste módulo é só de leitura.)
- **resposta**: `images`, tipo `array`, descrição «Images List», e cada item
  tem `xs` («Small Image Url», exemplo `/foto/b906f77_xs.png`) e `m` («Medium
  Image Url», exemplo `/foto/b906f77_m.png`).

**Os endereços vêm RELATIVOS** — `/foto/…`, não `https://…`. É o detalhe que
uma leitura à pressa deixa passar, e um `<img src="/foto/b906f77_m.png">` no
nosso domínio pede a foto ao NOSSO servidor e desenha o ícone de imagem
partida. Por isso o leitor absolutiza contra `https://www.vendus.pt`.

**Não foi feita uma chamada real à API**: não há chave Vendus neste repositório
(o `.env` só existe no servidor) e a única chave nesta máquina é de OUTRA
empresa. Por isso o leitor não confia na forma: aceita a lista, aceita um
objecto solto, aguenta `images` ausente, vazio, com itens que não são
dicionários, e recusa tudo o que não acabe num endereço `http(s)`.

**A REGRA DE PRECEDÊNCIA**, que é o que o dono não pode perder: uma foto
carregada À MÃO no backoffice **ganha sempre** a uma reimportação. Escrita por
extenso em `fotos.foto_da_reimportacao`, e guardada aqui caso a caso.
"""
import io
import uuid

import pytest
from fastapi import HTTPException

from faturacao import fotos as fotos_mod
from faturacao.fotos import (
    MAXIMO_BYTES,
    foto_da_reimportacao,
    nome_de_ficheiro_seguro,
    origem_da_foto_gravada,
    origem_de_uma_gravacao_do_backoffice,
    tipo_pela_assinatura,
)
from faturacao.importacao import _extrair_foto


# --- O que o Vendus devolve ---------------------------------------------------


def test_a_foto_do_vendus_vem_do_campo_images_e_ABSOLUTIZADA():
    """O exemplo literal da documentação: `/foto/b906f77_m.png`. Relativo.

    Sem absolutizar, o `<img>` do POS pede `/foto/b906f77_m.png` ao NOSSO
    domínio, leva um 404 e desenha o ícone de imagem partida em cada mosaico."""
    assert _extrair_foto({"images": [
        {"xs": "/foto/b906f77_xs.png", "m": "/foto/b906f77_m.png"}]}
    ) == "https://www.vendus.pt/foto/b906f77_m.png"


def test_prefere_o_MEDIO_ao_pequeno():
    """A grelha do POS desenha mosaicos de 4:3 num PC de loja, e o `xs` é a
    miniatura da lista do Vendus — esticada no mosaico, lê-se desfocada. O `m`
    serve os dois sítios onde a foto aparece (a grelha e o diálogo do
    produto)."""
    imagens = {"xs": "/foto/a_xs.png", "m": "/foto/a_m.png"}
    assert _extrair_foto({"images": [imagens]}).endswith("_m.png")


def test_sem_o_medio_serve_o_pequeno():
    """Uma foto desfocada é melhor do que nenhuma — o que não se faz é
    inventar o nome do ficheiro médio a partir do pequeno."""
    assert _extrair_foto({"images": [{"xs": "/foto/a_xs.png"}]}) == (
        "https://www.vendus.pt/foto/a_xs.png")


def test_um_endereco_ja_absoluto_fica_como_esta():
    assert _extrair_foto({"images": [{"m": "https://cdn.exemplo.pt/a.png"}]}) == (
        "https://cdn.exemplo.pt/a.png")


def test_images_como_OBJECTO_solto_tambem_serve():
    """A documentação diz `array`; não houve chamada real que o confirmasse, e
    um leitor que só aceite listas devolve `None` em silêncio se a conta
    responder com um objecto. O custo de aceitar os dois é uma linha."""
    assert _extrair_foto({"images": {"m": "/foto/a_m.png"}}) == (
        "https://www.vendus.pt/foto/a_m.png")


@pytest.mark.parametrize("produto", [
    {},                                   # sem o campo
    {"images": []},                       # a lista vazia
    {"images": None},
    {"images": [None, "não é um dicionário"]},
    {"images": [{}]},                     # o item sem xs nem m
    {"images": [{"m": ""}]},
    {"images": [{"m": "   "}]},
    {"images": [{"m": 12345}]},
])
def test_um_produto_sem_imagem_utilizavel_da_NONE(produto):
    assert _extrair_foto(produto) is None


@pytest.mark.parametrize("endereco", [
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "ftp://exemplo.pt/a.png",
    "//exemplo.pt/a.png",
])
def test_um_endereco_que_nao_e_http_e_RECUSADO(endereco):
    """O que sai daqui vai parar a um `src` de `<img>` no ecrã do balcão. Um
    `javascript:` num atributo desses é uma porta, e o Vendus é uma fonte
    externa — o `//` sem esquema é o caso silencioso, que num ecrã servido por
    https vai buscar a imagem a outro sítio qualquer."""
    assert _extrair_foto({"images": [{"m": endereco}]}) is None


# --- A precedência ------------------------------------------------------------


_NOSSA = "/api/faturacao/produtos/fotos/1111.webp"
_DO_VENDUS = "https://www.vendus.pt/foto/b906f77_m.png"
_OUTRA_DO_VENDUS = "https://www.vendus.pt/foto/outra_m.png"


def test_um_produto_SEM_foto_recebe_a_do_vendus():
    assert foto_da_reimportacao({}, _DO_VENDUS) == (_DO_VENDUS, "vendus")


def test_um_produto_sem_foto_e_sem_imagem_no_vendus_continua_sem_foto():
    assert foto_da_reimportacao({}, None) == (None, None)


def test_a_foto_que_VEIO_do_vendus_actualiza_se():
    """O Vendus é a fonte de verdade para o que o dono mudou LÁ — como o nome,
    o preço e o IVA. Uma foto que ele trocou no Vendus tem de chegar aqui."""
    existente = {"foto_url": _DO_VENDUS, "foto_origem": "vendus"}
    assert foto_da_reimportacao(existente, _OUTRA_DO_VENDUS) == (
        _OUTRA_DO_VENDUS, "vendus")


def test_A_FOTO_DO_DONO_GANHA_SEMPRE():
    """**A regra que o dono não pode perder.** Ele carregou a foto boa aqui; o
    Vendus tem outra (a velha, a errada, a do fornecedor). Uma reimportação
    não a substitui — quem AGIU aqui ganha a um automatismo."""
    existente = {"foto_url": _NOSSA, "foto_origem": "nossa"}
    assert foto_da_reimportacao(existente, _DO_VENDUS) == (_NOSSA, "nossa")


def test_uma_reimportacao_NUNCA_APAGA_uma_foto():
    """O caso nomeado no pedido: o produto não tem imagem nenhuma no Vendus, e
    aqui tem a que o dono carregou. Reimportar não pode deixar o ecrã em
    branco.

    E vale para as duas origens: o Vendus deixar de ter a imagem que já cá
    mandou não é um pedido para a apagar daqui."""
    do_dono = {"foto_url": _NOSSA, "foto_origem": "nossa"}
    assert foto_da_reimportacao(do_dono, None) == (_NOSSA, "nossa")
    do_vendus = {"foto_url": _DO_VENDUS, "foto_origem": "vendus"}
    assert foto_da_reimportacao(do_vendus, None) == (_DO_VENDUS, "vendus")


def test_uma_foto_LEGADA_sem_origem_conta_como_do_dono():
    """**Os produtos que já estão em produção.** Até hoje o único caminho para
    pôr uma foto era colar um endereço no backoffice — à mão. Um `foto_url` sem
    `foto_origem` só pode ter vindo de lá, e a direcção segura é a que nunca
    destrói o trabalho de alguém."""
    legada = {"foto_url": "https://exemplo.pt/acai.jpg"}
    assert origem_da_foto_gravada(legada) == "nossa"
    assert foto_da_reimportacao(legada, _DO_VENDUS) == (
        "https://exemplo.pt/acai.jpg", "nossa")


def test_um_produto_sem_foto_nenhuma_nao_tem_origem():
    assert origem_da_foto_gravada({}) is None
    assert origem_da_foto_gravada({"foto_url": None}) is None
    assert origem_da_foto_gravada({"foto_url": ""}) is None


# --- A origem quando se grava pelo backoffice ---------------------------------


def test_pôr_uma_foto_pelo_backoffice_marca_a_como_NOSSA():
    assert origem_de_uma_gravacao_do_backoffice(_NOSSA, {}) == "nossa"


def test_TROCAR_a_foto_do_vendus_pelo_backoffice_passa_a_ser_nossa():
    existente = {"foto_url": _DO_VENDUS, "foto_origem": "vendus"}
    assert origem_de_uma_gravacao_do_backoffice(_NOSSA, existente) == "nossa"


def test_gravar_o_produto_SEM_MEXER_na_foto_nao_lhe_muda_a_origem():
    """**O defeito que a regra fácil traria.** «Tudo o que passa pelo
    backoffice é nosso» congelava a foto do Vendus na primeira vez que alguém
    corrigisse o NOME do produto — e o dono deixava de receber lá as trocas de
    foto sem perceber porquê."""
    existente = {"foto_url": _DO_VENDUS, "foto_origem": "vendus"}
    assert origem_de_uma_gravacao_do_backoffice(_DO_VENDUS, existente) == "vendus"


def test_TIRAR_a_foto_pelo_backoffice_deixa_o_produto_sem_origem():
    """E a reimportação seguinte volta a poder trazer a do Vendus — tirar a
    foto é dizer «não quero esta», não «nunca mais quero nenhuma»."""
    existente = {"foto_url": _NOSSA, "foto_origem": "nossa"}
    assert origem_de_uma_gravacao_do_backoffice(None, existente) is None
    assert origem_de_uma_gravacao_do_backoffice("", existente) is None


# --- O ficheiro que chega do computador do dono -------------------------------

_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 40


@pytest.mark.parametrize("conteudo,tipo", [
    (_JPEG, "image/jpeg"), (_PNG, "image/png"), (_WEBP, "image/webp")])
def test_os_tres_formatos_aceites_reconhecem_se_pelos_PRIMEIROS_BYTES(conteudo, tipo):
    assert tipo_pela_assinatura(conteudo) == tipo


@pytest.mark.parametrize("conteudo", [
    b"",
    b"GIF89a" + b"\x00" * 40,                       # GIF: não está na lista
    b"%PDF-1.7\n" + b"\x00" * 40,                   # um PDF com o nome mudado
    b"<?php system($_GET['c']); ?>",                # o caso que interessa
    b"RIFF\x00\x00\x00\x00WAVE",                    # RIFF, mas não WEBP
    b"\xff\xd8",                                    # truncado
])
def test_o_que_nao_e_uma_imagem_das_tres_e_RECUSADO(conteudo):
    """**Pelos bytes, nunca pelo `Content-Type` nem pela extensão.** Os dois
    são escritos por quem envia. Um `.png` com PHP lá dentro guardado numa
    pasta servida por HTTP é a forma clássica desta rota correr mal."""
    assert tipo_pela_assinatura(conteudo) is None


def test_o_nome_do_ficheiro_e_ESCOLHIDO_POR_NOS_e_nunca_o_que_veio():
    """O nome que o browser manda é texto do cliente: `../../.env` é um nome de
    ficheiro válido. O que se grava é um UUID nosso mais a extensão do tipo
    reconhecido pelos bytes."""
    nome = nome_de_ficheiro_seguro("image/webp")
    corpo, _, extensao = nome.partition(".")
    assert extensao == "webp"
    uuid.UUID(corpo)  # rebenta se não for um UUID


def test_dois_carregamentos_nunca_escrevem_o_mesmo_ficheiro():
    assert nome_de_ficheiro_seguro("image/png") != nome_de_ficheiro_seguro("image/png")


# --- A rota do carregamento ----------------------------------------------------


class _FicheiroFalso:
    """O que o FastAPI entrega em `UploadFile` — reduzido ao que a rota usa."""

    def __init__(self, conteudo, filename="acai.jpg", content_type="image/jpeg"):
        self.file = io.BytesIO(conteudo)
        self.filename = filename
        self.content_type = content_type

    async def read(self, tamanho=-1):
        return self.file.read(tamanho)


def _corre(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(fotos_mod, "_PASTA", tmp_path / "fotos")
    return tmp_path / "fotos"


def test_uma_foto_boa_e_gravada_e_devolve_o_endereco(pasta):
    resposta = _corre(fotos_mod.carregar_foto(
        ficheiro=_FicheiroFalso(_JPEG), _=None))

    assert resposta["foto_url"].startswith("/api/faturacao/produtos/fotos/")
    assert resposta["foto_url"].endswith(".jpg")
    gravados = list(pasta.iterdir())
    assert len(gravados) == 1
    assert gravados[0].read_bytes() == _JPEG


def test_o_endereco_gravado_e_RELATIVO(pasta):
    """O portal responde em dois domínios (`lisbonb.com` e `rh.lisbonb.com`,
    que fica para sempre por causa das apps instaladas). Um endereço absoluto
    gravado com um deles ficava errado no outro — e ficaria errado outra vez no
    dia em que o domínio mudasse."""
    resposta = _corre(fotos_mod.carregar_foto(
        ficheiro=_FicheiroFalso(_JPEG), _=None))
    assert not resposta["foto_url"].startswith("http")


def test_um_ficheiro_que_nao_e_imagem_e_RECUSADO_e_NAO_FICA_no_disco(pasta):
    """Recusado pelos bytes, e sem deixar rasto: gravar primeiro e apagar
    depois deixava o ficheiro servível durante o intervalo."""
    with pytest.raises(HTTPException) as erro:
        _corre(fotos_mod.carregar_foto(
            ficheiro=_FicheiroFalso(b"<?php system($_GET['c']); ?>",
                                    filename="acai.png",
                                    content_type="image/png"),
            _=None))

    assert erro.value.status_code == 422
    assert "JPEG, PNG ou WebP" in erro.value.detail
    assert not pasta.exists() or list(pasta.iterdir()) == []


def test_uma_foto_GRANDE_DE_MAIS_e_recusada_com_o_tamanho_a_dizer_porque(pasta):
    """**A grelha do POS carrega dezenas destas de uma vez, num PC de loja.**
    O ecrã do backoffice reduz a foto antes de a enviar; este tecto é o que
    garante o que fica GRAVADO, mesmo que o ecrã seja contornado."""
    enorme = _JPEG + b"\x00" * MAXIMO_BYTES
    with pytest.raises(HTTPException) as erro:
        _corre(fotos_mod.carregar_foto(ficheiro=_FicheiroFalso(enorme), _=None))

    assert erro.value.status_code == 413
    assert "512 KB" in erro.value.detail
    assert not pasta.exists() or list(pasta.iterdir()) == []


def test_um_ficheiro_VAZIO_e_recusado(pasta):
    with pytest.raises(HTTPException):
        _corre(fotos_mod.carregar_foto(ficheiro=_FicheiroFalso(b""), _=None))


# --- A rota que serve a foto ---------------------------------------------------


@pytest.mark.parametrize("nome", [
    "../../../backend/.env",
    "..%2f..%2f.env",
    "/etc/passwd",
    "1111.webp/../../.env",
    "a b.webp",
    "1111.php",
    "1111.webp.php",
    ".env",
    "",
])
def test_a_rota_que_SERVE_recusa_qualquer_nome_que_nao_seja_o_nosso(pasta, nome):
    """A pasta é servida por HTTP: o nome do ficheiro é a única coisa que o
    pedido controla, e tem de casar EXACTAMENTE com a forma que gravamos —
    um UUID e uma das três extensões."""
    with pytest.raises(HTTPException) as erro:
        _corre(fotos_mod.servir_foto(nome))
    assert erro.value.status_code == 404


def test_a_foto_gravada_e_MESMO_servida(pasta):
    resposta = _corre(fotos_mod.carregar_foto(
        ficheiro=_FicheiroFalso(_WEBP, content_type="image/webp"), _=None))
    nome = resposta["foto_url"].rsplit("/", 1)[-1]

    ficheiro = _corre(fotos_mod.servir_foto(nome))

    assert ficheiro.path == str(pasta / nome)
    assert ficheiro.media_type == "image/webp"


def test_uma_foto_que_nao_existe_da_404_e_nao_rebenta(pasta):
    with pytest.raises(HTTPException) as erro:
        _corre(fotos_mod.servir_foto("%s.webp" % uuid.uuid4()))
    assert erro.value.status_code == 404


# --- A importação, de ponta a ponta --------------------------------------------
#
# A regra de precedência corrida sobre a rota real de sincronização, com uma
# base de dados COM ESTADO — a importação corrida DUAS vezes sobre a MESMA
# base, que é a única forma de provar o que uma REimportação faz.

from faturacao.importacao import _sincronizar_produtos  # noqa: E402
from .test_importacao import DbMemoria  # noqa: E402


def _do_vendus(**over):
    p = {"id": "v-1", "title": "Açaí Regular", "gross_price": "10.20",
         "tax_id": "INT", "category_id": "c-1",
         "images": [{"xs": "/foto/a_xs.png", "m": "/foto/a_m.png"}]}
    p.update(over)
    return p


def _importa(db, produtos):
    return _corre(_sincronizar_produtos(db, produtos, {"c-1": "cat-local"}))


def test_a_importacao_TRAZ_a_foto_do_vendus():
    """O pedido do dono: «pode pegar as imagens do vendus»."""
    db = DbMemoria()
    _importa(db, [_do_vendus()])

    guardado = db.produtos.documentos[0]
    assert guardado["foto_url"] == "https://www.vendus.pt/foto/a_m.png"
    assert guardado["foto_origem"] == "vendus"


def test_um_produto_sem_imagem_no_vendus_entra_sem_foto_e_nao_falha():
    """«as que você não conseguir deixe no backoffice a opção de fazer
    upload» — o produto entra à mesma, com o resto todo certo."""
    db = DbMemoria()
    resultado = _importa(db, [_do_vendus(images=[])])

    assert resultado["criados"] == 1 and resultado["problemas"] == []
    guardado = db.produtos.documentos[0]
    assert guardado["foto_url"] is None
    assert guardado["preco"] == 10.20 and guardado["tax_id"] == "INT"


def test_UMA_REIMPORTACAO_NAO_APAGA_A_FOTO_QUE_O_DONO_CARREGOU():
    """**O caso nomeado no pedido, corrido de ponta a ponta.** O produto não
    tem imagem nenhuma no Vendus; o dono carregou a foto boa aqui. Reimportar
    actualiza o preço e deixa a foto em paz."""
    db = DbMemoria()
    _importa(db, [_do_vendus(images=[])])
    # O dono carrega a foto no backoffice.
    db.produtos.documentos[0].update(foto_url=_NOSSA, foto_origem="nossa")

    _importa(db, [_do_vendus(images=[], gross_price="11.35")])

    guardado = db.produtos.documentos[0]
    assert guardado["foto_url"] == _NOSSA, (
        "A reimportação apagou a foto que o dono carregou.")
    assert guardado["foto_origem"] == "nossa"
    assert guardado["preco"] == 11.35, (
        "E o resto continua a vir do Vendus — a foto não congela o produto.")


def test_a_foto_do_dono_GANHA_a_do_vendus_numa_reimportacao():
    """A outra metade: o Vendus TEM uma imagem, e o dono escolheu outra aqui.
    Quem agiu ganha ao automatismo."""
    db = DbMemoria()
    _importa(db, [_do_vendus()])
    db.produtos.documentos[0].update(foto_url=_NOSSA, foto_origem="nossa")

    _importa(db, [_do_vendus()])

    assert db.produtos.documentos[0]["foto_url"] == _NOSSA


def test_uma_foto_TROCADA_no_vendus_chega_ca_na_reimportacao():
    """E o controlo que impede a regra de ser «nunca actualizar»: a foto que
    veio de lá e que ele trocou lá tem de chegar aqui, como o nome e o preço."""
    db = DbMemoria()
    _importa(db, [_do_vendus()])
    _importa(db, [_do_vendus(images=[{"m": "/foto/nova_m.png"}])])

    assert db.produtos.documentos[0]["foto_url"] == (
        "https://www.vendus.pt/foto/nova_m.png")
    assert len(db.produtos.documentos) == 1, "A reimportação duplicou o produto."


def test_um_produto_LEGADO_com_foto_a_mao_e_sem_origem_sobrevive_a_primeira_reimportacao():
    """Os produtos que já estão em produção com um endereço colado à mão e sem
    `foto_origem` nenhum: a primeira importação com fotos não os pode pisar."""
    db = DbMemoria()
    db.produtos.documentos.append({
        "id": "p-legado", "nome": "Açaí Regular", "categoria_id": "cat-local",
        "preco": 10.20, "tax_id": "INT", "vendus_ref": "v-1",
        "foto_url": "https://exemplo.pt/acai.jpg",
        "grupos_personalizacao": [], "ativo": True,
    })

    _importa(db, [_do_vendus()])

    guardado = db.produtos.documentos[0]
    assert guardado["foto_url"] == "https://exemplo.pt/acai.jpg"
    assert guardado["foto_origem"] == "nossa"


def test_a_importacao_continua_a_preservar_os_grupos_e_o_ativo():
    """O guarda vizinho, aqui só para não se perder de vista: a foto entra na
    lista do que a importação decide, e `grupos_personalizacao`/`ativo`
    continuam a ser só nossos."""
    db = DbMemoria()
    _importa(db, [_do_vendus()])
    db.produtos.documentos[0].update(grupos_personalizacao=["g-1"], ativo=False)

    _importa(db, [_do_vendus()])

    guardado = db.produtos.documentos[0]
    assert guardado["grupos_personalizacao"] == ["g-1"]
    assert guardado["ativo"] is False


# --- As rotas, resolvidas contra o router a sério ------------------------------


def test_as_rotas_das_fotos_nao_sao_TAPADAS_pelas_do_catalogo():
    """As fotos vivem debaixo de `/produtos/`, e o catálogo já lá tem
    `/produtos/{produto_id}`. O FastAPI resolve pela ORDEM de registo: uma rota
    tapada pela outra não parte nada em lado nenhum — responde 404 «Produto não
    encontrado» a um pedido de foto, e ninguém liga os dois factos.

    Resolvido contra o router A SÉRIO, e não pela leitura da lista."""
    from faturacao import router

    def quem_responde(metodo, caminho):
        for rota in router.routes:
            if metodo not in getattr(rota, "methods", ()):
                continue
            if rota.path_regex.match(caminho):
                return rota.endpoint.__name__
        return None

    assert quem_responde("POST", "/api/faturacao/produtos/fotos") == "carregar_foto"
    assert quem_responde(
        "GET", "/api/faturacao/produtos/fotos/%s.webp" % uuid.uuid4()) == "servir_foto"
    # E o contrário: o produto continua a ser servido pela rota do catálogo.
    assert quem_responde("GET", "/api/faturacao/produtos/p-1") == "obter_produto"


def test_CARREGAR_uma_foto_continua_a_exigir_o_gestor():
    """A rota que SERVE é pública (é um `<img>`, não leva cabeçalho nenhum —
    ver `test_protecao_rotas.py`). A que GRAVA, não: escreve no disco do
    servidor."""
    from faturacao import router
    from faturacao.auth import gestor_atual

    def dependencias(rota):
        encontrados = set()

        def procura(d):
            for filha in d.dependencies:
                encontrados.add(filha.call)
                procura(filha)

        procura(rota.dependant)
        return encontrados

    carregar = [r for r in router.routes
                if r.path == "/api/faturacao/produtos/fotos" and "POST" in r.methods]
    assert len(carregar) == 1
    assert gestor_atual in dependencias(carregar[0])
