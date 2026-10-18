// O carregador do Google Maps JavaScript API: porta legível do "inline
// bootstrap loader" oficial da Google (adenda §6.1; plano §1 "Biblioteca"),
// sem a dependência `@googlemaps/js-api-loader` (regra 6 do §0). A janela e o
// documento chegam por parâmetro: os componentes passam `window` e `document`,
// os testes passam falsos — nada daqui chega à rede no Jest.
//
//  - Só corre nas páginas do CRM (já carregadas com `React.lazy`): a Google não
//    entra no ficheiro principal do portal nem no `public/index.html`.
//  - `prepararGoogleMaps({janela, documento, chave, versao, idioma, regiao})`
//    não toca no documento: deixa `janela.google.maps.importLibrary` pronto (se
//    ainda não existir) e devolve `{importar}`. O primeiro `importar(nome)` mete
//    **um** `<script>` em `documento.head` com
//    `https://maps.googleapis.com/maps/api/js?key=…&v=weekly&language=pt-PT&region=PT&libraries=…&callback=google.maps.__ib__`.
//    A promessa resolve quando a Google instala o `importLibrary` verdadeiro e
//    chama o `__ib__`; a partir daí todos os `importar` (desta preparação ou de
//    outra na mesma janela) delegam nele.
//  - O script monta-se numa microtarefa, como no oficial (`await createElement`):
//    as bibliotecas pedidas no mesmo instante (`importar('maps'); importar('marker')`)
//    vão juntas no `libraries=` do URL, num só pedido.
//  - Um segundo `prepararGoogleMaps` na mesma janela não mete outro script. O
//    oficial escreve aqui um aviso na consola com as opções — com a chave; este
//    módulo não regista nada: a chave só aparece no `src` do script.
//  - Se o script não carregar (rede, bloqueador, quota), a promessa rejeita com
//    `Error(MENSAGEM_GOOGLE_NAO_CARREGOU)` e o `importar` seguinte tenta de novo
//    com um script novo, como no oficial. Sem chave não se pede nada à Google.
//  - O `nonce` de um `<script nonce>` existente copia-se para o script novo
//    (uma CSP futura no portal; adenda §5). `loading=async` não se põe (o
//    bootstrap oficial também não; §1 do plano).

const URL_API = 'https://maps.googleapis.com/maps/api/js?';
// O nome que a Google chama quando o script está pronto (`callback=google.maps.__ib__`).
const NOME_CALLBACK = '__ib__';

export const VERSAO_PADRAO = 'weekly';
export const IDIOMA_PADRAO = 'pt-PT';
export const REGIAO_PADRAO = 'PT';
export const MENSAGEM_GOOGLE_NAO_CARREGOU = 'O Google Maps não carregou.';

const eTextoComConteudo = (x) => typeof x === 'string' && x.trim() !== '';

const naoCarregou = () => Promise.reject(new Error(MENSAGEM_GOOGLE_NAO_CARREGOU));

// Instala em `maps` (o `janela.google.maps`) o `importLibrary` de arranque: o
// primeiro pedido mete o script; os pedidos ficam à espera do `__ib__`.
function instalarArranque({ maps, documento, chave, versao, idioma, regiao }) {
  const bibliotecas = new Set();
  let carregamento = null;

  const carregar = () => {
    if (carregamento) return carregamento;
    carregamento = new Promise((resolver, rejeitar) => {
      // Uma microtarefa: as bibliotecas pedidas no mesmo instante entram todas no URL.
      Promise.resolve().then(() => {
        const script = documento.createElement('script');
        const parametros = new URLSearchParams();
        parametros.set('key', chave);
        parametros.set('v', versao);
        parametros.set('language', idioma);
        parametros.set('region', regiao);
        parametros.set('libraries', [...bibliotecas].join(','));
        parametros.set('callback', `google.maps.${NOME_CALLBACK}`);
        script.src = URL_API + parametros;
        maps[NOME_CALLBACK] = resolver;
        script.onerror = () => {
          // Como no oficial: o próximo `importar` volta a tentar com um script novo.
          carregamento = null;
          rejeitar(new Error(MENSAGEM_GOOGLE_NAO_CARREGOU));
        };
        script.nonce = documento.querySelector('script[nonce]')?.nonce || '';
        documento.head.append(script);
      });
    });
    return carregamento;
  };

  const arranque = (nome, ...resto) => {
    bibliotecas.add(nome);
    return carregar().then(() => {
      // A Google substitui o `importLibrary` antes de chamar o `__ib__`; se não o
      // fez, não há biblioteca nenhuma para entregar (e nunca se chama a si próprio).
      if (maps.importLibrary === arranque) throw new Error(MENSAGEM_GOOGLE_NAO_CARREGOU);
      return maps.importLibrary(nome, ...resto);
    });
  };
  maps.importLibrary = arranque;
}

/**
 * Prepara o Google Maps nesta janela e devolve `{importar}`.
 *
 * `importar(nome)` → a promessa de `google.maps.importLibrary(nome)` ('maps',
 * 'marker', 'places'); a primeira chamada mete o script. Nada se pede à Google
 * antes do primeiro `importar`.
 */
export function prepararGoogleMaps({
  janela,
  documento,
  chave,
  versao = VERSAO_PADRAO,
  idioma = IDIOMA_PADRAO,
  regiao = REGIAO_PADRAO,
}) {
  const importar = (nome) => janela.google.maps.importLibrary(nome);
  // Já preparado (por nós) ou já carregado (pela Google): só se delega.
  if (typeof janela.google?.maps?.importLibrary === 'function') return { importar };
  if (!eTextoComConteudo(chave)) return { importar: naoCarregou };
  const google = janela.google || (janela.google = {});
  const maps = google.maps || (google.maps = {});
  instalarArranque({ maps, documento, chave, versao, idioma, regiao });
  return { importar };
}
