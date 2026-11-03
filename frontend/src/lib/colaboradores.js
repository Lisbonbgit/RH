// O que vai no PUT do «Editar Colaborador», fora do JSX de propósito — ver
// colaboradores.test.js.

// O email como se compara: sem espaços e sem diferenciar maiúsculas (a mesma
// regra do servidor, em update_employee).
const chaveEmail = (email) => String(email ?? '').trim().toLowerCase();

/** O corpo do PUT /employees/{id} a partir do formulário e da ficha aberta.
 *  - a palavra-passe nunca vai (troca-se pelo «Redefinir palavra-passe»);
 *  - o email só vai quando MUDOU, e sem os espaços: mudá-lo muda o login do
 *    colaborador e apaga o código de recuperação pendente;
 *  - a foto (base64) não se reenvia se não mudou.
 *  Não altera o formulário. */
export function dadosParaAtualizar(formulario, ficha) {
  const dados = { ...formulario };
  delete dados.password;
  if (chaveEmail(dados.email) === chaveEmail(ficha?.email)) delete dados.email;
  else dados.email = String(dados.email ?? '').trim();
  if (dados.photo === (ficha?.photo || '')) delete dados.photo;
  return dados;
}
