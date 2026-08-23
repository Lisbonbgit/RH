// **As fotos dos produtos, do lado do ecrã.** Duas coisas, e as duas puras (a
// segunda com um invólucro que toca no browser, marcado como tal).
//
// Vive num ficheiro próprio, e não dentro do `lib/pos.js` ou do
// `lib/faturacao.js`, porque os DOIS precisam dela: o backoffice para desenhar
// a pré-visualização e o POS para desenhar a grelha. Uma cópia em cada um era
// exactamente a forma como este repositório já teve oito cópias da formatação
// de dinheiro — e as oito com o mesmo defeito.

// **O endereço que se põe no `src` de um `<img>`.**
//
// O `foto_url` de um produto tem hoje duas formas, e é de propósito:
//
// - a do VENDUS é ABSOLUTA (`https://www.vendus.pt/foto/b906f77_m.png`) — é o
//   endereço que ele dá, e o servidor já a absolutizou (o Vendus manda-a
//   relativa, `/foto/…`, ver `importacao._extrair_foto`);
// - a NOSSA é RELATIVA (`/api/faturacao/produtos/fotos/<uuid>.webp`) — o
//   portal responde em dois domínios (`lisbonb.com` e `rh.lisbonb.com`, que
//   fica para sempre porque as apps instaladas têm-no cozido) e um endereço
//   absoluto gravado com um deles ficava errado no outro.
//
// A relativa resolve-se contra a base da API que o ecrã está a usar. No site
// essa base é `''` e o endereço fica tal e qual (o nginx encaminha `/api`); num
// embrulho onde a API viva noutro anfitrião, fica absoluta e continua a
// desenhar-se.
//
// **O que não é nenhuma das duas não se desenha.** `javascript:`, `data:` e o
// endereço sem esquema (`//outro-sitio.pt/x.png`, que num ecrã servido por
// https vai buscar a imagem a outro sítio qualquer) devolvem `null`, e o ecrã
// desenha o espaço de reserva. Um `foto_url` chega do servidor, mas o servidor
// foi-o buscar ao Vendus — é uma fonte externa, e isto é um atributo `src`.
export const urlDaFoto = (valor, base) => {
  const url = String(valor ?? '').trim();
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith('//') || !url.startsWith('/')) return null;
  return String(base ?? '') + url;
};

// **Quanto é que uma imagem tem de encolher para caber no lado maior.**
//
// A grelha do POS carrega DEZENAS destas de uma vez, num PC de loja: 40 fotos
// de telemóvel a 4 MB são 160 MB de cada vez que a operadora abre o ecrã de
// venda. O dono fotografa os açaís com o telemóvel — não se lhe pode pedir que
// as reduza primeiro —, por isso é o ecrã que as reduz antes de as enviar.
//
// 640 px no lado maior: o mosaico do POS é 4:3 e ocupa 160–220 px de largura
// num ecrã de balcão, o que dá 440 px num ecrã a 2× — e a mesma foto serve o
// diálogo do produto e a pré-visualização do backoffice. Em WebP a 0,82 fica
// pelos 40–80 KB, e o servidor recusa acima de 512 KB (`fotos.py`).
//
// Uma imagem que já cabe NÃO se estica: aumentar não acrescenta detalhe
// nenhum, só bytes.
export const dimensoesParaCaber = (largura, altura, maximo) => {
  const l = Number(largura);
  const a = Number(altura);
  if (!Number.isFinite(l) || !Number.isFinite(a) || l <= 0 || a <= 0) return null;
  const maior = Math.max(l, a);
  if (maior <= maximo) return { largura: Math.round(l), altura: Math.round(a) };
  const factor = maximo / maior;
  // Nunca zero: uma imagem de 4000×3 encolhida por 0,16 dava altura 0 e o
  // `canvas` desenhava nada — um ficheiro válido, vazio, gravado sem um erro.
  return {
    largura: Math.max(1, Math.round(l * factor)),
    altura: Math.max(1, Math.round(a * factor)),
  };
};

export const MAXIMO_LADO = 640;
export const QUALIDADE = 0.82;
// Os três que o servidor aceita (`fotos.py::tipo_pela_assinatura`, que os
// reconhece pelos primeiros bytes). Escrito aqui só para o `accept` do campo:
// quem RECUSA é o servidor.
export const TIPOS_ACEITES = 'image/jpeg,image/png,image/webp';

// O invólucro que toca no browser: lê o ficheiro, desenha-o num `canvas` na
// medida que a função acima calculou, e devolve um `Blob` em WebP.
//
// **O que aqui não é testável, dito por extenso:** o `jsdom` dos guardas deste
// repositório não tem `canvas` nem `createImageBitmap`, e por isso o que se
// mede é a DECISÃO (`dimensoesParaCaber`), não o desenho. O que protege o
// servidor de uma imagem enorme não é esta função — é o tecto de 512 KB do
// `fotos.py`, que vale mesmo que isto seja contornado.
//
// Se o browser não souber fazer WebP (`toBlob` devolve `null`), tenta JPEG; se
// nem isso, devolve o ficheiro ORIGINAL — que o servidor aceita à mesma se
// couber no tecto, e recusa com uma frase clara se não couber. Nunca se
// devolve nada em silêncio.
export const reduzirImagem = (ficheiro, maximo = MAXIMO_LADO) => new Promise((resolve) => {
  // Sem as peças do browser (um WebView antigo do PC da loja, ou um ambiente
  // sem `canvas`), devolve-se o ficheiro COMO ESTÁ — o servidor aceita-o à
  // mesma se couber no tecto, e recusa-o com uma frase clara se não couber.
  // Nunca se devolve nada em silêncio, e nunca se rebenta o gesto de escolher
  // uma foto por causa de uma capacidade que falta.
  if (typeof document === 'undefined'
      || typeof URL === 'undefined'
      || typeof URL.createObjectURL !== 'function'
      || typeof Image === 'undefined') {
    resolve(ficheiro);
    return;
  }
  const endereco = URL.createObjectURL(ficheiro);
  const img = new Image();
  img.onload = () => {
    URL.revokeObjectURL(endereco);
    const medida = dimensoesParaCaber(img.naturalWidth, img.naturalHeight, maximo);
    if (!medida) { resolve(ficheiro); return; }
    const tela = document.createElement('canvas');
    tela.width = medida.largura;
    tela.height = medida.altura;
    const pincel = tela.getContext('2d');
    if (!pincel) { resolve(ficheiro); return; }
    pincel.drawImage(img, 0, 0, medida.largura, medida.altura);
    tela.toBlob((webp) => {
      if (webp) { resolve(webp); return; }
      tela.toBlob((jpeg) => resolve(jpeg || ficheiro), 'image/jpeg', QUALIDADE);
    }, 'image/webp', QUALIDADE);
  };
  img.onerror = () => { URL.revokeObjectURL(endereco); resolve(ficheiro); };
  img.src = endereco;
});
