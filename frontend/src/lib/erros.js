// O erro de um pedido em texto para o ecrã — sempre uma string. Ver erros.test.js.
//
// O `detail` de um 422 do FastAPI é uma LISTA de objetos ([{type, loc, msg,
// input, ctx}]): entregue cru ao toast, o sonner desenha-o como filho React
// («Objects are not valid as a React child»), o React desmonta tudo e o portal
// fica em branco. Foi o que fez o login com «carlos@gmailcom»: o <input
// type="email"> aceita-o, o EmailStr do servidor não.

export const MENSAGEM_EMAIL_INVALIDO = 'Email inválido. Verifique como está escrito.';

/** A frase de uma lista de validação do FastAPI, ou `null` se não se souber ler:
 *  no campo email a frase de cima, noutro a `msg` do validador sem o «Value error, ». */
export function fraseDaValidacao(lista) {
  if (!Array.isArray(lista) || lista.length === 0) return null;
  const primeiro = lista[0] || {};
  const campo = Array.isArray(primeiro.loc) ? primeiro.loc[primeiro.loc.length - 1] : null;
  // A explicação do validador de email vem em inglês: diz-se o essencial.
  if (campo === 'email') return MENSAGEM_EMAIL_INVALIDO;
  const texto = typeof primeiro.msg === 'string' ? primeiro.msg.replace(/^Value error,\s*/i, '') : '';
  return texto || null;
}

/** O texto para o toast quando um pedido falha: o `detail` do servidor se for
 *  texto, a frase da validação se for uma lista, senão `porOmissao`. */
export function mensagemDoErro(error, porOmissao = 'Ocorreu um erro. Tente novamente.') {
  const detalhe = error?.response?.data?.detail;
  if (typeof detalhe === 'string' && detalhe) return detalhe;
  return fraseDaValidacao(detalhe) || porOmissao;
}

/** O interceptor de resposta do axios por omissão (registado no AuthContext): o
 *  `detail` em lista passa a texto, para os `toast.error(error.response?.data?.detail
 *  || …)` do portal, e a lista original fica em `detalhes`. Um `detail` em texto,
 *  ou um erro sem resposta, seguem intactos. A promessa continua rejeitada. */
export function detalheEmTexto(error) {
  const dados = error?.response?.data;
  if (dados && Array.isArray(dados.detail)) {
    dados.detalhes = dados.detail;
    // Sem frase que se saiba ler, fica sem `detail`: cada ecrã usa a sua de sempre.
    dados.detail = fraseDaValidacao(dados.detail) || undefined;
  }
  return Promise.reject(error);
}
