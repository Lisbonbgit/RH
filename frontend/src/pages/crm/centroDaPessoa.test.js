/**
 * "A MINHA LOCALIZAÇÃO" NAS DUAS PÁGINAS — o centro do GPS ganha à primeira vista do mapa.
 *
 * Só se vê com a página à volta: quando o mapa chega depois da primeira leitura, o efeito do botão (o filho) centra e o
 * da página, no mesmo commit, dá a primeira vista ao mapa. Por isso aqui correm o `CrmMapa` e o `CrmRota` verdadeiros,
 * com o botão, as regras e a ordem dos efeitos do React verdadeiros. Falsos só o `MapaLojas` (entrega o mapa falso
 * quando o teste manda), o GPS, a api, o planeador e os painéis, que não entram nesta conta.
 *
 * O Jest do CRA corre com `resetMocks`: os falsos das fábricas são funções simples e os `jest.fn` criam-se em cada
 * teste.
 */
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

import CrmMapa from './CrmMapa';
import CrmRota from './CrmRota';
import { ZOOM_LOJA, ZOOM_MINHA_POSICAO } from '../../lib/crm/mapa';
import { gpsFalso } from '../../lib/crm/testes/gpsFalso';

const mockEndereco = { pathname: '/crm/mapa', search: '' };
const mockNavegar = () => {};
const mockPedidos = {};
const mockMapaLojas = { aoPronto: null };
const mockPlaneador = { vista: null, aoMudarVista: null };

// O Jest do CRA não lê os `exports` do pacote: as páginas só usam estes.
jest.mock('react-router-dom', () => ({
  Link: ({ children }) => children,
  useLocation: () => ({ pathname: mockEndereco.pathname, search: mockEndereco.search, state: null }),
  useNavigate: () => mockNavegar,
  useParams: () => ({ data: '2026-11-06' }),
  useSearchParams: () => [new URLSearchParams(mockEndereco.search)],
}), { virtual: true });
// O atalho `@/` é do webpack (craco.config.js): o Jest do CRA não o conhece, e o botão do portal usa-o.
jest.mock('@/lib/utils', () => ({ cn: (...classes) => classes.filter(Boolean).join(' ') }), { virtual: true });
jest.mock('sonner', () => ({ toast: { error: () => {}, success: () => {} } }));
jest.mock('../../lib/crm/api', () => ({
  obterConfigMapa: () => mockPedidos.config(),
  listarLojas: () => mockPedidos.lojas(),
  listarRegioes: () => mockPedidos.regioes(),
}));
jest.mock('../../lib/crm/planeador', () => ({
  ...jest.requireActual('../../lib/crm/planeador'),
  criarPlaneador: ({ aoMudarVista }) => ({
    get vista() { return mockPlaneador.vista; },
    iniciar() { mockPlaneador.aoMudarVista = aoMudarVista; },
    destruir() {},
    mapaDisponivel() {},
  }),
}));
jest.mock('../../components/crm/MapaLojas', () => ({
  __esModule: true,
  default: ({ aoPronto }) => {
    mockMapaLojas.aoPronto = aoPronto;
    return null;
  },
}));

jest.mock('../../components/PageHeader', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/CartaoLoja', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/DefinicoesDoDia', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/DialogoAdicionarARota', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/FiltrosMapa', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/GuardaCrm', () => ({ IndicadorCrm: () => null }));
jest.mock('../../components/crm/ListaParagens', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/NegocioSelecionado', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/crm/ResumoRota', () => ({ __esModule: true, default: () => null, RodapeOrs: () => null }));
jest.mock('../../components/crm/SugestoesRota', () => ({
  __esModule: true, default: () => null, CartaoLojaEscolhida: () => null,
}));

const CONFIGURACAO = { google: { chave: 'chave-teste-navegador', map_id: 'map-id-teste' }, centro: { lat: 38.7369, lng: -9.1427 } };
const AQUI = [38.7223, -9.1393, 25];
const POSICAO = { lat: AQUI[0], lng: AQUI[1], precisao_m: 25 };
const LOJA = { id: 'loja-1', nome: 'Quiosque', fase: 'prospeccao', lat: 38.71, lng: -9.13 };
const OUTRA = { id: 'loja-2', nome: 'Mercearia', fase: 'prospeccao', lat: 38.75, lng: -9.16 };
const LOJAS = [LOJA, OUTRA];

let raiz;
let contentor;
let gps;

function mapaFalso() {
  return {
    mostrarMinhaPosicao: jest.fn(),
    centrarEm: jest.fn(),
    enquadrar: jest.fn(),
    enquadrarRota: jest.fn(),
    redimensionar: jest.fn(),
    focar: jest.fn(),
  };
}

// Um pedido que o teste acaba quando quer.
function adiado() {
  let acabar;
  const promessa = new Promise((resolve) => {
    acabar = resolve;
  });
  return { promessa, acabar };
}

const desenhar = async (pagina) => {
  await act(async () => raiz.render(pagina));
};
const tocar = async () => {
  await act(async () => contentor.querySelector('[data-testid="crm-mapa-minha-localizacao"]').click());
};
const responder = async () => {
  await act(async () => gps.responder(...AQUI));
};
const mapaPronto = async (mapa) => {
  await act(async () => mockMapaLojas.aoPronto(mapa));
};

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  contentor = document.createElement('div');
  document.body.appendChild(contentor);
  raiz = createRoot(contentor);
  gps = gpsFalso();
  Object.defineProperty(window.navigator, 'geolocation', { value: gps, configurable: true });
  mockMapaLojas.aoPronto = null;
  mockEndereco.search = '';
  mockPedidos.config = async () => CONFIGURACAO;
  mockPedidos.lojas = async () => LOJAS;
  mockPedidos.regioes = async () => [];
});

afterEach(async () => {
  await act(async () => raiz.unmount());
  contentor.remove();
  delete window.navigator.geolocation;
});

describe('CrmMapa', () => {
  beforeEach(() => {
    mockEndereco.pathname = '/crm/mapa';
  });

  test('sem tocar no botão, a primeira vista é a da página: as lojas', async () => {
    await desenhar(<CrmMapa />);
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.enquadrar).toHaveBeenCalledTimes(1);
    expect(mapa.centrarEm).not.toHaveBeenCalled();
    expect(gps.seguimentos).toEqual([]);
  });

  test('a leitura chega antes do mapa, com as lojas já carregadas: o centro fica, a primeira vista não o desfaz', async () => {
    await desenhar(<CrmMapa />);
    await tocar();
    await responder();
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.mostrarMinhaPosicao).toHaveBeenCalledWith(POSICAO);
    expect(mapa.centrarEm).toHaveBeenCalledTimes(1);
    expect(mapa.centrarEm).toHaveBeenCalledWith(POSICAO, ZOOM_MINHA_POSICAO);
    expect(mapa.enquadrar).not.toHaveBeenCalled();
  });

  test('as lojas chegam depois do centro: o mapa não salta da pessoa para elas', async () => {
    const lojas = adiado();
    mockPedidos.lojas = () => lojas.promessa;
    await desenhar(<CrmMapa />);
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    await tocar();
    await responder();
    expect(mapa.centrarEm).toHaveBeenCalledTimes(1);
    await act(async () => lojas.acabar(LOJAS));
    expect(mapa.enquadrar).not.toHaveBeenCalled();
    expect(mapa.centrarEm).toHaveBeenCalledTimes(1);
  });

  test('o toque é mais recente do que o `?loja=`: também ganha ao centro na loja da primeira vista', async () => {
    mockEndereco.search = `?loja=${LOJA.id}`;
    await desenhar(<CrmMapa />);
    await tocar();
    await responder();
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.centrarEm.mock.calls).toEqual([[POSICAO, ZOOM_MINHA_POSICAO]]);
  });

  test('o centro só ganha à primeira vista: depois, mudar o `?loja=` continua a centrar na loja', async () => {
    await desenhar(<CrmMapa />);
    await tocar();
    await responder();
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    mockEndereco.search = `?loja=${OUTRA.id}`;
    await desenhar(<CrmMapa />);
    expect(mapa.centrarEm).toHaveBeenLastCalledWith(OUTRA, ZOOM_LOJA);
  });

  test('com a primeira vista já feita, tocar no botão não guarda nada: mudar o `?loja=` centra na loja', async () => {
    await desenhar(<CrmMapa />);
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    await tocar();
    await responder();
    expect(mapa.enquadrar).toHaveBeenCalledTimes(1);
    expect(mapa.centrarEm).toHaveBeenCalledTimes(1);
    mockEndereco.search = `?loja=${OUTRA.id}`;
    await desenhar(<CrmMapa />);
    expect(mapa.centrarEm).toHaveBeenLastCalledWith(OUTRA, ZOOM_LOJA);
  });
});

describe('CrmRota', () => {
  const vistaDaRota = (mapaDaVista) => ({
    estado: 'rota',
    titulo: 'Rota',
    caminhoRotas: '/crm/rotas',
    configuracao: CONFIGURACAO,
    mapa: mapaDaVista,
    escolherPonto: null,
    lojaEscolhida: null,
    falhaDoMapa: null,
    textoLeitura: null,
    conflito: null,
    alerta: null,
    seccoes: {},
    sugestoes: null,
    semRede: false,
    somenteLeitura: false,
    podeAdicionar: false,
  });
  const COM_PARAGENS = { paragens: [{ id: 'p1', lat: 38.71, lng: -9.13 }], lojasForaDaRota: [] };

  beforeEach(() => {
    mockEndereco.pathname = '/crm/rotas/2026-11-06';
    mockPlaneador.vista = vistaDaRota(COM_PARAGENS);
  });

  test('sem tocar no botão, a primeira vista é a da página: a rota', async () => {
    await desenhar(<CrmRota />);
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.enquadrarRota).toHaveBeenCalledTimes(1);
    expect(mapa.centrarEm).not.toHaveBeenCalled();
  });

  test('a leitura chega antes do mapa: o centro fica, a primeira vista não o desfaz', async () => {
    await desenhar(<CrmRota />);
    await tocar();
    await responder();
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.centrarEm.mock.calls).toEqual([[POSICAO, ZOOM_MINHA_POSICAO]]);
    expect(mapa.enquadrarRota).not.toHaveBeenCalled();
    expect(mapa.enquadrar).not.toHaveBeenCalled();
  });

  test('as lojas que o dia sem paragens esperava chegam depois do centro: o mapa não salta da pessoa para elas', async () => {
    mockPlaneador.vista = vistaDaRota({ paragens: [], lojasForaDaRota: null });
    await desenhar(<CrmRota />);
    const mapa = mapaFalso();
    await mapaPronto(mapa);
    expect(mapa.enquadrar).toHaveBeenCalledTimes(1); // o centro das definições, à espera das lojas
    await tocar();
    await responder();
    await act(async () => mockPlaneador.aoMudarVista(vistaDaRota({ paragens: [], lojasForaDaRota: LOJAS })));
    expect(mapa.enquadrar).toHaveBeenCalledTimes(1);
  });
});
