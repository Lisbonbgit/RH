// Diferenças entre a loja carregada e o formulário da ficha, para o PATCH só
// levar o que mudou (com o `atualizado_em`, dossiê §5.10). Funções puras.
// Porta de public/assets/js/diferencas.js do CRM autónomo, tal e qual. Os
// campos novos do portal (o Instagram e o site, 2026-10-13) são textos
// simples, como o telefone: nada aqui os conhece pelo nome.

// A API exige estes campos juntos (backend/crm/dominio/validador_loja.py,
// `alteracao`): se um muda, vão todos.
export const CAMPOS_LOCALIZACAO = Object.freeze(['lat', 'lng', 'origem_coords', 'precisao_m']);

function vazio(valor) {
  return valor === null || valor === undefined || valor === '';
}

// Listas (ex.: dias_fechada) são conjuntos: comparam-se por valor e sem contar a ordem.
function iguais(a, b) {
  if (vazio(a) && vazio(b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    const ordenadoA = [...a].sort();
    const ordenadoB = [...b].sort();
    return ordenadoA.every((valor, i) => valor === ordenadoB[i]);
  }
  return a === b;
}

// O que se envia: um campo limpo no formulário ('') vai como null, o "sem valor" da API.
function paraEnviar(valor) {
  return vazio(valor) ? null : valor;
}

// Devolve só as chaves de `atual` cujo valor difere de `original`.
// Um campo vazio do formulário ('') equivale a null e é enviado como null.
// Chaves que `atual` não traz são ignoradas.
export function camposAlterados(original, atual) {
  const alterados = {};
  let localizacaoMudou = false;

  for (const chave of Object.keys(atual)) {
    if (iguais(original[chave], atual[chave])) continue;
    if (CAMPOS_LOCALIZACAO.includes(chave)) {
      localizacaoMudou = true;
    } else {
      alterados[chave] = paraEnviar(atual[chave]);
    }
  }

  if (localizacaoMudou) {
    for (const chave of CAMPOS_LOCALIZACAO) {
      alterados[chave] = paraEnviar(atual[chave] !== undefined ? atual[chave] : original[chave]);
    }
  }

  return alterados;
}
