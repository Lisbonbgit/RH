/**
 * AJUDAS DE DOM SEGURAS — `el()`, `hrefTelefone()` e `hrefNavegacao()`.
 *
 * Porta de tests/js/dom.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`. O
 * documento falso fica embutido, tal e qual: só tem createElement,
 * createTextNode, textContent, setAttribute e appendChild, e qualquer via de
 * HTML em texto (innerHTML, outerHTML, insertAdjacentHTML, document.write)
 * rebenta — se o `el()` a usasse, estes testes falhavam.
 *
 * O `dom.js` recebe sempre o documento por parâmetro. No portal, quem o chama
 * (as etiquetas dos pinos do `lib/crm/mapa.js`, T2.23) passa o `document` do
 * browser; os últimos testes fazem o mesmo com o `document` do jsdom.
 *
 * Os dados só entram no DOM como texto (regra 9 do plano; dossiê §0).
 *
 * O `hrefNavegacao` (F3 / T3.26) é a única porta dos links de navegação que o servidor calcula
 * (`paragem.links.google`/`.waze` e `rota.blocos_google[].href`, `backend/crm/dominio/navegacao.py`):
 * só passam os do Google Maps (`https://www.google.com/maps/dir/?api=1&…`) e os do Waze
 * (`https://waze.com/ul?…`), só com os caracteres de um URL (sem espaços, aspas, `<`, `>`, `|`, `\`
 * nem acentos); o resto dá `null` e o ecrã não desenha a ligação. Os prefixos leem-se do próprio
 * `navegacao.py` no último teste deste bloco: uma cópia dentro do teste não apanhava uma mudança do
 * servidor.
 */
/* eslint-disable no-script-url -- os 'javascript:' daqui são ataques que o el() tem de recusar */
import fs from 'fs';
import path from 'path';

import { el, hrefNavegacao, hrefTelefone } from './dom';

const NAVEGACAO_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'navegacao.py');

// Documento falso mínimo: só createElement/createTextNode, textContent,
// setAttribute e appendChild. Qualquer via de HTML em texto rebenta.
class NoTextoFalso {
  constructor(texto) { this.nodeType = 3; this.data = String(texto); }
  get textContent() { return this.data; }
}

class ElementoFalso {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.atributos = new Map();
    this.filhos = [];
  }
  get textContent() { return this.filhos.map((f) => f.textContent).join(''); }
  set textContent(valor) { this.filhos = [new NoTextoFalso(valor)]; }
  setAttribute(nome, valor) { this.atributos.set(String(nome), String(valor)); }
  getAttribute(nome) { return this.atributos.has(nome) ? this.atributos.get(nome) : null; }
  appendChild(filho) { this.filhos.push(filho); return filho; }
  set innerHTML(_) { throw new Error('innerHTML proibido'); }
  get innerHTML() { throw new Error('innerHTML proibido'); }
  set outerHTML(_) { throw new Error('outerHTML proibido'); }
  insertAdjacentHTML() { throw new Error('insertAdjacentHTML proibido'); }
}

function documentoFalso() {
  const criados = [];
  return {
    criados,
    createElement(tag) { const e = new ElementoFalso(tag); criados.push(e); return e; },
    createTextNode(texto) { return new NoTextoFalso(texto); },
    write() { throw new Error('document.write proibido'); },
  };
}

test('el: cria o elemento pedido', () => {
  const doc = documentoFalso();
  const no = el(doc, 'div');
  expect(no.tagName).toBe('DIV');
  expect(no.filhos.length).toBe(0);
  expect(no.atributos.size).toBe(0);
});

test('el: texto entra por textContent, literal, sem criar elementos', () => {
  const doc = documentoFalso();
  const no = el(doc, 'span', { texto: '<b>x</b>' });
  expect(no.textContent).toBe('<b>x</b>');
  expect(no.filhos.length).toBe(1);
  expect(no.filhos[0].nodeType).toBe(3);
  expect(doc.criados.length).toBe(1); // só o span foi criado
});

test('el: texto numérico e zero são mostrados', () => {
  const doc = documentoFalso();
  expect(el(doc, 'span', { texto: 0 }).textContent).toBe('0');
  expect(el(doc, 'span', { texto: 42 }).textContent).toBe('42');
});

test('el: classe como texto ou lista, via setAttribute', () => {
  const doc = documentoFalso();
  expect(el(doc, 'div', { classe: 'pino pino--cliente' }).getAttribute('class')).toBe('pino pino--cliente');
  expect(el(doc, 'div', { classe: ['botao', null, false, 'botao--primario'] }).getAttribute('class')).toBe('botao botao--primario');
  expect(el(doc, 'div', { classe: [] }).getAttribute('class')).toBe(null);
});

test('el: classe e texto false (padrão `cond && "x"`) não deixam "false" no DOM', () => {
  const doc = documentoFalso();
  expect(el(doc, 'div', { classe: false }).getAttribute('class')).toBe(null);
  expect(el(doc, 'div', { classe: '' }).getAttribute('class')).toBe(null);
  const semTexto = el(doc, 'span', { texto: false });
  expect(semTexto.textContent).toBe('');
  expect(semTexto.filhos.length).toBe(0);
});

test('el: atributos via setAttribute; true vira vazio; null/undefined/false são omitidos', () => {
  const doc = documentoFalso();
  const no = el(doc, 'input', {
    atributos: { type: 'text', name: 'nome', value: '<script>', required: true, disabled: false, placeholder: null, title: undefined, maxlength: 150 },
  });
  expect(no.getAttribute('type')).toBe('text');
  expect(no.getAttribute('name')).toBe('nome');
  expect(no.getAttribute('value')).toBe('<script>');
  expect(no.getAttribute('required')).toBe('');
  expect(no.getAttribute('maxlength')).toBe('150');
  expect(no.getAttribute('disabled')).toBe(null);
  expect(no.getAttribute('placeholder')).toBe(null);
  expect(no.getAttribute('title')).toBe(null);
});

test('el: recusa atributos de eventos (on*), em qualquer capitalização', () => {
  const doc = documentoFalso();
  for (const nome of ['onclick', 'onerror', 'OnLoad', 'ONMOUSEOVER', 'on']) {
    expect(() => el(doc, 'img', { atributos: { [nome]: 'alert(1)' } })).toThrow(/Atributo de evento recusado/);
  }
  // Só o nome conta, não o valor.
  expect(el(doc, 'img', { atributos: { alt: 'onde' } }).getAttribute('alt')).toBe('onde');
});

test('el: recusa srcdoc e URLs javascript:/vbscript: em atributos de ligação', () => {
  const doc = documentoFalso();
  expect(() => el(doc, 'iframe', { atributos: { srcdoc: '<b>x</b>' } })).toThrow();
  for (const valor of ['javascript:alert(1)', ' JavaScript:alert(1)', 'java\nscript:alert(1)', 'vbscript:msgbox(1)', '\u0000javascript:x']) {
    expect(() => el(doc, 'a', { atributos: { href: valor } })).toThrow();
    expect(() => el(doc, 'img', { atributos: { src: valor } })).toThrow();
    expect(() => el(doc, 'form', { atributos: { action: valor } })).toThrow();
  }
  expect(el(doc, 'a', { atributos: { href: '#/lojas/3' } }).getAttribute('href')).toBe('#/lojas/3');
  expect(el(doc, 'a', { atributos: { href: 'tel:+351912345678' } }).getAttribute('href')).toBe('tel:+351912345678');
  expect(el(doc, 'img', { atributos: { src: '/icone.svg' } }).getAttribute('src')).toBe('/icone.svg');
  expect(el(doc, 'form', { atributos: { action: '/api/login' } }).getAttribute('action')).toBe('/api/login');
  expect(() => el(doc, 'a', { atributos: { HREF: 'javascript:alert(1)' } })).toThrow(/URL recusada/);
  expect(() => el(doc, 'button', { atributos: { formaction: 'javascript:x' } })).toThrow(/URL recusada/);
});

test('el: filhos são nós ou textos (textos viram nós de texto); nulos são ignorados', () => {
  const doc = documentoFalso();
  const filho = el(doc, 'strong', { texto: 'Nome' });
  const no = el(doc, 'p', { filhos: [filho, ': ', '<i>x</i>', null, undefined, false, 7, [el(doc, 'em', { texto: 'a' })]] });
  expect(no.filhos.length).toBe(5);
  expect(no.filhos[0]).toBe(filho);
  expect(no.filhos[1].nodeType).toBe(3);
  expect(no.filhos[2].textContent).toBe('<i>x</i>');
  expect(no.filhos[3].textContent).toBe('7');
  expect(no.filhos[4].tagName).toBe('EM');
  expect(no.textContent).toBe('Nome: <i>x</i>7a');
});

test('el: texto e filhos juntos — o texto vem primeiro', () => {
  const doc = documentoFalso();
  const no = el(doc, 'button', { texto: 'Guardar ', filhos: [el(doc, 'span', { texto: '(sem rede)' })] });
  expect(no.textContent).toBe('Guardar (sem rede)');
});

test('hrefTelefone: só dígitos e o + inicial', () => {
  expect(hrefTelefone('+351 912 345 678')).toBe('tel:+351912345678');
  expect(hrefTelefone('912 345 678')).toBe('tel:912345678');
  expect(hrefTelefone('(+351) 21-234-5678')).toBe('tel:+351212345678');
  expect(hrefTelefone('  +351912345678  ')).toBe('tel:+351912345678');
  expect(hrefTelefone('00351 912345678')).toBe('tel:00351912345678');
  expect(hrefTelefone(912345678)).toBe('tel:912345678');
});

test('hrefTelefone: um + que não está antes do primeiro dígito é descartado', () => {
  expect(hrefTelefone('91+2345678 9')).toBe('tel:9123456789');
  expect(hrefTelefone('++351912345678')).toBe('tel:+351912345678');
});

test('hrefTelefone: descarta letras, separadores e tentativas de injeção', () => {
  expect(hrefTelefone('912345678"><script>')).toBe('tel:912345678');
  expect(hrefTelefone('javascript:912345678')).toBe('tel:912345678');
  expect(hrefTelefone('912 345 678 ext. 2')).toBe('tel:9123456782');
});

test('hrefTelefone: menos de 9 dígitos ou vazio → null', () => {
  expect(hrefTelefone('12345678')).toBe(null);
  expect(hrefTelefone('+351 1234')).toBe(null);
  expect(hrefTelefone('')).toBe(null);
  expect(hrefTelefone('   ')).toBe(null);
  expect(hrefTelefone(null)).toBe(null);
  expect(hrefTelefone(undefined)).toBe(null);
  expect(hrefTelefone('sem telefone')).toBe(null);
});

// --- hrefNavegacao: só os links de navegação que o servidor calcula ---

// Os links exatos do backend/tests/crm/test_dominio_navegacao.py (T3.10).
const GOOGLE = 'https://www.google.com/maps/dir/?api=1&destination=38.710800,-9.136900&travelmode=driving&dir_action=navigate';
const WAZE = 'https://waze.com/ul?ll=38.710800,-9.136900&navigate=yes';
const BLOCO = 'https://www.google.com/maps/dir/?api=1&destination=38.711100,-9.136900&waypoints=38.710800,-9.136900%7C38.710900,-9.136900&travelmode=driving&dir_action=navigate';

test.each([
  ['Google Maps, uma paragem', GOOGLE],
  ['Google Maps, a evitar portagens', `${GOOGLE}&avoid=tolls`],
  ['Google Maps, um bloco com waypoints (o | codificado)', BLOCO],
  ['Waze', WAZE],
  ['Waze, a evitar portagens', `${WAZE}&avoid_tolls=true`],
])('hrefNavegacao deixa passar o link do servidor, tal e qual: %s', (_, link) => {
  expect(hrefNavegacao(link)).toBe(link);
});

test.each([
  ['javascript:', 'javascript:alert(1)'],
  ['javascript: com o caminho do Google', 'javascript://www.google.com/maps/dir/?api=1&%0aalert(1)'],
  ['data:', 'data:text/html,<b>x</b>'],
  ['http: (sem cifra)', 'http://www.google.com/maps/dir/?api=1&destination=38.7,-9.1'],
  ['o esquema em maiúsculas', 'HTTPS://waze.com/ul?ll=38.7,-9.1&navigate=yes'],
  ['sem esquema', '//waze.com/ul?ll=38.7,-9.1&navigate=yes'],
  ['outro domínio', 'https://exemplo.invalid/maps/dir/?api=1&destination=38.7,-9.1'],
  ['um domínio que só começa como o da Google', 'https://www.google.com.exemplo.invalid/maps/dir/?api=1&x=1'],
  ['um domínio que só começa como o do Waze', 'https://waze.com.exemplo.invalid/ul?ll=38.7,-9.1'],
  ['o Google sem www', 'https://google.com/maps/dir/?api=1&destination=38.7,-9.1'],
  ['outro serviço da Google', 'https://maps.google.com/maps/dir/?api=1&destination=38.7,-9.1'],
  ['outra página do Google Maps', 'https://www.google.com/maps/search/?api=1&query=38.7,-9.1'],
  ['outra versão da API', 'https://www.google.com/maps/dir/?api=2&destination=38.7,-9.1'],
  ['o Waze com www', 'https://www.waze.com/ul?ll=38.7,-9.1&navigate=yes'],
  ['outra página do Waze', 'https://waze.com/live-map?ll=38.7,-9.1'],
  ['o Waze sem o ?', 'https://waze.com/ul'],
  ['o prefixo do Google sozinho', 'https://www.google.com/maps/dir/?api=1&'],
  ['o Google sem o &', 'https://www.google.com/maps/dir/?api=1'],
  ['o prefixo do Waze sozinho', 'https://waze.com/ul?'],
  ['um link escondido noutro', 'https://exemplo.invalid/?https://waze.com/ul?ll=38.7,-9.1'],
  ['aspas', `${WAZE}&x="`],
  ['aspas que fecham o atributo', `${GOOGLE}"><img src=x onerror=alert(1)>`],
  ['plica', `${WAZE}&x='`],
  ['<', `${WAZE}&x=<`],
  ['>', `${WAZE}&x=>`],
  ['| em claro', 'https://www.google.com/maps/dir/?api=1&destination=1,1&waypoints=2,2|3,3'],
  ['barra invertida', `${WAZE}\\`],
  ['acento grave', `${WAZE}\``],
  ['um espaço no meio', `${WAZE}&x=a b`],
  ['um espaço antes', ` ${WAZE}`],
  ['um espaço depois', `${WAZE} `],
  ['uma mudança de linha', `${WAZE}\n`],
  ['um tab', `${WAZE}\t`],
  ['um NUL', `${WAZE}\u0000`],
  ['um acento', `${WAZE}&x=ç`],
  ['vazio', ''],
])('hrefNavegacao recusa: %s → null', (_, link) => {
  expect(hrefNavegacao(link)).toBe(null);
});

test.each([[null], [undefined], [42], [true], [[WAZE]], [{ toString: () => WAZE }], [Object(WAZE)]])(
  'hrefNavegacao recusa o que não é texto (%p) → null',
  (valor) => {
    expect(hrefNavegacao(valor)).toBe(null);
  },
);

test('hrefNavegacao aceita os links que o navegacao.py do servidor monta (os prefixos lidos de lá)', () => {
  const texto = fs.readFileSync(NAVEGACAO_PY, 'utf8');
  const google = /^_GOOGLE = "([^"]+)"$/m.exec(texto);
  const waze = /^_WAZE = "([^"]+)"$/m.exec(texto);
  expect(google).not.toBe(null);
  expect(waze).not.toBe(null);
  expect(google[1]).toBe('https://www.google.com/maps/dir/?api=1');
  expect(waze[1]).toBe('https://waze.com/ul?');
  // O servidor junta "&destination=…" ao do Google e "ll=…" ao do Waze.
  expect(hrefNavegacao(`${google[1]}&destination=38.710800,-9.136900`)).not.toBe(null);
  expect(hrefNavegacao(`${waze[1]}ll=38.710800,-9.136900`)).not.toBe(null);
  // E o servidor codifica o separador dos waypoints, que aqui se recusa em claro.
  expect(/^_SEPARADOR_WAYPOINTS = "%7C"$/m.test(texto)).toBe(true);
});

// --- O mesmo `el()` com o `document` do jsdom, como no browser ---

test('jsdom: um nome <b>x</b> fica texto literal, sem criar <b>', () => {
  const no = el(document, 'span', { classe: 'etiqueta-loja', texto: '<b>x</b>' });
  expect(no.tagName).toBe('SPAN');
  expect(no.getAttribute('class')).toBe('etiqueta-loja');
  expect(no.textContent).toBe('<b>x</b>');
  expect(no.childNodes).toHaveLength(1);
  expect(no.childNodes[0].nodeType).toBe(Node.TEXT_NODE);
  expect(no.querySelector('b')).toBe(null);
});

test('jsdom: filhos em texto também ficam texto, e os nós entram tal e qual', () => {
  const forte = el(document, 'strong', { texto: 'Loja' });
  const no = el(document, 'p', { filhos: [forte, ' <img src=x onerror=alert(1)>'] });
  expect(no.firstChild).toBe(forte);
  expect(no.textContent).toBe('Loja <img src=x onerror=alert(1)>');
  expect(no.querySelector('img')).toBe(null);
  expect(no.children).toHaveLength(1);
});

test('jsdom: a ligação "Ligar" leva o tel: do hrefTelefone; javascript: é recusado', () => {
  const ligar = el(document, 'a', { texto: 'Ligar', atributos: { href: hrefTelefone('+351 912 345 678') } });
  expect(ligar.getAttribute('href')).toBe('tel:+351912345678');
  expect(ligar.textContent).toBe('Ligar');
  // Sem telefone válido não há href (null é omitido).
  expect(el(document, 'a', { atributos: { href: hrefTelefone('1234') } }).hasAttribute('href')).toBe(false);
  expect(() => el(document, 'a', { atributos: { href: 'javascript:alert(1)' } })).toThrow(/URL recusada/);
  expect(() => el(document, 'img', { atributos: { onerror: 'alert(1)' } })).toThrow(/Atributo de evento recusado/);
});

test('jsdom: a ligação do Waze leva o href do hrefNavegacao; um link recusado fica sem href', () => {
  const waze = el(document, 'a', {
    texto: 'Waze',
    atributos: { href: hrefNavegacao(WAZE), target: '_blank', rel: 'noopener noreferrer' },
  });
  expect(waze.getAttribute('href')).toBe(WAZE);
  expect(waze.textContent).toBe('Waze');
  const recusado = el(document, 'a', { texto: 'Google Maps', atributos: { href: hrefNavegacao('javascript:alert(1)') } });
  expect(recusado.hasAttribute('href')).toBe(false);
});
