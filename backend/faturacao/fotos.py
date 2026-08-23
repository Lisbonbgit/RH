"""As FOTOS dos produtos: as que se puxam do Vendus e as que o dono carrega.

O pedido do dono, por palavras dele: «em produtos no backoffice ainda não
consigo colocar as imagens dos produtos. você consegue puxar do Vendus?» …
«pode pegar as imagens do vendus. as que você não conseguir deixe no backoffice
a opção de fazer upload.»

**ONDE FICAM, e porquê.** As que se PUXAM do Vendus ficam a apontar para lá (é
o endereço que ele dá, e não há outro); as que o dono CARREGA ficam no NOSSO
servidor. A razão é o objectivo do projecto — largar o Vendus. Mandá-las para
lá (a API aceita: o campo `image` de `POST /products` recebe um URL ou o
ficheiro em base64) era pôr as fotos do dono a depender exactamente do sistema
que queremos deixar, e no dia em que a conta fechasse iam com ela. Além disso o
cliente Vendus deste módulo é, e continua a ser, **só de leitura** (ver
`vendus/cliente.py`): a conta emite faturas reais da Fordaimon Foods, e a
primeira escrita que este sistema lhe fizer não vai ser uma foto.

**A pasta é a que já existe e já sobrevive ao deploy.** `uploads/` está
declarada como volume no `docker-compose.yml` (`uploads_data:/app/uploads`) e
por isso atravessa um `docker compose up -d --build` — as fotos ficam em
`uploads/faturacao/produtos/`. Não há volume novo para alguém se esquecer de
criar; a alternativa (uma pasta dentro da imagem) apagava as fotos todas no
primeiro deploy.

**Servidas por uma rota PÚBLICA**, e é uma decisão, não um esquecimento: um
`<img src="…">` não leva cabeçalho `Authorization` nenhum — nem o JWT do
backoffice nem o token do dispositivo do POS. Ou a rota é pública, ou as fotos
não aparecem em ecrã nenhum. O que fica exposto é a fotografia de um açaí, com
um nome de ficheiro que é um UUID (não se adivinha, não se enumera). A rota
está declarada em `test_protecao_rotas.py` como pública, ao lado da `/saude` e
do emparelhamento — em consciência, com esta razão escrita.

**O que se aceita, e porquê esses números.** JPEG, PNG e WebP; no máximo
512 KB por ficheiro. A grelha do POS carrega DEZENAS de fotos de uma vez, num
PC de loja: 40 fotos de telemóvel a 4 MB são 160 MB por cada vez que a
operadora abre o ecrã de venda. O ecrã do backoffice reduz a imagem ANTES de a
enviar (ver `lib/faturacao.js::reduzirImagem` — 640 px no lado maior, WebP) e o
que sai de lá anda pelos 40–80 KB; este tecto é o que garante o que fica
GRAVADO mesmo que o ecrã seja contornado. E o tipo reconhece-se pelos PRIMEIROS
BYTES, nunca pelo `Content-Type` nem pela extensão — os dois são escritos por
quem envia, e um `.png` com PHP lá dentro numa pasta servida por HTTP é a forma
clássica de esta rota correr mal.
"""
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .auth import gestor_atual

logger = logging.getLogger(__name__)

router = APIRouter()

# A raiz do backend — a mesma que o `server.py` usa para o `uploads/`.
_RAIZ = Path(__file__).resolve().parent.parent
_PASTA = Path(os.environ.get("FAT_FOTOS_DIR") or (_RAIZ / "uploads" / "faturacao" / "produtos"))

# O prefixo por onde as fotos são pedidas. RELATIVO de propósito: o portal
# responde em dois domínios (`lisbonb.com` e `rh.lisbonb.com`, que fica para
# sempre porque as apps instaladas têm-no cozido), e um endereço absoluto
# gravado com um deles ficava errado no outro. Quem desenha a imagem resolve-o
# contra a base da API que estiver a usar (`urlDaFotoPos`/`urlDaFoto`).
PREFIXO_PUBLICO = "/api/faturacao/produtos/fotos/"

MAXIMO_BYTES = 512 * 1024

# Assinatura -> tipo. Os três formatos que um browser desenha em `<img>` sem
# pensar duas vezes, e que o `canvas.toBlob` do backoffice produz.
_ASSINATURAS = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
_EXTENSOES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_TIPOS = {v: k for k, v in _EXTENSOES.items()}

# O nome que gravamos, e o ÚNICO que a rota que serve aceita: um UUID e uma
# das três extensões. É a defesa contra o `../../.env` — o nome do ficheiro é
# a única parte do pedido que o cliente controla.
_NOME_VALIDO = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)$"
)

_MSG_TIPO = (
    "Só se aceitam imagens JPEG, PNG ou WebP — e o ficheiro é reconhecido "
    "pelo conteúdo, não pelo cabeçalho nem pela extensão. Este não é nenhuma das três."
)
_MSG_TAMANHO = (
    "A imagem tem %d KB e o máximo é 512 KB. A grelha do POS carrega dezenas "
    "de fotos de uma vez num PC de loja — escolha uma imagem mais pequena."
)


def tipo_pela_assinatura(conteudo: bytes) -> Optional[str]:
    """O tipo de imagem lido dos PRIMEIROS BYTES — `None` se não for uma das
    três que aceitamos.

    Nunca pelo `Content-Type` do pedido nem pela extensão do nome: os dois são
    escritos por quem envia. O WebP tem de ser verificado em duas partes (é um
    contentor RIFF: `RIFF` + 4 bytes de tamanho + `WEBP`), senão um `.wav`
    passava por imagem."""
    if not conteudo:
        return None
    for assinatura, tipo in _ASSINATURAS:
        if conteudo.startswith(assinatura):
            return tipo
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "image/webp"
    return None


def nome_de_ficheiro_seguro(tipo: str) -> str:
    """O nome com que a foto fica gravada — escolhido POR NÓS.

    O `filename` que o browser manda é texto do cliente (`../../.env` é um nome
    de ficheiro perfeitamente válido) e não entra aqui de forma nenhuma. Um
    UUID novo de cada vez também faz do endereço uma chave imutável: uma foto
    trocada é um endereço novo, e por isso a resposta pode ser guardada em
    cache para sempre sem nunca mostrar a foto velha."""
    return "%s.%s" % (uuid.uuid4(), _EXTENSOES[tipo])


# --- A ORIGEM da foto, e a precedência numa reimportação ----------------------
#
# É a decisão que o pedido do dono obriga a tomar: uma foto que ele carregou à
# mão NÃO pode ser apagada por uma reimportação de um produto que, no Vendus,
# não tem imagem nenhuma.
#
# A regra, por extenso: **quem AGIU aqui ganha a um automatismo, e uma
# reimportação nunca APAGA uma foto.** Em cada linha do quadro, o que fica:
#
#   foto aqui        | Vendus tem | fica
#   -----------------|------------|-------------------------------------------
#   nenhuma          | sim        | a do Vendus (origem "vendus")
#   nenhuma          | não        | nenhuma
#   veio do Vendus   | sim        | a NOVA do Vendus — ele é a fonte de verdade
#                    |            | do que o dono mudou LÁ, como o nome/preço
#   veio do Vendus   | não        | a que cá está (deixar de a ter lá não é um
#                    |            | pedido para a apagar aqui)
#   carregada aqui   | sim        | a NOSSA — o dono escolheu-a de propósito
#   carregada aqui   | não        | a NOSSA
#
# O `foto_origem` é o campo que torna as duas últimas linhas distintas das duas
# do meio. Sem ele, ou o Vendus pisava a foto do dono, ou nunca mais
# actualizava nenhuma.


def origem_da_foto_gravada(produto: Optional[Dict]) -> Optional[str]:
    """De onde veio a foto que este produto tem — `"nossa"`, `"vendus"`, ou
    `None` se não tem foto nenhuma.

    **Uma foto sem `foto_origem` conta como NOSSA**, e é a decisão que protege
    o que já está em produção: até hoje o único caminho para pôr uma foto num
    produto era colar um endereço no campo do backoffice, à mão. Tudo o que lá
    esteja foi posto por alguém, e a direcção segura é a que nunca destrói o
    trabalho de ninguém."""
    if not (produto or {}).get("foto_url"):
        return None
    return produto.get("foto_origem") or "nossa"


def foto_da_reimportacao(
    existente: Optional[Dict], foto_do_vendus: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """O par `(foto_url, foto_origem)` que uma reimportação deve gravar. Ver o
    quadro acima."""
    origem = origem_da_foto_gravada(existente)
    if origem == "nossa":
        return (existente or {}).get("foto_url"), "nossa"
    if foto_do_vendus:
        return foto_do_vendus, "vendus"
    return (existente or {}).get("foto_url"), origem


def origem_de_uma_gravacao_do_backoffice(
    nova_url: Optional[str], existente: Optional[Dict]
) -> Optional[str]:
    """A origem a gravar quando o produto é guardado pelo ECRÃ do backoffice.

    **Não é «tudo o que passa por aqui é nosso»**, e a diferença tem
    consequência: com essa regra, corrigir o NOME de um produto congelava a
    foto que tinha vindo do Vendus, e o dono deixava de receber aqui as trocas
    que fizesse lá — sem perceber porquê. O que marca a foto como nossa é
    MEXER-LHE.

    Tirar a foto devolve `None`: a reimportação seguinte volta a poder trazer a
    do Vendus. Apagar a foto é dizer «não quero esta», não «nunca mais quero
    nenhuma»."""
    if not nova_url:
        return None
    if nova_url == (existente or {}).get("foto_url"):
        return origem_da_foto_gravada(existente)
    return "nossa"


# --- As duas rotas -------------------------------------------------------------


@router.post("/produtos/fotos", status_code=201)
async def carregar_foto(
    ficheiro: UploadFile = File(...), _: dict = Depends(gestor_atual)
) -> dict:
    """Grava uma foto de produto e devolve o endereço para pôr em `foto_url`.

    **Lê para memória e só depois grava**, e não o contrário: um ficheiro
    recusado nunca chega a existir no disco. Gravar primeiro e apagar a seguir
    deixava-o servível durante o intervalo — numa pasta que é servida por
    HTTP."""
    conteudo = await ficheiro.read(MAXIMO_BYTES + 1)
    if len(conteudo) > MAXIMO_BYTES:
        raise HTTPException(
            status_code=413, detail=_MSG_TAMANHO % (len(conteudo) // 1024))

    tipo = tipo_pela_assinatura(conteudo)
    if tipo is None:
        raise HTTPException(status_code=422, detail=_MSG_TIPO)

    _PASTA.mkdir(parents=True, exist_ok=True)
    nome = nome_de_ficheiro_seguro(tipo)
    (_PASTA / nome).write_bytes(conteudo)
    logger.info("[faturacao] foto de produto gravada: %s (%d bytes)", nome, len(conteudo))
    return {"foto_url": PREFIXO_PUBLICO + nome, "bytes": len(conteudo)}


@router.get("/produtos/fotos/{nome}")
async def servir_foto(nome: str):
    """Serve uma foto carregada aqui. **Pública** — ver a docstring do módulo.

    O nome tem de casar EXACTAMENTE com a forma que gravamos (um UUID e uma das
    três extensões). Tudo o resto é 404, incluindo um nome que exista mesmo no
    disco: a lista do que se serve é a forma do nome, não o conteúdo da
    pasta."""
    if not _NOME_VALIDO.match(nome or ""):
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    caminho = _PASTA / nome
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    return FileResponse(
        str(caminho),
        media_type=_TIPOS[nome.rsplit(".", 1)[-1]],
        # O nome é um UUID e uma foto trocada é um endereço NOVO — por isso
        # esta resposta nunca fica velha, e a grelha do POS deixa de a ir
        # buscar outra vez a cada abertura do ecrã de venda.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
