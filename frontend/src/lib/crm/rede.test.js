/**
 * O ESTADO DA REDE — online/offline, para os ecrãs que precisam dela.
 *
 * Porta de tests/js/rede.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), tal e qual, com o `node:assert` passado a
 * `expect`. A janela e o navigator são falsos e entram por parâmetro: a janela
 * é um `EventTarget` (o do jsdom do Jest, como o do browser) e o navigator só
 * precisa de `onLine`.
 *
 * Os dois últimos testes são extra: fixam as guardas do `avisar()` (a cópia
 * dos ouvintes e o `has`), que os do autónomo deixavam passar.
 *
 * No portal, o "Guardar" da loja nova fica desativado sem rede (T2.27; desenho
 * original §6.2).
 */
import { criarEstadoRede } from './rede';

// A janela é um EventTarget (como a do browser); o navigator só precisa de onLine.
const janelaFalsa = () => new EventTarget();

test('online(): segue o navigator.onLine', () => {
  const navegador = { onLine: true };
  const rede = criarEstadoRede(janelaFalsa(), navegador);
  expect(rede.online()).toBe(true);
  navegador.onLine = false;
  expect(rede.online()).toBe(false);
});

test('sem navigator.onLine (ou sem navigator) assume que há rede', () => {
  expect(criarEstadoRede(janelaFalsa(), {}).online()).toBe(true);
  expect(criarEstadoRede(janelaFalsa(), undefined).online()).toBe(true);
  expect(criarEstadoRede(undefined, undefined).online()).toBe(true);
});

test('aoMudar: avisa com false ao perder a rede e com true ao recuperá-la', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const vistos = [];
  rede.aoMudar((online) => vistos.push(online));
  janela.dispatchEvent(new Event('offline'));
  janela.dispatchEvent(new Event('online'));
  expect(vistos).toEqual([false, true]);
});

test('aoMudar devolve a função que cancela o aviso', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const vistos = [];
  const cancelar = rede.aoMudar((online) => vistos.push(online));
  cancelar();
  janela.dispatchEvent(new Event('offline'));
  expect(vistos).toEqual([]);
});

test('vários ouvintes: cada um é avisado, e cancelar um não afeta os outros', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const a = [];
  const b = [];
  const cancelarA = rede.aoMudar((online) => a.push(online));
  rede.aoMudar((online) => b.push(online));
  janela.dispatchEvent(new Event('offline'));
  cancelarA();
  janela.dispatchEvent(new Event('online'));
  expect(a).toEqual([false]);
  expect(b).toEqual([false, true]);
});

test('um ouvinte que cancela durante o aviso não impede os seguintes', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const vistos = [];
  const cancelar = rede.aoMudar(() => cancelar());
  rede.aoMudar((online) => vistos.push(online));
  janela.dispatchEvent(new Event('offline'));
  expect(vistos).toEqual([false]);
});

// --- Extra: as duas guardas do avisar() (a cópia e o `has`), que os testes do autónomo não fixam ---

test('um ouvinte cancelado por outro durante o aviso já não é avisado', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const vistos = [];
  let cancelarB = () => {};
  rede.aoMudar(() => cancelarB());
  cancelarB = rede.aoMudar((online) => vistos.push(online));
  janela.dispatchEvent(new Event('offline'));
  expect(vistos).toEqual([]);
});

test('um ouvinte acrescentado durante o aviso só é avisado da vez seguinte', () => {
  const janela = janelaFalsa();
  const rede = criarEstadoRede(janela, { onLine: true });
  const vistos = [];
  let acrescentado = false;
  rede.aoMudar(() => {
    if (acrescentado) return;
    acrescentado = true;
    rede.aoMudar((online) => vistos.push(online));
  });
  janela.dispatchEvent(new Event('offline'));
  expect(vistos).toEqual([]);
  janela.dispatchEvent(new Event('online'));
  expect(vistos).toEqual([true]);
});
