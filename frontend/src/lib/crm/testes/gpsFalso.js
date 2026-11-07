// O `navigator.geolocation` falso para os testes de "A minha localização" (só testes; fica fora do varrimento do
// seguranca.test.js, que exclui a pasta `testes/`).
//
// Como no browser, um `watchPosition` responde mais tarde e mais do que uma vez: o teste é que manda (`responder`,
// `falhar`), sempre ao seguimento ativo mais recente. Cada seguimento fica em `seguimentos`, com o `id`, as `opcoes`,
// as funções do browser (`sucesso`, `erro`) e `parado`: chamar as funções de um seguimento parado imita a resposta que
// chega atrasada. O `clearWatch` conta em `limpezas`, para se provar que cada seguimento para uma só vez. Com
// `{primeiroId}` o primeiro id é outro (o 0 é um id como os outros).
//
// O Jest do CRA corre com `resetMocks`: criar o falso dentro de cada teste.

export const coordenadas = (latitude, longitude, accuracy) => ({ coords: { latitude, longitude, accuracy } });

export function gpsFalso({ primeiroId = 1 } = {}) {
  const gps = {
    seguimentos: [],
    limpezas: [],
    leiturasUnicas: 0,
    getCurrentPosition() {
      gps.leiturasUnicas += 1;
    },
    watchPosition(sucesso, erro, opcoes) {
      const id = primeiroId + gps.seguimentos.length;
      gps.seguimentos.push({ id, sucesso, erro, opcoes, parado: false });
      return id;
    },
    clearWatch(id) {
      gps.limpezas.push(id);
      const seguimento = gps.seguimentos.find((s) => s.id === id);
      if (seguimento) seguimento.parado = true;
    },

    // Para os testes
    ativos: () => gps.seguimentos.filter((s) => !s.parado),
    responder(latitude, longitude, accuracy = 10) {
      gps.ativos().at(-1).sucesso(coordenadas(latitude, longitude, accuracy));
    },
    falhar(code) {
      gps.ativos().at(-1).erro({ code, message: 'erro do browser' });
    },
  };
  return gps;
}
