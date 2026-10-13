// Os ids do portal (plano §1, "Identificadores"): regiões, lojas e membros têm
// um `id` gravado com `str(uuid.uuid4())`, em texto. No CRM autónomo eram
// inteiros positivos; onde ele pedia um inteiro, o portal pede um `eUuid`.
//
// PADRAO_UUID4 é o `_UUID4` de backend/crm/dominio/validador_loja.py (o que o
// servidor aceita num `regiao_id`), verificado pelo último teste do
// ids.test.js, que lê esse ficheiro: minúsculas, versão 4, variante 8, 9, a
// ou b, tal e qual (sem aparar).

export const PADRAO_UUID4 = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';

// Sem a flag `m`, o `$` do JavaScript só aceita o fim do texto (um `\n` final
// fica de fora, ao contrário do `$` do Python).
const UUID4 = new RegExp(`^${PADRAO_UUID4}$`);

export function eUuid(valor) {
  return typeof valor === 'string' && UUID4.test(valor);
}
