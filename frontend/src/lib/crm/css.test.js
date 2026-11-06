/**
 * O CSS DO MAPA (`components/crm/crm.css`) — as regras que só se veem no
 * browser, conferidas aqui pelo texto.
 *
 * Correção "T2.23 (porta do mapa.test.js e seguranca.test.js) / T2.25": escrito
 * antes do `crm.css`, lê-o com `path.join(__dirname, …)` (o `import.meta` do
 * autónomo não funciona no Jest do CRA). As cores dos pinos são as de
 * `lib/crm/fases.js` (estão num só sítio), a etiqueta tem cores fixas (o mapa é
 * claro também no tema escuro do portal) e as amostras de cor dos filtros e do
 * cartão usam as mesmas classes dos pinos.
 *
 * G12 (o mapa passa a Google): saem as regras da biblioteca antiga (as juntas
 * das imagens do mapa, a etiqueta como balão, os botões de zoom: os controlos
 * são agora da Google). O pino de uma loja e o do seletor são o `content` de um
 * marcador avançado (`mapa.js`, `seletor.js`), que a Google ancora pelo fundo
 * ao centro no ponto: o `.pino` desce metade da altura (a bola fica no ponto) e
 * a gota do `.pino-seletor` tem a ponta no fundo ao centro. E a regra de
 * disposição (adenda §2.2): o logótipo e a atribuição da Google, no fundo do
 * mapa, nunca se escondem nem se tapam — nenhum seletor entra no elemento do
 * mapa, nada nosso absoluto sobre os mapas chega ao fundo, e nenhum seletor
 * toca nos elementos da Google. O Playwright da G21 confere o mesmo no browser.
 *
 * "A minha localização" (desenho de 2026-11-06): o ponto azul é o `content` de um marcador avançado, com a mesma
 * ancoragem do pino, a cor do `mapa.js`, cores fixas e sem receber toques. O círculo da precisão não tem CSS: as
 * opções vão no `google.maps.Circle` (mapa.test.js).
 */
import fs from 'fs';
import path from 'path';
import { FASES, ORDEM } from './fases';
import { COR_MINHA_POSICAO } from './mapa';
import { ESTILO_CIRCULO } from './seletor';

const CAMINHO = path.join(__dirname, '../../components/crm/crm.css');
// Sem comentários: uma regra comentada não conta.
const CSS = fs.readFileSync(CAMINHO, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const escapar = (texto) => texto.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// As regras de um CSS, pela ordem: {cabeca, seletores, corpo}. Lê as chavetas, para as regras dentro de um
// @media contarem como as outras (o @media em si, como qualquer @-regra, não é uma regra com seletores).
function lerRegras(css) {
  const regras = [];
  const abertas = [];
  let inicio = 0;
  for (let i = 0; i < css.length; i += 1) {
    if (css[i] === '{') {
      if (abertas.length > 0) abertas[abertas.length - 1].temFilhos = true;
      abertas.push({ cabeca: css.slice(inicio, i).trim(), corpo: i + 1, temFilhos: false });
      inicio = i + 1;
    } else if (css[i] === '}') {
      const aberta = abertas.pop();
      if (aberta && !aberta.temFilhos && !aberta.cabeca.startsWith('@')) {
        regras.push({
          cabeca: aberta.cabeca,
          seletores: aberta.cabeca.split(',').map((s) => s.trim()).filter(Boolean),
          corpo: css.slice(aberta.corpo, i),
        });
      }
      inicio = i + 1;
    }
  }
  return regras;
}

const REGRAS = lerRegras(CSS);

// O corpo da primeira regra com exatamente este seletor, ou null.
const regra = (seletor) => REGRAS.find((r) => r.cabeca === seletor)?.corpo ?? null;

// Todos os seletores do ficheiro (as cabeças das regras, partidas nas vírgulas).
const seletores = () => REGRAS.flatMap((r) => r.seletores);

// O valor de uma declaração no corpo de uma regra (a última, como no browser), ou null.
function valor(corpo, propriedade) {
  const padrao = new RegExp(`(?:^|[;{\\s])${escapar(propriedade)}\\s*:\\s*([^;]+);`, 'g');
  const todas = [...(corpo ?? '').matchAll(padrao)];
  return todas.length > 0 ? todas[todas.length - 1][1].trim() : null;
}

// Prende-se pelo fundo: `bottom` ou qualquer `inset` (o `inset: 0` também é bottom: 0).
const presoAoFundo = (corpo) => /(?:^|[;{\s])(?:bottom|inset(?:-[a-z-]+)?)\s*:/.test(corpo);

// Entra no elemento do mapa da Google: o `.crm-mapa` (a classe exata) seguido de mais alguma coisa que não
// seja uma pseudo-classe do próprio elemento — um filho, um descendente, outra classe no mesmo elemento
// (`.crm-mapa.x`), um atributo, um ::before/::after (um filho gerado).
const entraNoMapa = (seletor) =>
  [...seletor.matchAll(/\.crm-mapa(?![\w-])/g)].some(
    (m) => seletor.slice(m.index + m[0].length).replace(/^(?::(?!:)[\w-]+(?:\([^)]*\))?)*/, '').trim() !== '',
  );

// Toca nos elementos da Google: as classes `gm-…`, os elementos `gmp-…`, ou atributos com "google" (o logótipo
// e as ligações dos termos).
const tocaNaGoogle = (seletor) => /gmp?-|google/i.test(seletor);

// --- As ferramentas do teste ---------------------------------------------------------------------------------

test('lerRegras lê as regras soltas e as de dentro de um @media, sem o @media nem as @-regras sem filhos', () => {
  const amostra = '.a { color: red; }\n@media (min-width: 1024px) {\n  .b, .c > * { top: 0; }\n}\n@font-face { font-family: x; }\n';
  expect(lerRegras(amostra)).toEqual([
    { cabeca: '.a', seletores: ['.a'], corpo: ' color: red; ' },
    { cabeca: '.b, .c > *', seletores: ['.b', '.c > *'], corpo: ' top: 0; ' },
  ]);
});

test('valor dá a última declaração com o nome exato (não confunde top com margin-top nem --x-top)', () => {
  const corpo = ' margin-top: 4px; --x-top: 1px; top: 2px; top: 3px; ';
  expect(valor(corpo, 'top')).toBe('3px');
  expect(valor(corpo, 'margin-top')).toBe('4px');
  expect(valor(corpo, 'bottom')).toBeNull();
  expect(valor(null, 'top')).toBeNull();
});

test('presoAoFundo vê o bottom e os inset, e não os margin-bottom/padding-bottom', () => {
  for (const corpo of [' bottom: 0; ', ' inset: 0; ', ' top: 0; inset-block-end: 2px; ', '\nbottom:0;']) {
    expect(presoAoFundo(corpo)).toBe(true);
  }
  for (const corpo of [' top: 0; margin-bottom: 4px; ', ' padding-bottom: 2px; border-bottom: 1px solid; ']) {
    expect(presoAoFundo(corpo)).toBe(false);
  }
});

test.each([
  ['.crm-mapa .pino', true],
  ['.crm-mapa > div', true],
  ['.crm-mapa>div', true],
  ['.crm-mapa.outra-classe', true],
  ['.crm-mapa::after', true],
  ['.crm-mapa[aria-busy="true"]', true],
  ['.crm-mapa:hover .x', true],
  ['.crm-seletor__vista .crm-mapa img', true],
  ['.crm-mapa', false],
  ['.crm-mapa:focus-visible', false],
  ['.crm-seletor__vista > .crm-mapa', false],
  ['.crm-mapa__barra > *', false],
  ['.crm-mapa__vista', false],
  ['.crm-mapa--planeador .pino', false],
])('entraNoMapa(%s) → %s', (seletor, esperado) => {
  expect(entraNoMapa(seletor)).toBe(esperado);
});

test.each([
  ['.gm-style', true],
  ['.crm-mapa__vista .gm-style-cc', true],
  ['gmp-advanced-marker', true],
  ['[class^="gm-"]', true],
  ['a[title*="Google"]', true],
  ['.pino', false],
  ['.crm-negocio__acoes', false],
])('tocaNaGoogle(%s) → %s', (seletor, esperado) => {
  expect(tocaNaGoogle(seletor)).toBe(esperado);
});

// --- Os pinos das lojas --------------------------------------------------------------------------------------

test('cada fase tem a cor exata no pino (e o contorno só onde a fase o tem: a potencial)', () => {
  for (const fase of ORDEM) {
    const bloco = regra(`.pino--${fase}`);
    expect(bloco).not.toBeNull();
    expect(valor(bloco, '--cor-pino')).toBe(FASES[fase].cor);
    expect(valor(bloco, '--contorno-pino')).toBe(FASES[fase].contorno);
  }
});

test('só há classes de pino para as fases que existem', () => {
  const fases = new Set(seletores().flatMap((s) => [...s.matchAll(/\.pino--([a-z0-9_-]+)/g)].map((m) => m[1])));
  expect([...fases].sort()).toEqual([...ORDEM].sort());
});

test('o pino de uma loja é um bloco de 44 × 44 px que desce metade da altura: a bola fica no ponto da loja', () => {
  const pino = regra('.pino');
  expect(pino).not.toBeNull();
  expect(valor(pino, 'position')).toBe('relative');
  expect(valor(pino, 'width')).toBe('44px');
  expect(valor(pino, 'height')).toBe('44px');
  // O marcador avançado põe o fundo ao centro do conteúdo no ponto; a descer metade da altura, é o centro do
  // bloco (a bola) que fica lá.
  expect(valor(pino, 'transform')).toBe('translateY(50%)');
  // As cores por omissão (uma fase desconhecida): cinzento com contorno branco.
  expect(valor(pino, '--cor-pino')).toBe('#cfcfcf');
  expect(valor(pino, '--contorno-pino')).toBe('#fff');
});

test('a bola é um círculo de 20 px ao centro do bloco, desenhado com as variáveis das classes das fases', () => {
  const bola = regra('.pino__bola');
  expect(bola).not.toBeNull();
  expect(valor(bola, 'position')).toBe('absolute');
  expect(valor(bola, 'width')).toBe('20px');
  expect(valor(bola, 'height')).toBe('20px');
  expect(valor(bola, 'top')).toBe('50%');
  expect(valor(bola, 'left')).toBe('50%');
  expect(valor(bola, 'margin')).toBe('-10px 0 0 -10px');
  expect(valor(bola, 'border-radius')).toBe('50%');
  expect(valor(bola, 'background')).toBe('var(--cor-pino)');
  expect(valor(bola, 'border')).toBe('3px solid var(--contorno-pino)');
  // A bola é só o span: um ::before/::after no pino desenhava outra.
  expect(seletores().filter((s) => /\.pino(?:--[\w-]+)?::?(?:before|after)/.test(s))).toEqual([]);
});

test('a etiqueta da loja fica à direita da bola, ao meio da altura, e não recebe toques', () => {
  const etiqueta = regra('.etiqueta-loja');
  expect(etiqueta).not.toBeNull();
  expect(valor(etiqueta, 'position')).toBe('absolute');
  expect(valor(etiqueta, 'left')).toBe('32px');
  expect(valor(etiqueta, 'top')).toBe('50%');
  expect(valor(etiqueta, 'transform')).toBe('translateY(-50%)');
  expect(valor(etiqueta, 'pointer-events')).toBe('none');
});

test('a etiqueta mostra o nome inteiro (sem reticências): os nomes compridos passam a outra linha', () => {
  const etiqueta = regra('.etiqueta-loja');
  expect(etiqueta).not.toBeNull();
  expect(etiqueta).not.toMatch(/text-overflow/);
  expect(etiqueta).not.toMatch(/overflow:\s*hidden/);
  expect(valor(etiqueta, 'white-space')).toBe('normal');
  // O bloco do pino só tem 44 px: sem o max-content, o nome partia-se em cada palavra.
  expect(valor(etiqueta, 'width')).toBe('max-content');
  expect(valor(etiqueta, 'max-width')).toBe('16rem');
});

test('a etiqueta tem cores fixas (o mapa é claro também no tema escuro)', () => {
  const etiqueta = regra('.etiqueta-loja');
  const fundo = valor(etiqueta, 'background');
  const cor = valor(etiqueta, 'color');
  expect(fundo).not.toBeNull();
  expect(cor).not.toBeNull();
  for (const valorDaCor of [fundo, cor]) {
    expect(valorDaCor).not.toMatch(/var\(|currentcolor|inherit/i);
  }
});

test('uma só regra pinta a etiqueta (duas pintavam duas caixas)', () => {
  expect(seletores().filter((s) => /\.etiqueta-loja/.test(s))).toEqual(['.etiqueta-loja']);
});

test('as amostras de cor (filtros e cartão) usam as classes dos pinos, com o mesmo cinzento por omissão', () => {
  const amostra = regra('.crm-amostra-fase');
  expect(amostra).not.toBeNull();
  expect(amostra).toMatch(/background:\s*var\(--cor-pino,\s*#cfcfcf\);/);
  expect(amostra).toMatch(/border:\s*2px solid var\(--contorno-pino,/);
});

// --- A posição da pessoa ("A minha localização") --------------------------------------------------------------

test('o ponto azul é um círculo de 18 px que desce metade da altura: o centro fica na posição da pessoa', () => {
  const ponto = regra('.ponto-minha-posicao');
  expect(ponto).not.toBeNull();
  expect(valor(ponto, 'box-sizing')).toBe('border-box');
  expect(valor(ponto, 'width')).toBe('18px');
  expect(valor(ponto, 'height')).toBe('18px');
  expect(valor(ponto, 'border-radius')).toBe('50%');
  // O marcador avançado põe o fundo ao centro do conteúdo no ponto, como no .pino.
  expect(valor(ponto, 'transform')).toBe('translateY(50%)');
});

test('o ponto azul não rouba toques aos pinos que estejam por baixo', () => {
  expect(valor(regra('.ponto-minha-posicao'), 'pointer-events')).toBe('none');
  // Uma só regra e sem filhos: nada lá dentro volta a receber toques.
  expect(seletores().filter((s) => /ponto-minha-posicao/.test(s))).toEqual(['.ponto-minha-posicao']);
});

test('o ponto azul tem a cor do mapa.js e cores fixas (o mapa é claro também no tema escuro)', () => {
  const ponto = regra('.ponto-minha-posicao');
  expect(valor(ponto, 'background')).toBe(COR_MINHA_POSICAO);
  expect(valor(ponto, 'border')).toBe('3px solid #fff');
  for (const propriedade of ['background', 'border', 'box-shadow']) {
    expect(valor(ponto, propriedade)).not.toMatch(/var\(|currentcolor|inherit/i);
  }
  // Vê-se por cima do contorno branco e do mapa claro.
  expect(contraste(valor(ponto, 'background'), '#ffffff')).toBeGreaterThanOrEqual(3);
});

test('num telemóvel estreito a barra de cima não transborda: os botões passam a outra linha', () => {
  const barra = regra('.crm-mapa__barra');
  expect(valor(barra, 'display')).toBe('flex');
  expect(valor(barra, 'flex-wrap')).toBe('wrap');
  // Presa aos dois lados: a largura é a do mapa, nunca a dos botões.
  expect(valor(barra, 'left')).toBe('max(10px, env(safe-area-inset-left))');
  expect(valor(barra, 'right')).toBe('max(10px, env(safe-area-inset-right))');
});

test('no planeador a barra fica à esquerda: à direita tapava o "+" da Google quando o mapa encolhe com o cartão', () => {
  const planeador = regra('.crm-mapa__barra--planeador');
  expect(valor(planeador, 'justify-content')).toBe('flex-start');
  // Só muda o lado: o resto (presa pelo top, deixa passar os toques) é o da barra, que vem antes para ceder aqui.
  expect(planeador.trim().split(';').filter(Boolean)).toHaveLength(1);
  expect(valor(regra('.crm-mapa__barra'), 'justify-content')).toBe('flex-end');
  const cabecas = REGRAS.map((r) => r.cabeca);
  expect(cabecas.indexOf('.crm-mapa__barra')).toBeLessThan(cabecas.indexOf('.crm-mapa__barra--planeador'));
});

// --- As áreas dos mapas --------------------------------------------------------------------------------------

test('o mapa tem altura explícita: ocupa a área toda e pode encolher com o cartão da loja aberto', () => {
  // O mapa da Google precisa de uma área com tamanho: o elemento enche a vista (absoluto, de canto a canto).
  const mapa = regra('.crm-mapa');
  expect(mapa).not.toBeNull();
  expect(valor(mapa, 'position')).toBe('absolute');
  expect(valor(mapa, 'inset')).toBe('0');
  expect(valor(mapa, 'isolation')).toBe('isolate'); // os controlos e os balões da Google ficam por baixo do menu
  // A vista ocupa o que sobra; com o cartão aberto encolhe até 8rem, para o contacto e o Ver ficha caberem
  // no ecrã (telemóvel deitado incluído).
  const vista = regra('.crm-mapa__vista');
  expect(vista).not.toBeNull();
  expect(valor(vista, 'position')).toBe('relative');
  expect(valor(vista, 'flex')).toMatch(/^1 1 0(?:%|px)?$/);
  const altura = (valor(vista, 'min-height') ?? '').match(/^([\d.]+)rem$/);
  expect(altura).not.toBeNull();
  expect(Number(altura[1])).toBeLessThanOrEqual(8);
});

test('o mapa do seletor tem altura própria (o .crm-mapa é absoluto dentro dela)', () => {
  const vista = regra('.crm-seletor__vista');
  expect(vista).not.toBeNull();
  expect(valor(vista, 'position')).toBe('relative');
  expect(valor(vista, 'height')).toMatch(/^clamp\(16rem,\s*50vh,\s*28rem\)$/);
  expect(valor(vista, 'overflow')).toBe('hidden');
});

// --- O seletor da localização (T2.26; G12 sobre o marcador avançado) ----------------------------------------
// O pino do seletor é a `div.pino-seletor` vazia (seletor.js, feita com o el()): a gota desenha-se toda aqui.

test('o pino do seletor é um bloco de 44 × 38 px com a gota roxa (a cor do círculo da precisão)', () => {
  const area = regra('.pino-seletor');
  expect(area).not.toBeNull();
  expect(valor(area, 'position')).toBe('relative'); // a gota e o ponto são absolutos dentro dele
  expect(valor(area, 'width')).toBe('44px');
  expect(valor(area, 'height')).toBe('38px');
  expect(valor(area, 'transform')).toBeNull(); // a ponta já é o fundo ao centro: o bloco não se desloca
  const gota = regra('.pino-seletor::before');
  expect(gota).not.toBeNull();
  expect(valor(gota, 'background')).toBe(ESTILO_CIRCULO.strokeColor);
  expect(valor(gota, 'border')).toBe('3px solid #fff');
  expect(valor(gota, 'border-radius')).toBe('50% 50% 50% 0');
  expect(valor(gota, 'transform')).toBe('rotate(-45deg)');
  expect(valor(gota, 'width')).toBe('28px');
  expect(valor(gota, 'height')).toBe('28px');
  const ponto = regra('.pino-seletor::after');
  expect(ponto).not.toBeNull();
  expect(valor(ponto, 'background')).toBe('#fff');
  expect(valor(ponto, 'border-radius')).toBe('50%');
  // As duas partes da gota são do CSS (o conteúdo do marcador não leva HTML).
  for (const bloco of [gota, ponto]) {
    expect(valor(bloco, 'content')).toBe('""');
    expect(valor(bloco, 'position')).toBe('absolute');
  }
});

test('a ponta da gota fica no fundo ao centro do bloco (o ponto da loja), e o ponto branco no meio da gota', () => {
  const px = (bloco, propriedade) => {
    const texto = valor(bloco, propriedade) ?? '';
    expect([propriedade, texto]).toEqual([propriedade, expect.stringMatching(/^-?\d+(?:\.\d+)?px$/)]);
    return parseFloat(texto);
  };
  const area = regra('.pino-seletor');
  const gota = regra('.pino-seletor::before');
  const ponto = regra('.pino-seletor::after');
  const lado = px(gota, 'width');
  expect(px(gota, 'height')).toBe(lado);
  const centro = { x: px(gota, 'left') + lado / 2, y: px(gota, 'top') + lado / 2 };
  expect(centro.x).toBe(px(area, 'width') / 2);
  // O quadrado rodado -45° com o canto de baixo à esquerda em bico (50% 50% 50% 0): o bico fica por baixo do
  // centro, a meia diagonal (lado / 2 × √2), e tem de ser o fundo do bloco (meio píxel de folga).
  expect(Math.abs(centro.y + (lado / 2) * Math.SQRT2 - px(area, 'height'))).toBeLessThanOrEqual(0.5);
  const diametro = px(ponto, 'width');
  expect(px(ponto, 'height')).toBe(diametro);
  expect(px(ponto, 'left') + diametro / 2).toBe(centro.x);
  expect(px(ponto, 'top') + diametro / 2).toBe(centro.y);
});

test('confirmada a localização, a gota fica roxo-escuro', () => {
  const confirmado = regra('.crm-seletor[data-estado="confirmado"] .pino-seletor::before');
  expect(confirmado).not.toBeNull();
  expect(valor(confirmado, 'background')).toBe('#4f1f7d');
});

// --- O painel do negócio selecionado (NegocioSelecionado) ---------------------------------------------------

test('o painel do negócio vive fora do mapa (nada dele é absoluto, fixo nem pegajoso) e os botões passam a outra linha', () => {
  expect(regra('.crm-negocio')).not.toBeNull();
  const soltas = REGRAS.filter(
    (r) => r.seletores.some((s) => s.includes('crm-negocio'))
      && /absolute|fixed|sticky/.test(valor(r.corpo, 'position') ?? ''),
  );
  expect(soltas.map((r) => r.cabeca)).toEqual([]);
  const acoes = regra('.crm-negocio__acoes');
  expect(acoes).not.toBeNull();
  expect(valor(acoes, 'display')).toBe('flex');
  expect(valor(acoes, 'flex-wrap')).toBe('wrap');
});

// --- A regra de disposição (adenda §2.2) e as guardas da atribuição -----------------------------------------

test('regra de disposição (a): o elemento do mapa da Google não tem filhos nossos — nenhum seletor entra nele', () => {
  expect(seletores().filter(entraNoMapa)).toEqual([]);
});

test('regra de disposição (b): sobre os mapas, só o próprio .crm-mapa vai até ao fundo; o resto prende-se pelo top', () => {
  const sobreOsMapas = REGRAS.filter(
    (r) => /^(?:absolute|fixed)$/.test(valor(r.corpo, 'position') ?? '')
      && r.seletores.some((s) => /crm-mapa|crm-seletor__vista/.test(s)),
  );
  const outras = sobreOsMapas.filter((r) => r.cabeca !== '.crm-mapa');
  expect(outras.map((r) => r.cabeca)).toContain('.crm-mapa__barra'); // hoje só ela
  const fora = outras.filter((r) => valor(r.corpo, 'top') === null || presoAoFundo(r.corpo));
  expect(fora.map((r) => r.cabeca)).toEqual([]);
});

test('regra de disposição (c): a barra de cima deixa passar os toques para o mapa; só os filhos os recebem', () => {
  expect(valor(regra('.crm-mapa__barra'), 'pointer-events')).toBe('none');
  expect(valor(regra('.crm-mapa__barra > *'), 'pointer-events')).toBe('auto');
});

test('guardas da atribuição: nenhum seletor toca nos elementos da Google (gm-, gmp-, "google")', () => {
  expect(seletores().filter(tocaNaGoogle)).toEqual([]);
});

// Revisão do mapa Google (MAPA-G-5): o cartão da loja e o painel do negócio vivem por baixo do mapa, encostados
// ao fundo dele, onde estão o logótipo e a atribuição da Google. Uma sombra lançada para cima (deslocamento
// vertical negativo) pinta-se por cima dessa faixa, e o `elementFromPoint` da G21 não a apanha.
const PAINEIS_POR_BAIXO = ['components/crm/CartaoLoja.js', 'components/crm/NegocioSelecionado.js'];

// Se alguma das sombras de um box-shadow (também a de uma classe do Tailwind, com `_` no lugar dos espaços), sem
// `inset`, tem o deslocamento vertical (o segundo comprimento) negativo. As vírgulas de rgb()/hsl() não contam.
function sombraParaCima(valorSombra) {
  const sombras = valorSombra.replace(/\([^)]*\)/g, '()').split(',');
  return sombras.some((sombra) => {
    const partes = sombra.trim().split(/[\s_]+/);
    if (partes.includes('inset')) return false;
    const comprimentos = partes.filter((parte) => /^-?(?:\d*\.)?\d+(?:px|rem|em)?$/.test(parte));
    return comprimentos.length >= 2 && parseFloat(comprimentos[1]) < 0;
  });
}

test('sombraParaCima vê o deslocamento vertical negativo (também no Tailwind), e não o inset nem o positivo', () => {
  expect(sombraParaCima('0 -6px 18px rgb(0 0 0 / 0.12)')).toBe(true);
  expect(sombraParaCima('0_-6px_18px_rgb(0_0_0/0.12)')).toBe(true);
  expect(sombraParaCima('0 2px 6px rgb(0 0 0 / 40%), 0 -1px 0 hsl(0, 0%, 0%)')).toBe(true);
  expect(sombraParaCima('0 1px 3px rgb(0 0 0 / 45%)')).toBe(false);
  expect(sombraParaCima('0_1px_3px_rgb(0_0_0/0.45)')).toBe(false);
  expect(sombraParaCima('inset 0 -6px 18px rgb(0 0 0 / 0.12)')).toBe(false);
  expect(sombraParaCima('none')).toBe(false);
});

test('regra de disposição (d): o cartão da loja e o painel do negócio, por baixo do mapa, não lançam sombra para cima', () => {
  for (const relativo of PAINEIS_POR_BAIXO) {
    const fonte = fs.readFileSync(path.join(__dirname, '../..', relativo), 'utf8');
    const sombras = [...fonte.matchAll(/shadow-\[([^\]]+)\]/g)].map((achado) => achado[1]);
    expect([relativo, sombras.filter(sombraParaCima)]).toEqual([relativo, []]);
  }
  const doPainel = REGRAS.filter((r) => r.seletores.some((s) => s.includes('crm-negocio')));
  expect(doPainel.map((r) => r.cabeca)).toContain('.crm-negocio');
  const comSombra = doPainel.filter((r) => sombraParaCima(valor(r.corpo, 'box-shadow') ?? 'none'));
  expect(comSombra.map((r) => r.cabeca)).toEqual([]);
});

// --- O planeador da rota (F3 / T3.36) ------------------------------------------------------------------------
// Os pinos da rota são o `content` dos marcadores avançados do `mapa.mostrarRota` (T3.33): `div.pino-paragem`
// + `pino--<fase>` (+ `--aviso`, `--sem-numero`) com `span.pino-paragem__numero` e `span.etiqueta-loja`, e o
// `div.pino-extremo` > `span.pino-extremo__marca` + `span.etiqueta-loja`. A linha da rota não tem CSS: as opções
// vão no `google.maps.Polyline` (mapa.test.js). O planeador (`.crm-planeador`) põe o painel e o mapa lado a lado
// a partir de 1024 px; abaixo, o mapa com altura fixa e o painel por baixo, tudo a deslocar-se (correções
// "T3.35 / T3.36" e "T3.36 (css.test.js e crm.css)" do mapa Google). O painel, a lista, a pega e o rodapé do
// ORS vivem fora do `.crm-mapa` e encolhem-no, nunca por cima (as asserções (a)–(d) de cima continuam).

// Os blocos de topo que são @-regras com chavetas, pela ordem: {cabeca, dentro}. As regras soltas ficam no `fora`
// (sem as @-regras sem chavetas, como o @import, que o lerRegras juntava à cabeça da regra seguinte).
function blocosDeTopo(css) {
  const blocos = [];
  let fora = '';
  let profundidade = 0;
  let inicio = 0;
  let cabecaDoBloco = null;
  let abre = -1;
  for (let i = 0; i < css.length; i += 1) {
    if (css[i] === '{') {
      if (profundidade === 0) {
        const cabeca = css.slice(inicio, i).trim();
        if (cabeca.startsWith('@')) {
          cabecaDoBloco = cabeca;
          abre = i;
        } else {
          cabecaDoBloco = null;
        }
      }
      profundidade += 1;
    } else if (css[i] === '}') {
      profundidade -= 1;
      if (profundidade === 0) {
        if (cabecaDoBloco === null) fora += css.slice(inicio, i + 1);
        else blocos.push({ cabeca: cabecaDoBloco, dentro: css.slice(abre + 1, i) });
        inicio = i + 1;
      }
    } else if (css[i] === ';' && profundidade === 0) {
      inicio = i + 1;
    }
  }
  return { blocos, fora };
}

const normalizar = (texto) => texto.replace(/\s+/g, ' ').trim();

// As regras dentro dos @media com esta condição exata (ex.: '(min-width: 1024px)'), e as de fora de qualquer
// @-regra com chavetas.
const regrasDoMedia = (css, condicao) => blocosDeTopo(css).blocos
  .filter((b) => normalizar(b.cabeca) === `@media ${condicao}`)
  .flatMap((b) => lerRegras(b.dentro));
const regrasSoltas = (css) => lerRegras(blocosDeTopo(css).fora);

const corpoEm = (lista, seletor) => lista.find((r) => r.cabeca === seletor)?.corpo ?? null;
const DESKTOP = '(min-width: 1024px)';
const SOLTAS = regrasSoltas(CSS);
const NO_DESKTOP = regrasDoMedia(CSS, DESKTOP);

// O contraste WCAG entre duas cores #rgb/#rrggbb (de 1 a 21).
function luminancia(hex) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex ?? '');
  if (m === null) return null;
  const digitos = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => {
    const canal = parseInt(digitos.slice(i, i + 2), 16) / 255;
    return canal <= 0.03928 ? canal / 12.92 : ((canal + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contraste(a, b) {
  const [la, lb] = [luminancia(a), luminancia(b)];
  if (la === null || lb === null) return null;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const px = (texto) => {
  const m = /^(-?\d+(?:\.\d+)?)px$/.exec(texto ?? '');
  return m === null ? null : Number(m[1]);
};

test('blocosDeTopo separa os @media (com as regras lá dentro) das regras soltas e das @-regras sem chavetas', () => {
  const amostra = [
    '@import url(x.css);',
    '.a { color: red; }',
    '@media (min-width: 1024px) {\n  .b { top: 0; }\n  .c { left: 0; }\n}',
    '@media (max-width: 600px) { .d { top: 1px; } }',
    '.e { color: blue; }',
  ].join('\n');
  const { blocos, fora } = blocosDeTopo(amostra);
  expect(blocos.map((b) => normalizar(b.cabeca))).toEqual(['@media (min-width: 1024px)', '@media (max-width: 600px)']);
  expect(regrasDoMedia(amostra, DESKTOP).map((r) => r.cabeca)).toEqual(['.b', '.c']);
  expect(regrasDoMedia(amostra, '(max-width: 600px)').map((r) => r.cabeca)).toEqual(['.d']);
  expect(regrasDoMedia(amostra, '(min-width: 1023px)')).toEqual([]);
  expect(regrasSoltas(amostra).map((r) => r.cabeca)).toEqual(['.a', '.e']);
  expect(fora).not.toContain('@import');
  expect(fora).not.toContain('.b');
});

test('contraste dá a razão do WCAG (21 entre o preto e o branco; o #767676 mal passa os 4,5 sobre o branco)', () => {
  expect(contraste('#000', '#fff')).toBeCloseTo(21, 5);
  expect(contraste('#ffffff', '#FFFFFF')).toBeCloseTo(1, 5);
  expect(contraste('#767676', '#fff')).toBeGreaterThanOrEqual(4.5);
  expect(contraste('#777777', '#fff')).toBeLessThan(4.5);
  expect(contraste('var(--x)', '#fff')).toBeNull();
  expect(contraste('#fff', null)).toBeNull();
});

test('o pino de uma paragem e o do início/fim são o mesmo bloco de 44 × 44 px do pino da loja (a etiqueta e a ancoragem batem)', () => {
  for (const seletor of ['.pino-paragem', '.pino-extremo']) {
    const bloco = regra(seletor);
    expect([seletor, bloco === null]).toEqual([seletor, false]);
    expect([seletor, valor(bloco, 'position')]).toEqual([seletor, 'relative']);
    expect([seletor, valor(bloco, 'width')]).toEqual([seletor, '44px']);
    expect([seletor, valor(bloco, 'height')]).toEqual([seletor, '44px']);
    // O marcador põe o fundo ao centro do conteúdo no ponto: o centro do bloco fica no ponto da loja.
    expect([seletor, valor(bloco, 'transform')]).toEqual([seletor, 'translateY(50%)']);
  }
});

test('a cor da fase chega ao pino da paragem pelas classes .pino--<fase>: só elas (e o .pino, antes delas) mudam as cores', () => {
  for (const variavel of ['--cor-pino', '--contorno-pino']) {
    const comVariavel = REGRAS.filter((r) => valor(r.corpo, variavel) !== null).map((r) => r.cabeca);
    // Uma regra de uma só classe depois das das fases (ex.: `.pino-paragem { --cor-pino: … }`) ganhava-lhes.
    expect([variavel, comVariavel[0]]).toEqual([variavel, '.pino']);
    expect([variavel, comVariavel.slice(1).every((cabeca) => ORDEM.some((fase) => cabeca === `.pino--${fase}`))]).toEqual([
      variavel,
      true,
    ]);
  }
});

test('o número da paragem é um disco de 24 px ao centro do bloco, com o anel na cor da fase', () => {
  const numero = regra('.pino-paragem__numero');
  expect(numero).not.toBeNull();
  expect(valor(numero, 'position')).toBe('absolute');
  expect(valor(numero, 'top')).toBe('50%');
  expect(valor(numero, 'left')).toBe('50%');
  expect(valor(numero, 'box-sizing')).toBe('border-box');
  expect(valor(numero, 'width')).toBe('24px');
  expect(valor(numero, 'height')).toBe('24px');
  expect(valor(numero, 'margin')).toBe('-12px 0 0 -12px');
  expect(valor(numero, 'border-radius')).toBe('50%');
  expect(valor(numero, 'border')).toBe('4px solid var(--cor-pino, #cfcfcf)');
  // O número ao meio do disco.
  expect(valor(numero, 'display')).toBe('flex');
  expect(valor(numero, 'align-items')).toBe('center');
  expect(valor(numero, 'justify-content')).toBe('center');
});

test('o número tem cor fixa e legível em todas as fases: texto escuro sobre o disco branco (contraste ≥ 4,5)', () => {
  const numero = regra('.pino-paragem__numero');
  const fundo = valor(numero, 'background');
  const cor = valor(numero, 'color');
  // Cores fixas: o mapa é claro também no tema escuro do portal, e a cor da fase só pinta o anel.
  for (const valorDaCor of [fundo, cor]) expect(valorDaCor).toMatch(/^#[0-9a-f]{3}(?:[0-9a-f]{3})?$/i);
  expect(contraste(cor, fundo)).toBeGreaterThanOrEqual(4.5);
  expect(Number(valor(numero, 'font-weight'))).toBeGreaterThanOrEqual(700);
  // Dois algarismos (até 48 paragens) cabem no disco.
  const letra = px(valor(numero, 'font-size'));
  expect(letra).not.toBeNull();
  expect(letra).toBeLessThanOrEqual(12);
  expect(valor(numero, 'white-space')).toBe('nowrap');
});

test('o disco do número quase não passa por baixo da etiqueta (que começa aos 32 px do bloco)', () => {
  const largura = px(valor(regra('.pino-paragem__numero'), 'width'));
  const etiqueta = px(valor(regra('.etiqueta-loja'), 'left'));
  expect([largura, etiqueta].includes(null)).toBe(false);
  const metade = largura / 2;
  // O centro do disco está aos 22 px (o meio do bloco de 44): acaba no máximo 2 px depois do início da etiqueta.
  expect(22 + metade - etiqueta).toBeLessThanOrEqual(2);
});

test('uma paragem com aviso tem um halo vermelho fixo à volta do número (sem aviso, nenhum)', () => {
  const aviso = regra('.pino-paragem--aviso');
  expect(aviso).not.toBeNull();
  const vermelho = valor(aviso, '--aviso-pino');
  expect(vermelho).toMatch(/^#[0-9a-f]{6}$/i);
  // Um contorno que se vê sobre o branco (contraste ≥ 3 nos elementos gráficos).
  expect(contraste(vermelho, '#fff')).toBeGreaterThanOrEqual(3);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(vermelho.slice(i, i + 2), 16));
  expect(r).toBeGreaterThan(g + b);
  // O halo é uma sombra do disco com a variável: sem a classe do aviso, a variável não existe e fica a cor de
  // reserva (transparente).
  expect(valor(regra('.pino-paragem__numero'), 'box-shadow')).toMatch(/^0 0 0 3px var\(--aviso-pino, transparent\),/);
  const comAviso = REGRAS.filter((r) => valor(r.corpo, '--aviso-pino') !== null).map((r) => r.cabeca);
  expect(comAviso).toEqual(['.pino-paragem--aviso']);
});

test('uma paragem sem número (fechada, não cabe) é um ponto na cor da fase, com o anel do aviso', () => {
  const semNumero = regra('.pino-paragem--sem-numero');
  expect(semNumero).not.toBeNull();
  const fundo = valor(semNumero, 'background');
  expect(fundo).toMatch(/^radial-gradient\(circle, /);
  expect(fundo).toContain('var(--cor-pino, #cfcfcf) 0 6px');
  expect(fundo).toContain('var(--aviso-pino, ');
  expect(fundo).toMatch(/transparent \d+px\)$/);
  // O ponto (com os anéis) não passa da etiqueta: o último anel acaba no máximo aos 12 px do centro.
  const raios = [...fundo.matchAll(/(\d+)px/g)].map((m) => Number(m[1]));
  expect(Math.max(...raios)).toBeLessThanOrEqual(12);
});

test('a marca do início e do fim é um quadrado escuro ao centro do bloco, com cores fixas (não é um pino de loja)', () => {
  const marca = regra('.pino-extremo__marca');
  expect(marca).not.toBeNull();
  expect(valor(marca, 'position')).toBe('absolute');
  expect(valor(marca, 'top')).toBe('50%');
  expect(valor(marca, 'left')).toBe('50%');
  const lado = px(valor(marca, 'width'));
  expect(lado).not.toBeNull();
  expect(px(valor(marca, 'height'))).toBe(lado);
  expect(valor(marca, 'margin')).toBe(`-${lado / 2}px 0 0 -${lado / 2}px`);
  expect(22 + lado / 2 - px(valor(regra('.etiqueta-loja'), 'left'))).toBeLessThanOrEqual(2);
  expect(valor(marca, 'border-radius')).not.toBe('50%');
  for (const propriedade of ['background', 'border']) {
    expect([propriedade, valor(marca, propriedade)]).not.toEqual([propriedade, null]);
    expect(valor(marca, propriedade)).not.toMatch(/var\(|currentcolor|inherit/i);
  }
  expect(contraste(valor(marca, 'background'), '#ffffff')).toBeGreaterThanOrEqual(4.5);
});

test('no mapa do planeador, os pinos das lojas fora da rota ficam esbatidos (os da rota não)', () => {
  const esbatido = regra('.crm-mapa--planeador .pino');
  expect(esbatido).not.toBeNull();
  const opacidade = Number(valor(esbatido, 'opacity'));
  expect(opacidade).toBeGreaterThanOrEqual(0.3);
  expect(opacidade).toBeLessThanOrEqual(0.7);
  // Só o pino das lojas (a classe .pino): nada esbate as paragens, o início nem o fim.
  const doPlaneador = seletores().filter((s) => s.includes('crm-mapa--planeador'));
  expect(doPlaneador).toEqual(['.crm-mapa--planeador .pino']);
  for (const r of REGRAS.filter((x) => x.seletores.some((s) => /pino-(?:paragem|extremo)/.test(s)))) {
    expect([r.cabeca, valor(r.corpo, 'opacity')]).toEqual([r.cabeca, null]);
  }
});

test('a pega de arrastar tem 44 × 44 px e não deixa o dedo deslocar a página (touch-action: none)', () => {
  const pega = regra('.crm-pega');
  expect(pega).not.toBeNull();
  expect(valor(pega, 'width')).toBe('44px');
  expect(valor(pega, 'height')).toBe('44px');
  expect(valor(pega, 'flex')).toBe('none');
  expect(valor(pega, 'touch-action')).toBe('none');
  expect(valor(pega, 'cursor')).toBe('grab');
  expect(valor(pega, 'user-select')).toBe('none');
  expect(valor(regra('.crm-paragem--arrastada .crm-pega'), 'cursor')).toBe('grabbing');
});

test('a linha arrastada segue o dedo por cima das outras (sem transição); as outras abrem lugar com transição', () => {
  const linha = regra('.crm-paragem');
  expect(linha).not.toBeNull();
  expect(valor(linha, 'position')).toBe('relative');
  expect(valor(linha, 'transition')).toMatch(/^transform \d+ms/);
  const arrastada = regra('.crm-paragem--arrastada');
  expect(arrastada).not.toBeNull();
  expect(Number(valor(arrastada, 'z-index'))).toBeGreaterThanOrEqual(1);
  expect(valor(arrastada, 'transition')).toBe('none');
  // Quem pede menos movimento não vê as linhas a deslizar.
  const reduzido = regrasDoMedia(CSS, '(prefers-reduced-motion: reduce)');
  expect(valor(corpoEm(reduzido, '.crm-paragem'), 'transition')).toBe('none');
});

test('o planeador enche a área do ecrã cheio; abaixo de 1024 px, o mapa tem altura fixa e o painel vem por baixo, tudo a deslocar-se', () => {
  const planeador = corpoEm(SOLTAS, '.crm-planeador');
  expect(planeador).not.toBeNull();
  expect(valor(planeador, 'height')).toBe('100%');
  expect(valor(planeador, 'display')).toBe('grid');
  expect(valor(planeador, 'overflow-y')).toBe('auto');
  expect(valor(planeador, 'grid-template-areas')).toBe('"mapa" "painel"');
  const mapa = corpoEm(SOLTAS, '.crm-planeador__mapa');
  expect(mapa).not.toBeNull();
  // O .crm-mapa é absoluto (inset 0) dentro desta área: ela precisa de altura própria.
  expect(valor(mapa, 'position')).toBe('relative');
  expect(valor(mapa, 'grid-area')).toBe('mapa');
  expect(valor(mapa, 'height')).toMatch(/^\d+vh$/);
  expect(valor(mapa, 'min-height')).toMatch(/^\d+(?:\.\d+)?rem$/);
  const painel = corpoEm(SOLTAS, '.crm-planeador__painel');
  expect(painel).not.toBeNull();
  expect(valor(painel, 'grid-area')).toBe('painel');
  expect(valor(painel, 'min-width')).toBe('0');
});

test('a partir de 1024 px, o painel (até 440 px) e o mapa lado a lado; só o painel se desloca', () => {
  const planeador = corpoEm(NO_DESKTOP, '.crm-planeador');
  expect(planeador).not.toBeNull();
  expect(valor(planeador, 'grid-template-columns')).toBe('minmax(0, 440px) minmax(0, 1fr)');
  expect(valor(planeador, 'grid-template-rows')).toBe('minmax(0, 1fr)');
  expect(valor(planeador, 'grid-template-areas')).toBe('"painel mapa"');
  expect(valor(planeador, 'overflow-y')).toBe('hidden');
  const painel = corpoEm(NO_DESKTOP, '.crm-planeador__painel');
  expect(painel).not.toBeNull();
  expect(valor(painel, 'overflow-y')).toBe('auto');
  expect(valor(painel, 'min-height')).toBe('0');
  const mapa = corpoEm(NO_DESKTOP, '.crm-planeador__mapa');
  expect(mapa).not.toBeNull();
  expect(valor(mapa, 'height')).toBe('auto');
  expect(valor(mapa, 'min-height')).toBe('0');
  // Só estas três regras mudam no computador.
  expect(NO_DESKTOP.filter((r) => r.seletores.some((s) => s.includes('crm-planeador'))).map((r) => r.cabeca).sort()).toEqual([
    '.crm-planeador',
    '.crm-planeador__mapa',
    '.crm-planeador__painel',
  ]);
});

test('o planeador e o painel (os que deslocam) contêm o que é absoluto lá dentro: os textos só para leitores de ecrã não fazem a página deslocar', () => {
  // T3.38: sem um antepassado posicionado, o `sr-only` (absoluto) da ListaParagens escapava ao deslocamento e
  // alongava a página no telemóvel (o `main` do ecrã cheio já não desloca).
  expect(valor(corpoEm(SOLTAS, '.crm-planeador'), 'position')).toBe('relative');
  expect(valor(corpoEm(SOLTAS, '.crm-planeador__painel'), 'position')).toBe('relative');
  // A área do mapa já o era (o .crm-mapa é absoluto dentro dela), e nenhum @media o muda.
  expect(valor(corpoEm(SOLTAS, '.crm-planeador__mapa'), 'position')).toBe('relative');
  for (const r of NO_DESKTOP.filter((regra) => regra.seletores.some((s) => s.includes('crm-planeador')))) {
    expect([r.cabeca, valor(r.corpo, 'position')]).toEqual([r.cabeca, null]);
  }
});

test('o painel, a lista e a pega vivem fora do mapa: nada deles é absoluto, fixo nem pegajoso', () => {
  const doPlaneador = REGRAS.filter((r) => r.seletores.some((s) => /crm-planeador|crm-lista-paragens|crm-paragem|crm-pega/.test(s)));
  expect(doPlaneador.length).toBeGreaterThanOrEqual(6);
  const soltas = doPlaneador.filter((r) => /absolute|fixed|sticky/.test(valor(r.corpo, 'position') ?? ''));
  expect(soltas.map((r) => r.cabeca)).toEqual([]);
  // E nenhum entra no elemento do mapa nem toca na Google (as asserções (a) e as guardas, para estas regras).
  for (const s of doPlaneador.flatMap((r) => r.seletores)) {
    expect([s, entraNoMapa(s) || tocaNaGoogle(s)]).toEqual([s, false]);
  }
});
