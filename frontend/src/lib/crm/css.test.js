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
 */
import fs from 'fs';
import path from 'path';
import { FASES, ORDEM } from './fases';
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
