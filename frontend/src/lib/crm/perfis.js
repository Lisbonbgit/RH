// Os perfis dos membros do CRM e os nomes em pt-PT. Funções puras.
// Porta de public/assets/js/perfis.js do CRM autónomo, com o terceiro perfil
// do portal, o motorista (plano T2.21).
//
// Os valores são os PERFIS de backend/crm/dominio/membros.py (o perfis.test.js
// lê esse ficheiro), mas a ordem é a do ecrã dos membros: o mais comum
// primeiro, porque o primeiro é o que o "Adicionar" escolhe por omissão —
// nunca o admin.

export const PERFIS = Object.freeze([
  Object.freeze({ valor: 'utilizador', rotulo: 'Utilizador' }),
  Object.freeze({ valor: 'admin', rotulo: 'Administrador' }),
  Object.freeze({ valor: 'motorista', rotulo: 'Motorista' }),
]);

// 'admin' → 'Administrador'. Um valor desconhecido (de uma versão mais nova do servidor) fica como está.
export function rotuloPerfil(perfil) {
  return PERFIS.find((p) => p.valor === perfil)?.rotulo ?? (typeof perfil === 'string' ? perfil : '');
}
