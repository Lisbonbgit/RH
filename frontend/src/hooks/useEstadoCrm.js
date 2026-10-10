// O estado de membro do CRM da sessão atual: `{carregando, eu, falhou,
// tentarDeNovo}`, com `eu` = `{membro, perfil, admin_master}` (`GET
// /api/crm/eu`, normalizado).
//
// Uma só cache para a app inteira: o `AdminLayout`, o `EmployeeLayout`, o
// `CrmLayout` e a guarda das rotas partilham o mesmo pedido, feito uma vez por
// token (o token vem do `AuthContext`). As regras estão em `lib/crm/eu.js`,
// com testes; aqui só se ligam ao React.
//
// Enquanto se espera, `eu` é `EU_NINGUEM` (o CRM fica escondido) e
// `carregando` é `true` (a guarda espera em vez de recambiar). Se o pedido
// falhar, o CRM fica escondido e `falhou` é `true` (a guarda mostra o aviso
// em vez de recambiar); `tentarDeNovo()` volta a perguntar, como o próximo
// componente que montar. Quando a resposta chega, todos os que estão montados
// a recebem.
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { obterEu } from '../lib/crm/api';
import { criarCacheEu, estadoEu } from '../lib/crm/eu';

const cacheEu = criarCacheEu(obterEu);

export function useEstadoCrm() {
  const { token } = useAuth();
  const memorizado = useSyncExternalStore(cacheEu.subscrever, () => cacheEu.memorizado(token));
  // A tentativa deste componente (sobe com `tentarDeNovo`) e a última que
  // terminou (com ou sem resposta), com o seu token. Outro token, ou uma
  // tentativa nova, voltam a "a carregar" até o pedido DESTE componente
  // terminar.
  const [tentativa, setTentativa] = useState(0);
  const [respondido, setRespondido] = useState(null);

  useEffect(() => {
    let ativo = true;
    cacheEu.obter(token).then(() => {
      if (ativo) setRespondido({ token, tentativa });
    });
    return () => {
      ativo = false;
    };
  }, [token, tentativa]);

  const tentarDeNovo = useCallback(() => setTentativa((n) => n + 1), []);
  const jaRespondeu = respondido !== null && respondido.token === token && respondido.tentativa === tentativa;
  return { ...estadoEu(memorizado, jaRespondeu), tentarDeNovo };
}

export default useEstadoCrm;
