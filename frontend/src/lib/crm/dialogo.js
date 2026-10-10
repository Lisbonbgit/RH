// O diálogo do 409 duplicado: "Já existe X aqui — é a mesma?" (desenho
// original §6.2), na nova loja (T2.27) e ao corrigir a localização na ficha
// (T2.28). Regras puras: porta da parte de
// public/assets/js/componentes/dialogo.js do CRM autónomo que não é DOM. O
// `components/crm/DialogoDuplicado.js` desenha isto num `AlertDialog` do
// shadcn.
//
// Três respostas, como no autónomo (correção "componentes Sem Jest"):
//  - 'Sim, abrir X' → 'abrir' (abrir a ficha da loja que já existe);
//  - 'Não, é outra loja' → 'outra' (gravar na mesma, com `confirmar_duplicado`);
//  - 'Cancelar' (ou o Escape) → null (não fazer nada).
// O nome da loja vem do servidor (de quem a registou): fica em partes de texto,
// que o React escreve como texto, nunca como HTML.
//
// Adaptação dos ids (plano T2.24a): a loja do 409 tem um uuid em texto, e não
// um inteiro positivo.
import { eUuid } from './ids';

export const RESPOSTA_ABRIR = 'abrir';
export const RESPOSTA_OUTRA = 'outra';
export const TEXTO_OUTRA_LOJA = 'Não, é outra loja';
export const TEXTO_CANCELAR = 'Cancelar';

const textoAbrir = (nome) => `Sim, abrir ${nome}`;

// A loja mais perto da lista do 409 duplicado ({id, nome, distancia_m}, da mais perto para a mais longe), ou
// null. Só a primeira conta.
export function lojaDuplicada(lista) {
  const loja = Array.isArray(lista) ? lista[0] : null;
  return eUuid(loja?.id) && typeof loja.nome === 'string' ? loja : null;
}

const parte = (texto, forte = false) => Object.freeze({ texto, forte });
const botao = (texto, valor, variante) => Object.freeze({ texto, valor, variante });

// A pergunta e os botões do diálogo da loja `loja` (a de `lojaDuplicada`):
// {mensagem: [{texto, forte}], botoes: [{texto, valor, variante: 'principal'|'normal'|'discreto'}]}.
export function dialogoDuplicado(loja) {
  const nome = String(loja?.nome ?? '');
  return Object.freeze({
    mensagem: Object.freeze([parte('Já existe '), parte(nome, true), parte(' aqui — é a mesma?')]),
    botoes: Object.freeze([
      botao(textoAbrir(nome), RESPOSTA_ABRIR, 'principal'),
      botao(TEXTO_OUTRA_LOJA, RESPOSTA_OUTRA, 'normal'),
      botao(TEXTO_CANCELAR, null, 'discreto'),
    ]),
  });
}

// Uma pergunta, uma resposta: só a primeira escolha conta (dois toques seguidos, ou um toque e o Escape,
// não fazem duas coisas). `escolher(valor)` diz se esta foi a que contou.
export function criarEscolhaUnica(aoEscolher) {
  let escolhida = false;
  return {
    get escolhida() {
      return escolhida;
    },
    escolher(valor) {
      if (escolhida) return false;
      escolhida = true;
      aoEscolher?.(valor);
      return true;
    },
  };
}
