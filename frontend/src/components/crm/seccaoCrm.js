// A secção CRM do menu de gestão (`AdminLayout`), no formato das outras
// secções do array `sections`: só aparece a quem pode abrir o CRM (`visivel`,
// com o `podeVerCrm` que o `AdminLayout` calcula por `podeAbrirAreaCrm`), e
// as Definições só ao admin do CRM (`crmAdmin`, filtrado por `eAdminCrm`).
//
// Os itens saem de `ITENS_MENU_CRM` (`lib/crm/acesso.js`), os mesmos da área
// própria (`CrmLayout`), já na casa da gestão (`/admin/crm/...`): um caminho
// do CRM muda-se num só sítio e bate com as rotas de `rotasCrm.js`.
//
// A interface só esconde; é o servidor que protege (`crm/auth.py`).
import {
  Map as IconeMapa, // nunca `Map`: tapava o Map do JavaScript
  MapPinPlus,
  Settings,
} from 'lucide-react';
import { BASE_CRM_ADMIN, ITENS_MENU_CRM, rotaDoCrmNoAdmin } from '../../lib/crm/acesso';

// O ícone de cada item de `ITENS_MENU_CRM`, pela `chave` (os mesmos do `CrmLayout`).
const ICONES = { mapa: IconeMapa, 'loja-nova': MapPinPlus, definicoes: Settings };

export const seccaoCrm = Object.freeze({
  key: 'crm',
  label: 'CRM',
  home: `${BASE_CRM_ADMIN}/mapa`,
  // `/admin/crm` e o que está por baixo. O `match` do RH (o apanha-tudo do
  // `/admin`) exclui exatamente o mesmo caminho.
  match: rotaDoCrmNoAdmin,
  // Fecha na dúvida: só `podeVerCrm === true` mostra a secção.
  visivel: (ctx) => ctx?.podeVerCrm === true,
  items: Object.freeze(
    ITENS_MENU_CRM.map(({ chave, rotulo, caminho, soAdmin }) =>
      Object.freeze({ path: `${BASE_CRM_ADMIN}/${caminho}`, label: rotulo, icon: ICONES[chave], crmAdmin: soAdmin }),
    ),
  ),
});

export default seccaoCrm;
