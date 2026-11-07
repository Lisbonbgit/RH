// O que vai no PUT do «Editar Colaborador», fora do JSX de propósito — ver
// colaboradores.test.js.
import { mensagemDoErro as mensagemGenerica } from './erros';

// O email como se compara para saber se MUDOU: sem os espaços, mas com as
// maiúsculas — corrigir só as maiúsculas também se grava, é como o email se
// mostra e se escreve (a mesma regra do servidor, em _correcao_do_email).
const emailLimpo = (email) => String(email ?? '').trim();

/** O corpo do PUT /employees/{id} a partir do formulário e da ficha aberta.
 *  - a palavra-passe nunca vai (troca-se pelo «Redefinir palavra-passe»);
 *  - o email só vai quando MUDOU, e sem os espaços: mudá-lo muda o login do
 *    colaborador e apaga o código de recuperação pendente;
 *  - a foto (base64) não se reenvia se não mudou.
 *  Não altera o formulário. */
export function dadosParaAtualizar(formulario, ficha) {
  const dados = { ...formulario };
  delete dados.password;
  if (emailLimpo(dados.email) === emailLimpo(ficha?.email)) delete dados.email;
  else dados.email = emailLimpo(dados.email);
  if (dados.photo === (ficha?.photo || '')) delete dados.photo;
  return dados;
}

/** O texto para o toast quando gravar o colaborador falha — sempre uma string.
 *  A regra é a de lib/erros.js (o 422 do FastAPI traz uma LISTA de objetos, que o
 *  sonner desenhava como filho React: portal em branco). */
export const mensagemDoErro = (error) => mensagemGenerica(error, 'Erro ao guardar colaborador');
