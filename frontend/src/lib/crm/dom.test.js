/**
 * AJUDAS DE DOM SEGURAS — `el()` e `hrefTelefone()`.
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
 */
/* eslint-disable no-script-url -- os 'javascript:' daqui são ataques que o el() tem de recusar */
import { el, hrefTelefone } from './dom';

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
