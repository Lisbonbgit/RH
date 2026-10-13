// As rotas do CRM, declaradas uma vez e montadas em duas casas (`App.js`):
//   - `/crm/*`, a área própria, com o `CrmLayout` (que já traz a guarda);
//   - `/admin/crm/*`, as mesmas páginas dentro do `AdminLayout`, com a
//     `GuardaCrm` como elemento da rota `crm`.
//
// São funções que devolvem `<Route>` (e não componentes): o `<Routes>` do
// React Router só aceita `<Route>` e fragmentos como filhos.
//
// As páginas carregam-se à parte (`React.lazy`): o que vier a pesar (o
// Leaflet, na F2) não entra no ficheiro principal do portal. Os caminhos
// batem com `ITENS_MENU_CRM` (`lib/crm/acesso.js`): `mapa`, `lojas/nova`,
// `definicoes`.
import React, { Suspense, lazy } from 'react';
import { Navigate, Route, useLocation } from 'react-router-dom';
import { Button } from '../../components/ui/button';
import { GuardaCrm, IndicadorCrm, SoAdminCrm } from '../../components/crm/GuardaCrm';
import { baseCrm } from '../../lib/crm/acesso';

const CrmMapa = lazy(() => import('./CrmMapa'));
const CrmLojaNova = lazy(() => import('./CrmLojaNova'));
const CrmLoja = lazy(() => import('./CrmLoja'));
const CrmDefinicoes = lazy(() => import('./CrmDefinicoes'));

export const MENSAGEM_PAGINA_FALHOU =
  'Não foi possível abrir esta página do CRM. Verifique a ligação e recarregue.';

// Se o ficheiro de uma página não chegar (rede em baixo, ou uma versão nova
// publicada entretanto), o React deitava abaixo o portal inteiro e ficava o
// ecrã em branco. Assim fica só esta página, com um aviso e "Recarregar".
class FalhaDaPagina extends React.Component {
  constructor(props) {
    super(props);
    this.state = { falhou: false };
  }

  static getDerivedStateFromError() {
    return { falhou: true };
  }

  componentDidCatch(erro) {
    console.error('[crm] a página não abriu:', erro);
  }

  render() {
    if (!this.state.falhou) return this.props.children;
    return (
      <div role="alert" className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
        <p className="max-w-md text-muted-foreground">{MENSAGEM_PAGINA_FALHOU}</p>
        <Button type="button" onClick={() => window.location.reload()}>
          Recarregar
        </Button>
      </div>
    );
  }
}

// A `key` dá a cada rota o seu próprio limite: a falha de uma página não fica
// presa quando se navega para outra.
function pagina(nome, Pagina) {
  return (
    <FalhaDaPagina key={nome}>
      <Suspense fallback={<IndicadorCrm texto="A abrir a página…" />}>
        <Pagina />
      </Suspense>
    </FalhaDaPagina>
  );
}

// Um caminho do CRM que não existe abre o mapa da mesma casa (como o CRM
// autónomo: "tudo o resto → mapa"), em vez de deitar a pessoa fora do CRM.
function ParaOMapaCrm() {
  const { pathname } = useLocation();
  return <Navigate to={`${baseCrm(pathname)}/mapa`} replace />;
}

/** As rotas filhas, iguais nas duas casas. */
export function filhosCrm() {
  return (
    <>
      <Route index element={<Navigate to="mapa" replace />} />
      <Route path="mapa" element={pagina('mapa', CrmMapa)} />
      <Route path="lojas/nova" element={pagina('loja-nova', CrmLojaNova)} />
      <Route path="lojas/:lojaId" element={pagina('loja', CrmLoja)} />
      <Route element={<SoAdminCrm />}>
        <Route path="definicoes" element={pagina('definicoes', CrmDefinicoes)} />
      </Route>
      <Route path="*" element={<ParaOMapaCrm />} />
    </>
  );
}

/** A secção CRM dentro do `/admin` (o `AdminLayout` desenha à volta). */
export function rotasCrmNoAdmin() {
  return (
    <Route path="crm" element={<GuardaCrm />}>
      {filhosCrm()}
    </Route>
  );
}
