// DOM falso para os testes do CRM (só testes; fica fora do varrimento do
// seguranca.test.js, que exclui a pasta `testes/`).
//
// Porta de tests/js/apoio/dom-falso.js do CRM autónomo (etiqueta
// `referencia-standalone`), tal e qual, com os comentários adaptados ao
// portal (correção "T2.23 (porta do mapa.test.js e seguranca.test.js)").
// No Jest do CRA o EventTarget e o Event são os do jsdom.
//
// Só existe o que o código do CRM pode usar: createElement/createTextNode,
// atributos, textContent, appendChild/replaceChildren/remove,
// value/disabled/hidden, focus e eventos. Qualquer via de HTML em texto
// (innerHTML, outerHTML, insertAdjacentHTML, document.write) rebenta, para os
// testes apanharem dados a entrar no DOM como HTML (regra 9 do plano; dossiê §0).

const proibido = (via) => () => {
  throw new Error(`${via} proibido`);
};

export class NoTextoFalso {
  constructor(texto) {
    this.nodeType = 3;
    this.data = String(texto);
    this.parentNode = null;
  }

  get textContent() { return this.data; }

  set textContent(valor) { this.data = String(valor); }

  remove() { this.parentNode?.removerFilho(this); }
}

export class ElementoFalso extends EventTarget {
  constructor(documento, tag) {
    super();
    this.ownerDocument = documento;
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.atributos = new Map();
    this.childNodes = [];
    this.parentNode = null;
    this.value = '';
  }

  // Atributos
  setAttribute(nome, valor) { this.atributos.set(String(nome), String(valor)); }

  getAttribute(nome) { return this.atributos.has(nome) ? this.atributos.get(nome) : null; }

  hasAttribute(nome) { return this.atributos.has(nome); }

  removeAttribute(nome) { this.atributos.delete(nome); }

  get id() { return this.getAttribute('id') ?? ''; }

  get className() { return this.getAttribute('class') ?? ''; }

  get classes() { return this.className.split(/\s+/).filter(Boolean); }

  // Propriedades refletidas em atributos booleanos (como no browser).
  get hidden() { return this.hasAttribute('hidden'); }

  set hidden(valor) { this.alternarBooleano('hidden', valor); }

  get disabled() { return this.hasAttribute('disabled'); }

  set disabled(valor) { this.alternarBooleano('disabled', valor); }

  alternarBooleano(nome, valor) {
    if (valor) this.setAttribute(nome, '');
    else this.removeAttribute(nome);
  }

  // Árvore
  get children() { return this.childNodes.filter((no) => no.nodeType === 1); }

  get textContent() { return this.childNodes.map((no) => no.textContent).join(''); }

  set textContent(valor) {
    this.replaceChildren();
    if (valor !== '' && valor !== null && valor !== undefined) this.appendChild(new NoTextoFalso(valor));
  }

  appendChild(no) {
    if (no === null || typeof no !== 'object' || !('nodeType' in no)) {
      throw new TypeError('appendChild: não é um nó');
    }
    no.parentNode?.removerFilho(no);
    no.parentNode = this;
    this.childNodes.push(no);
    return no;
  }

  append(...nos) {
    for (const no of nos) this.appendChild(typeof no === 'string' ? new NoTextoFalso(no) : no);
  }

  replaceChildren(...nos) {
    for (const no of this.childNodes) no.parentNode = null;
    this.childNodes = [];
    this.append(...nos);
  }

  removerFilho(no) {
    this.childNodes = this.childNodes.filter((filho) => filho !== no);
    no.parentNode = null;
  }

  remove() { this.parentNode?.removerFilho(this); }

  contains(no) {
    for (let atual = no; atual; atual = atual.parentNode) if (atual === this) return true;
    return false;
  }

  get isConnected() {
    let atual = this;
    while (atual.parentNode) atual = atual.parentNode;
    return atual === this.ownerDocument.body;
  }

  focus() { this.ownerDocument.activeElement = this; }

  // Clique como no browser: um botão de um formulário submete-o (exceto type="button").
  click() {
    if (this.disabled) return;
    const evento = new Event('click', { cancelable: true });
    this.dispatchEvent(evento);
    if (evento.defaultPrevented || this.tagName !== 'BUTTON') return;
    const tipo = this.getAttribute('type') ?? 'submit';
    if (tipo !== 'submit') return;
    const formulario = ascendente(this, (no) => no.tagName === 'FORM');
    formulario?.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  get innerHTML() { throw new Error('innerHTML proibido'); }

  set innerHTML(_) { throw new Error('innerHTML proibido'); }

  get outerHTML() { throw new Error('outerHTML proibido'); }

  set outerHTML(_) { throw new Error('outerHTML proibido'); }
}

ElementoFalso.prototype.insertAdjacentHTML = proibido('insertAdjacentHTML');

// <dialog> como no browser: showModal() só com o diálogo na página e fechado;
// close() tira o `open` e emite 'close'; o Escape emite 'cancel' e, se ninguém
// o impedir, fecha (premirEscape).
export class DialogoFalso extends ElementoFalso {
  constructor(documento, tag) {
    super(documento, tag);
    this.modal = false;
    this.returnValue = '';
  }

  get open() { return this.hasAttribute('open'); }

  showModal() {
    if (this.open) throw new Error('InvalidStateError: o diálogo já está aberto');
    if (!this.isConnected) throw new Error('InvalidStateError: o diálogo não está na página');
    this.setAttribute('open', '');
    this.modal = true;
  }

  close(valor) {
    if (!this.open) return;
    this.removeAttribute('open');
    this.modal = false;
    if (valor !== undefined) this.returnValue = String(valor);
    this.dispatchEvent(new Event('close'));
  }

  premirEscape() {
    const evento = new Event('cancel', { cancelable: true });
    this.dispatchEvent(evento);
    if (!evento.defaultPrevented) this.close();
  }
}

export function documentoFalso() {
  const documento = {
    title: '',
    activeElement: null,
    createElement: (tag) => (String(tag).toLowerCase() === 'dialog'
      ? new DialogoFalso(documento, tag)
      : new ElementoFalso(documento, tag)),
    createTextNode: (texto) => new NoTextoFalso(texto),
    write: proibido('document.write'),
    writeln: proibido('document.writeln'),
  };
  documento.body = new ElementoFalso(documento, 'body');
  return documento;
}

// Janela falsa: location.hash e history.replaceState como no browser. Mudar o
// hash por atribuição dispara o 'hashchange' de forma assíncrona (e só se
// mudou); o replaceState não dispara nada.
export function janelaFalsa(hash = '') {
  const janela = new EventTarget();
  let atual = hash;
  janela.navegacoes = [];
  janela.location = {
    get hash() { return atual; },
    set hash(novo) {
      const normalizado = novo === '' || String(novo).startsWith('#') ? String(novo) : `#${novo}`;
      if (normalizado === atual) return;
      atual = normalizado;
      janela.navegacoes.push(normalizado);
      setTimeout(() => janela.dispatchEvent(new Event('hashchange')), 0);
    },
  };
  janela.history = {
    replaceState(_estado, _titulo, url) {
      const texto = String(url);
      atual = texto.startsWith('#') ? texto : '';
    },
  };
  // O utilizador muda o hash (ex.: toca numa ligação ou no "voltar").
  janela.irPara = (novo) => {
    janela.location.hash = novo;
  };
  return janela;
}

// Procura na árvore
export function descendentes(raiz) {
  const lista = [];
  const visitar = (no) => {
    for (const filho of no.children ?? []) {
      lista.push(filho);
      visitar(filho);
    }
  };
  visitar(raiz);
  return lista;
}

export function ascendente(no, predicado) {
  for (let atual = no.parentNode; atual; atual = atual.parentNode) if (predicado(atual)) return atual;
  return null;
}

export const procurar = (raiz, predicado) => descendentes(raiz).find(predicado) ?? null;

export const procurarTodos = (raiz, predicado) => descendentes(raiz).filter(predicado);

// O elemento <tag> cujo texto (sem espaços nas pontas) é `texto`.
export const porTexto = (raiz, tag, texto) =>
  procurar(raiz, (no) => no.tagName === tag.toUpperCase() && no.textContent.trim() === texto);

export const porClasse = (raiz, classe) => procurar(raiz, (no) => no.classes.includes(classe));

// O campo cujo <label> tem o texto `rotulo` (pelo for/id).
export function campoPorRotulo(raiz, rotulo) {
  const label = porTexto(raiz, 'label', rotulo);
  if (!label) return null;
  const id = label.getAttribute('for');
  return procurar(raiz, (no) => no.id === id && no !== label);
}

// Deixa correr as promessas e os temporizadores pendentes (fetch falso, hashchange).
export async function assentar(voltas = 10) {
  for (let i = 0; i < voltas; i += 1) await new Promise((resolver) => setTimeout(resolver, 0));
}
