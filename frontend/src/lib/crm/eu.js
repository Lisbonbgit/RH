// O estado de membro do CRM da sessão: `GET /api/crm/eu` → `{membro, perfil,
// admin_master}`, pedido **uma vez por token** e partilhado por todos os
// componentes que o querem (os layouts e a guarda, por `useEstadoCrm`).
//
// Funções puras (o pedido entra por parâmetro): sem React, sem axios.
//
// **Uma falha não é um "não".** Se o pedido falhar, o CRM fica escondido
// (`EU_NINGUEM`), mas a falha não se guarda: o pedido seguinte volta a tentar.
// Um "não é membro" de verdade (resposta do servidor) guarda-se para o token,
// como um "sim". É por isso que o backend responde 500, e nunca
// `membro: false`, quando a base falha (`test_eu.py`). E o estado que os
// componentes recebem diz `falhou: true`, para a guarda das rotas mostrar
// "Tentar de novo" em vez de recambiar um membro (`decisaoGuardaCrm`).

// = `crm/dominio/membros.py::PERFIS`, pela mesma ordem.
export const PERFIS_CRM = Object.freeze(['admin', 'utilizador', 'motorista']);

// A resposta do `/eu` a quem não é membro; também o que se assume sem sessão,
// enquanto se espera, ou depois de uma falha.
export const EU_NINGUEM = Object.freeze({ membro: false, perfil: null, admin_master: false });

export const ESTADO_A_CARREGAR = Object.freeze({ carregando: true, eu: EU_NINGUEM, falhou: false });
export const ESTADO_FALHOU = Object.freeze({ carregando: false, eu: EU_NINGUEM, falhou: true });

const tokenValido = (token) => typeof token === 'string' && token !== '';

// Uma resposta com a forma do `/eu`. Um 200 sem ela (o `index.html` de um
// proxy, um corpo vazio) é uma falha, não um "não é membro".
const temFormaDeEu = (dados) => typeof dados?.membro === 'boolean';

/**
 * O `eu` só com as três chaves, congelado. Como no backend (`estado_crm`), um
 * perfil fora da lista não é membro: `membro` só com `true` e com um perfil
 * conhecido, senão `EU_NINGUEM`. `admin_master` só com `true` e num admin.
 */
export function normalizarEu(dados) {
  if (dados?.membro !== true || !PERFIS_CRM.includes(dados.perfil)) {
    return EU_NINGUEM;
  }
  return Object.freeze({
    membro: true,
    perfil: dados.perfil,
    admin_master: dados.admin_master === true && dados.perfil === 'admin',
  });
}

/**
 * A cache do `/eu` por token. `obter(token)` faz o pedido (devolve os `data`
 * ou uma promessa deles); o token vai como argumento — o `obterEu` do
 * `api.js` não precisa dele, porque lê o mesmo token do axios global, posto
 * pelo `AuthContext` antes de o estado mudar.
 *
 * Guarda só o token atual: outro token (outra sessão) substitui-o, e a
 * resposta atrasada do antigo não fica como a do novo. Sem token, esquece o
 * que tinha (terminar a sessão) e devolve `EU_NINGUEM` sem pedido.
 *
 * Devolve:
 *   - `obter(token)` → promessa do `eu` normalizado; **nunca rejeita** (uma
 *     falha dá `EU_NINGUEM` e não fica guardada);
 *   - `memorizado(token)` → o `eu` guardado para este token (sempre a mesma
 *     referência), `EU_NINGUEM` sem token, ou `undefined` se ainda não há
 *     resposta (ou se a última falhou);
 *   - `subscrever(ouvinte)` → avisa quando chega a resposta do token atual
 *     (já guardada quando o ouvinte corre); devolve a função para deixar de
 *     ouvir (forma do `useSyncExternalStore`). Trocar de token ou terminar a
 *     sessão não avisa: os componentes já se redesenham com o token novo.
 */
export function criarCacheEu(obter) {
  // {token, eu (undefined até haver resposta), promessa (o pedido a correr ou já
  // respondido; null depois de uma falha, para o seguinte voltar a tentar)}.
  let entrada = null;
  const ouvintes = new Set();

  const avisar = () => ouvintes.forEach((ouvinte) => ouvinte());

  function memorizado(token) {
    if (!tokenValido(token)) return EU_NINGUEM;
    return entrada !== null && entrada.token === token ? entrada.eu : undefined;
  }

  // Cada pedido escreve só na SUA entrada. Se entretanto o token mudou, a
  // entrada já não é a da cache: a resposta atrasada vai para quem a pediu e
  // não fica como a do token novo (nem avisa ninguém).
  function pedir(token) {
    const atual = { token, eu: undefined, promessa: null };
    entrada = atual;

    let resposta;
    try {
      resposta = Promise.resolve(obter(token));
    } catch (e) {
      resposta = Promise.reject(e);
    }

    // Uma falha não se guarda: larga a promessa, e o pedido seguinte volta a tentar.
    const falhou = () => {
      atual.promessa = null;
      return EU_NINGUEM;
    };
    atual.promessa = resposta.then((dados) => {
      if (!temFormaDeEu(dados)) return falhou();
      atual.eu = normalizarEu(dados);
      if (entrada === atual) avisar();
      return atual.eu;
    }, falhou);
    return atual.promessa;
  }

  function obterEu(token) {
    if (!tokenValido(token)) {
      entrada = null;
      return Promise.resolve(EU_NINGUEM);
    }
    // O mesmo token: a resposta já guardada, ou o pedido que ainda corre.
    if (entrada !== null && entrada.token === token && entrada.promessa !== null) return entrada.promessa;
    return pedir(token);
  }

  function subscrever(ouvinte) {
    ouvintes.add(ouvinte);
    return () => {
      ouvintes.delete(ouvinte);
    };
  }

  return { obter: obterEu, memorizado, subscrever };
}

/**
 * O `{carregando, eu, falhou}` que um componente mostra, a partir do que a
 * cache tem guardado e de o pedido deste componente já ter terminado:
 *   - resposta guardada → mostra-a (também um "não é membro": não é falha);
 *   - sem resposta e o pedido ainda a correr → a carregar (a guarda espera em
 *     vez de recambiar — também depois de uma falha de outro componente, em
 *     que o pedido deste é a nova tentativa);
 *   - sem resposta e o pedido já terminou → falhou: CRM escondido nos menus,
 *     e a guarda mostra o aviso com "Tentar de novo" (nunca recambia).
 */
export function estadoEu(memorizado, jaRespondeu) {
  if (memorizado !== undefined) return { carregando: false, eu: memorizado, falhou: false };
  return jaRespondeu ? ESTADO_FALHOU : ESTADO_A_CARREGAR;
}
