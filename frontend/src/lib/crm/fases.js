// Fases da loja (desenho original §4.1; dossiê §5.1). Porta de
// public/assets/js/fases.js do CRM autónomo.
//
// A ORDEM tem de ser a de backend/crm/dominio/fases.py, verificado pelo
// backend/tests/crm/test_consistencia_frontend.py (e pelo último teste do
// fases.test.js): manter ORDEM numa só linha, e cada fase de FASES numa linha
// que começa por `<fase>: Object.freeze({ id: '<fase>', rotulo: …, cor: …`.

export const ORDEM = Object.freeze(['perdida', 'potencial', 'contactada', 'amostra', 'cliente']);

// A ordem do funil, a que faz sentido a quem escolhe ou filtra uma fase (a ORDEM é a das regras automáticas).
export const FUNIL = Object.freeze(['potencial', 'contactada', 'amostra', 'cliente', 'perdida']);

// Cores fixas dos pinos (não seguem o tema do portal: o mapa é o mesmo no claro e no escuro).
// O `rotulo` é o nome no ecrã e a única fonte dele (filtros, formulário, cartão, ficha, título do
// pino); o `id` é a chave da API e do histórico, e nunca muda com o nome (desenho original §4.1).
export const FASES = Object.freeze({
  perdida: Object.freeze({ id: 'perdida', rotulo: 'Perdida', cor: '#1a1a1a', contorno: null }),
  potencial: Object.freeze({ id: 'potencial', rotulo: 'Potencial', cor: '#cfcfcf', contorno: '#888' }),
  contactada: Object.freeze({ id: 'contactada', rotulo: 'A aguardar amostra', cor: '#f4c20d', contorno: null }),
  amostra: Object.freeze({ id: 'amostra', rotulo: 'Amostra recebida', cor: '#f08a24', contorno: null }),
  cliente: Object.freeze({ id: 'cliente', rotulo: 'Cliente', cor: '#6b2fa3', contorno: null }),
});

// Classe CSS do pino (L.divIcon, sem html). Só fases conhecidas entram no nome da classe.
export function classePino(fase) {
  return ORDEM.includes(fase) ? `pino pino--${fase}` : 'pino';
}
