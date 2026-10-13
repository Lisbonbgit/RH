// Decide quando trocar para os mosaicos alternativos (OSM): com 3 ou mais
// erros e mais erros do que sucessos. Troca uma só vez; depois disso os
// contadores ficam como estavam e registarErro() devolve sempre false.
// Porta de public/assets/js/mosaicos.js do CRM autónomo; quem o liga aos
// eventos do Leaflet (`tileerror`/`tileload`) é o `lib/crm/mapa.js`.

const MINIMO_ERROS = 3;

export function criarControloAlternativa() {
  let erros = 0;
  let sucessos = 0;
  let mudou = false;

  return {
    get erros() {
      return erros;
    },
    get sucessos() {
      return sucessos;
    },
    get mudou() {
      return mudou;
    },
    registarSucesso() {
      if (!mudou) sucessos += 1;
    },
    // Devolve true só no erro que deve provocar a troca.
    registarErro() {
      if (mudou) return false;
      erros += 1;
      if (erros >= MINIMO_ERROS && erros > sucessos) {
        mudou = true;
        return true;
      }
      return false;
    },
  };
}
