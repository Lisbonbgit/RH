// Estado da rede (online/offline), para os ecrãs que precisam dela (desenho
// original §6.2: adicionar uma loja exige rede). A janela e o navigator são
// recebidos por parâmetro (testável no Jest). Porta de public/assets/js/rede.js
// do CRM autónomo, tal e qual.
//
// O navigator.onLine só é fiável no "sem rede": true quer dizer que há uma
// ligação, não que o servidor responde. Por isso a API continua a dar
// 'sem_rede' quando o pedido falha (lib/crm/api.js).

export function criarEstadoRede(janela, navegador) {
  const ouvintes = new Set();

  function avisar(online) {
    // Uma cópia: um ouvinte pode cancelar-se (ou cancelar outro) durante o aviso.
    for (const ouvinte of [...ouvintes]) {
      if (ouvintes.has(ouvinte)) ouvinte(online);
    }
  }

  if (janela && typeof janela.addEventListener === 'function') {
    janela.addEventListener('online', () => avisar(true));
    janela.addEventListener('offline', () => avisar(false));
  }

  return {
    // Sem a informação (browser antigo), assume-se que há rede: o pedido dirá se não há.
    online: () => navegador?.onLine !== false,

    // aoMudar((online) => …) → função que cancela o aviso.
    aoMudar(ouvinte) {
      ouvintes.add(ouvinte);
      return () => {
        ouvintes.delete(ouvinte);
      };
    },
  };
}
