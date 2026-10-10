// O estado de membro do CRM da sessão atual: `{carregando, eu}`, com `eu` =
// `{membro, perfil, admin_master}` (`GET /api/crm/eu`, normalizado).
//
// Uma só cache para a app inteira: o `AdminLayout`, o `EmployeeLayout`, o
// `CrmLayout` e a guarda das rotas partilham o mesmo pedido, feito uma vez por
// token (o token vem do `AuthContext`). As regras estão em `lib/crm/eu.js`,
// com testes; aqui só se ligam ao React.
//
// Enquanto se espera, `eu` é `EU_NINGUEM` (o CRM fica escondido) e
// `carregando` é `true` (a guarda espera em vez de recambiar). Se o pedido
// falhar, o CRM fica escondido e o próximo componente que montar volta a
// perguntar; quando a resposta chega, todos os que estão montados a recebem.
import { useEffect, useState, useSyncExternalStore } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { obterEu } from '../lib/crm/api';
import { criarCacheEu, estadoEu } from '../lib/crm/eu';

const cacheEu = criarCacheEu(obterEu);

export function useEstadoCrm() {
  const { token } = useAuth();
  const memorizado = useSyncExternalStore(cacheEu.subscrever, () => cacheEu.memorizado(token));
  // O token cujo pedido, feito por ESTE componente, já terminou (com ou sem
  // resposta). Outro token volta a "a carregar" até o seu pedido terminar.
  const [respondido, setRespondido] = useState(null);

  useEffect(() => {
    let ativo = true;
    cacheEu.obter(token).then(() => {
      if (ativo) setRespondido(token);
    });
    return () => {
      ativo = false;
    };
  }, [token]);

  return estadoEu(memorizado, respondido === token);
}

export default useEstadoCrm;
