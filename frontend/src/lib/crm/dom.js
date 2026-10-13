// Ajudas de DOM seguras. Porta de public/assets/js/dom.js do CRM autónomo.
//
// Os dados só entram no DOM por textContent, createElement, createTextNode e
// setAttribute — nunca como HTML em texto (regra 9 do plano; dossiê §0). O
// documento é sempre recebido por parâmetro (testável com um documento falso).
// No portal, o React já escapa o texto; isto serve onde se monta DOM à mão
// para o Leaflet (ex.: a etiqueta permanente de cada pino, em `lib/crm/mapa.js`).

const ATRIBUTOS_URL = new Set(['href', 'src', 'action', 'formaction', 'xlink:href', 'poster']);

function urlPerigosa(valor) {
  // Os browsers ignoram espaços e caracteres de controlo no esquema.
  // eslint-disable-next-line no-control-regex
  const limpo = String(valor).replace(/[\u0000- \u007f-\u009f]/g, '').toLowerCase();
  // O esquema aparece aqui só para ser RECUSADO (o no-script-url avisa de qualquer texto 'javascript:').
  // eslint-disable-next-line no-script-url
  return limpo.startsWith('javascript:') || limpo.startsWith('vbscript:');
}

function validarAtributo(nome, valor) {
  const minusculas = String(nome).toLowerCase();
  if (minusculas.startsWith('on')) {
    throw new Error(`Atributo de evento recusado: ${nome} (use addEventListener)`);
  }
  if (minusculas === 'srcdoc') {
    throw new Error('Atributo recusado: srcdoc');
  }
  if (ATRIBUTOS_URL.has(minusculas) && urlPerigosa(valor)) {
    throw new Error(`URL recusada no atributo ${nome}`);
  }
}

function acrescentarFilhos(documento, no, filhos) {
  for (const filho of filhos) {
    if (filho === null || filho === undefined || filho === false) continue;
    if (Array.isArray(filho)) {
      acrescentarFilhos(documento, no, filho);
    } else if (typeof filho === 'object') {
      no.appendChild(filho);
    } else {
      no.appendChild(documento.createTextNode(String(filho)));
    }
  }
}

// el(document, 'span', {texto, classe, atributos: {href: 'tel:+351…'}, filhos: [...]})
export function el(documento, tag, { texto, classe, atributos, filhos } = {}) {
  const no = documento.createElement(tag);

  // false/null/undefined = "sem classe" e "sem texto" (padrão `cond && 'x'`).
  if (classe !== undefined && classe !== null && classe !== false) {
    const classes = Array.isArray(classe) ? classe.filter(Boolean).join(' ') : String(classe);
    if (classes !== '') no.setAttribute('class', classes);
  }

  if (atributos) {
    for (const [nome, valor] of Object.entries(atributos)) {
      if (valor === null || valor === undefined || valor === false) continue;
      const texto = valor === true ? '' : String(valor);
      validarAtributo(nome, texto);
      no.setAttribute(nome, texto);
    }
  }

  if (texto !== undefined && texto !== null && texto !== false) no.textContent = String(texto);
  if (filhos) acrescentarFilhos(documento, no, filhos);

  return no;
}

// '+351 912 345 678' → 'tel:+351912345678'. Só dígitos e um '+' antes do
// primeiro dígito. Menos de 9 dígitos → null (não há ligação para marcar).
// Desde 2026-10-13 o cartão da loja já não a usa (mostra o contacto em texto);
// fica para quem vier a precisar de uma ligação para marcar.
export function hrefTelefone(telefone) {
  if (telefone === null || telefone === undefined) return null;
  const texto = String(telefone);
  const primeiroDigito = texto.search(/[0-9]/);
  if (primeiroDigito === -1) return null;
  const digitos = texto.replace(/[^0-9]/g, '');
  if (digitos.length < 9) return null;
  const mais = texto.slice(0, primeiroDigito).includes('+') ? '+' : '';
  return `tel:${mais}${digitos}`;
}
