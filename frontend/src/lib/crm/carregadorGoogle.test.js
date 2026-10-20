/**
 * O CARREGADOR DO GOOGLE MAPS — um só `<script>`, só nas páginas do CRM.
 *
 * Porta legível do "inline bootstrap loader" oficial da Google (adenda §6.1;
 * plano G4), provada com uma janela e um documento falsos: nada aqui chega à
 * rede. O que importa:
 *   - `prepararGoogleMaps` não toca no documento; é o primeiro `importar` que
 *     mete **um** `<script>` em `documento.head`, com a chave, `v=weekly`,
 *     `language=pt-PT`, `region=PT`, as bibliotecas e
 *     `callback=google.maps.__ib__` (`loading=async` pode estar ou não);
 *   - a promessa só resolve quando a Google instala o `importLibrary`
 *     verdadeiro e chama o `__ib__`; a partir daí tudo delega nele;
 *   - dois `importar` antes de carregar, ou um segundo `prepararGoogleMaps` na
 *     mesma janela, não metem outro script (a Google avisa "only loaded once");
 *   - `onerror` → `Error('O Google Maps não carregou.')` e o `importar`
 *     seguinte tenta de novo com um script novo;
 *   - o `nonce` de um `script[nonce]` existente copia-se;
 *   - a chave só aparece no `src` do script: o módulo não regista nada;
 *   - a Google que recusa a chave depois de carregar (referrer não autorizado,
 *     chave inválida: o script carrega na mesma e chama o `gm_authFailure` da
 *     janela) avisa quem está à escuta (`aoFalharAutenticacao`), uma vez, e
 *     quem chega depois logo; um `gm_authFailure` que já lá estava continua a
 *     ser chamado (revisão do mapa Google, MAPA-G-1 / G-ENG-1).
 */
import fs from 'fs';
import path from 'path';
import { prepararGoogleMaps, MENSAGEM_GOOGLE_NAO_CARREGOU } from './carregadorGoogle';

const CHAVE = 'chave-teste';
const URL_API = 'https://maps.googleapis.com/maps/api/js';
const ERRO = 'O Google Maps não carregou.';

// Deixa correr as microtarefas (o script monta-se numa, como no bootstrap oficial).
const esperar = () => new Promise((resolver) => setTimeout(resolver, 0));

const janelaFalsa = () => ({ google: undefined });

// Um documento mínimo: `createElement('script')` dá um objeto com `src`, `onerror` e `nonce`;
// `head.append` guarda; `querySelector('script[nonce]')` devolve o script existente, se houver.
function documentoFalso({ nonce } = {}) {
  const criados = [];
  const head = {
    filhos: [],
    append(...nos) {
      this.filhos.push(...nos);
    },
  };
  return {
    head,
    criados,
    createElement(tag) {
      const no = { tagName: String(tag).toUpperCase(), src: '', onerror: null, nonce: undefined };
      criados.push(no);
      return no;
    },
    querySelector(seletor) {
      if (seletor === 'script[nonce]' && nonce !== undefined) return { nonce };
      return null;
    },
  };
}

const scripts = (documento) => documento.head.filhos.filter((no) => no.tagName === 'SCRIPT');
const parametros = (script) => new URL(script.src).searchParams;

// O que o script da Google faz ao chegar: instala o `importLibrary` verdadeiro e chama o `__ib__`.
function carregarScript(janela, importLibrary = jest.fn(async (nome) => ({ nome }))) {
  janela.google.maps.importLibrary = importLibrary;
  janela.google.maps.__ib__();
  return importLibrary;
}

// Regista o estado de uma promessa sem a esperar.
function observar(promessa) {
  const estado = { valor: 'pendente' };
  promessa.then(
    () => {
      estado.valor = 'resolvida';
    },
    () => {
      estado.valor = 'rejeitada';
    },
  );
  return estado;
}

function preparar(opcoes = {}) {
  const janela = opcoes.janela ?? janelaFalsa();
  const documento = documentoFalso(opcoes.documento);
  const { importar, aoFalharAutenticacao } = prepararGoogleMaps({ janela, documento, chave: CHAVE, ...opcoes.preparacao });
  return { janela, documento, importar, aoFalharAutenticacao };
}

// O script chega e a Google chama o __ib__ (o mapa já se pode criar).
async function carregar(preparado) {
  const promessa = preparado.importar('maps');
  await esperar();
  carregarScript(preparado.janela);
  await promessa;
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('prepararGoogleMaps', () => {
  test('não toca no documento; devolve {importar}', () => {
    const { documento, importar } = preparar();
    expect(typeof importar).toBe('function');
    expect(documento.criados).toEqual([]);
    expect(documento.head.filhos).toEqual([]);
  });

  test('deixa google.maps.importLibrary pronto na janela, como o bootstrap oficial', () => {
    const { janela, documento } = preparar();
    expect(typeof janela.google.maps.importLibrary).toBe('function');
    expect(documento.head.filhos).toEqual([]);
  });
});

describe('o primeiro importar mete um só script com o URL certo', () => {
  test('importar("maps") → um <script> em documento.head', async () => {
    const { documento, importar } = preparar();
    importar('maps');
    await esperar();
    expect(scripts(documento)).toHaveLength(1);
    expect(documento.criados).toHaveLength(1);
    const [script] = scripts(documento);
    expect(script.src.startsWith(`${URL_API}?`)).toBe(true);
    const url = new URL(script.src);
    expect(`${url.origin}${url.pathname}`).toBe(URL_API);
  });

  test('os parâmetros exatos: key, v=weekly, language=pt-PT, region=PT, libraries=maps, callback=google.maps.__ib__', async () => {
    const { documento, importar } = preparar();
    importar('maps');
    await esperar();
    const p = parametros(scripts(documento)[0]);
    expect(p.get('key')).toBe(CHAVE);
    expect(p.get('v')).toBe('weekly');
    expect(p.get('language')).toBe('pt-PT');
    expect(p.get('region')).toBe('PT');
    expect(p.get('libraries')).toBe('maps');
    expect(p.get('callback')).toBe('google.maps.__ib__');
  });

  test('nenhum parâmetro a mais; loading, se estiver, é async', async () => {
    const { documento, importar } = preparar();
    importar('maps');
    await esperar();
    const p = parametros(scripts(documento)[0]);
    const nomes = [...p.keys()].sort();
    expect(new Set(nomes).size).toBe(nomes.length);
    for (const nome of nomes) {
      expect(['callback', 'key', 'language', 'libraries', 'loading', 'region', 'v']).toContain(nome);
    }
    // Sem `loading` (null) ou `loading=async`; nada mais (sem `expect` condicional).
    expect([null, 'async']).toContain(p.get('loading'));
  });

  test('as bibliotecas pedidas no mesmo instante vão juntas no mesmo script', async () => {
    const { documento, importar } = preparar();
    importar('maps');
    importar('marker');
    await esperar();
    expect(scripts(documento)).toHaveLength(1);
    expect(parametros(scripts(documento)[0]).get('libraries')).toBe('maps,marker');
  });

  test('versao, idioma e regiao são opções', async () => {
    const { documento, importar } = preparar({ preparacao: { versao: 'quarterly', idioma: 'en', regiao: 'ES' } });
    importar('maps');
    await esperar();
    const p = parametros(scripts(documento)[0]);
    expect(p.get('v')).toBe('quarterly');
    expect(p.get('language')).toBe('en');
    expect(p.get('region')).toBe('ES');
    expect(p.get('key')).toBe(CHAVE);
  });
});

describe('a promessa resolve só quando a Google chama o __ib__', () => {
  test('fica pendente até o script instalar o importLibrary e chamar o __ib__', async () => {
    const { janela, importar } = preparar();
    const estado = observar(importar('maps'));
    await esperar();
    expect(estado.valor).toBe('pendente');
    carregarScript(janela);
    await esperar();
    expect(estado.valor).toBe('resolvida');
  });

  test('resolve com o que o importLibrary verdadeiro devolve', async () => {
    const { janela, importar } = preparar();
    const promessa = importar('maps');
    await esperar();
    const importLibrary = carregarScript(janela);
    await expect(promessa).resolves.toEqual({ nome: 'maps' });
    expect(importLibrary).toHaveBeenCalledTimes(1);
    expect(importLibrary).toHaveBeenCalledWith('maps');
  });

  test('depois de carregar, importar("marker") chama o importLibrary verdadeiro e não mete outro script', async () => {
    const { janela, documento, importar } = preparar();
    const primeira = importar('maps');
    await esperar();
    const importLibrary = carregarScript(janela);
    await primeira;
    await expect(importar('marker')).resolves.toEqual({ nome: 'marker' });
    expect(importLibrary).toHaveBeenLastCalledWith('marker');
    expect(scripts(documento)).toHaveLength(1);
  });

  test('um __ib__ sem importLibrary verdadeiro rejeita em vez de ficar a rodar', async () => {
    const { janela, importar } = preparar();
    const promessa = importar('maps');
    await esperar();
    janela.google.maps.__ib__();
    await expect(promessa).rejects.toThrow(ERRO);
  });
});

describe('um só script por janela', () => {
  test('importar("maps") duas vezes antes de carregar → um só script; as duas resolvem', async () => {
    const { janela, documento, importar } = preparar();
    const a = importar('maps');
    await esperar();
    const b = importar('maps');
    await esperar();
    expect(scripts(documento)).toHaveLength(1);
    expect(documento.criados).toHaveLength(1);
    carregarScript(janela);
    await expect(a).resolves.toEqual({ nome: 'maps' });
    await expect(b).resolves.toEqual({ nome: 'maps' });
  });

  test('um segundo prepararGoogleMaps na mesma janela não mete outro script (nem com outra chave)', async () => {
    const janela = janelaFalsa();
    const documento = documentoFalso();
    const primeiro = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    const segundo = prepararGoogleMaps({ janela, documento, chave: 'outra-chave' });
    const a = primeiro.importar('maps');
    const b = segundo.importar('marker');
    await esperar();
    expect(scripts(documento)).toHaveLength(1);
    const p = parametros(scripts(documento)[0]);
    expect(p.get('key')).toBe(CHAVE);
    expect(scripts(documento)[0].src).not.toContain('outra-chave');
    carregarScript(janela);
    await expect(a).resolves.toEqual({ nome: 'maps' });
    await expect(b).resolves.toEqual({ nome: 'marker' });
  });

  test('um segundo prepararGoogleMaps depois de a Google ter carregado delega no importLibrary verdadeiro', async () => {
    const janela = janelaFalsa();
    const documento = documentoFalso();
    const primeiro = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    const promessa = primeiro.importar('maps');
    await esperar();
    const importLibrary = carregarScript(janela);
    await promessa;
    const segundo = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    await expect(segundo.importar('places')).resolves.toEqual({ nome: 'places' });
    expect(importLibrary).toHaveBeenLastCalledWith('places');
    expect(scripts(documento)).toHaveLength(1);
    expect(janela.google.maps.importLibrary).toBe(importLibrary);
  });
});

describe('quando o script não carrega', () => {
  test('onerror → rejeita com Error("O Google Maps não carregou.")', async () => {
    const { documento, importar } = preparar();
    const promessa = importar('maps');
    await esperar();
    const [script] = scripts(documento);
    expect(typeof script.onerror).toBe('function');
    script.onerror(new Error('rede'));
    await expect(promessa).rejects.toThrow(Error);
    await expect(promessa).rejects.toThrow(ERRO);
    expect(MENSAGEM_GOOGLE_NAO_CARREGOU).toBe(ERRO);
  });

  test('um importar seguinte tenta de novo com um script novo, como o bootstrap oficial', async () => {
    const { janela, documento, importar } = preparar();
    const falhada = importar('maps');
    await esperar();
    const [primeiro] = scripts(documento);
    primeiro.onerror(new Error('rede'));
    await expect(falhada).rejects.toThrow(ERRO);

    const nova = importar('maps');
    await esperar();
    expect(scripts(documento)).toHaveLength(2);
    const segundo = scripts(documento)[1];
    expect(segundo).not.toBe(primeiro);
    expect(parametros(segundo).get('key')).toBe(CHAVE);
    expect(parametros(segundo).get('callback')).toBe('google.maps.__ib__');
    carregarScript(janela);
    await expect(nova).resolves.toEqual({ nome: 'maps' });
  });

  test('sem chave não se pede nada à Google: importar rejeita e o documento fica intocado', async () => {
    for (const chave of ['', '   ', undefined, null]) {
      const janela = janelaFalsa();
      const documento = documentoFalso();
      const { importar } = prepararGoogleMaps({ janela, documento, chave });
      await expect(importar('maps')).rejects.toThrow(ERRO);
      await esperar();
      expect(documento.criados).toEqual([]);
      expect(documento.head.filhos).toEqual([]);
    }
  });
});

describe('o nonce', () => {
  test('copia-se de um script[nonce] existente', async () => {
    const { documento, importar } = preparar({ documento: { nonce: 'n0nce-da-pagina' } });
    importar('maps');
    await esperar();
    expect(scripts(documento)[0].nonce).toBe('n0nce-da-pagina');
  });

  test('sem script[nonce] na página fica vazio', async () => {
    const { documento, importar } = preparar();
    importar('maps');
    await esperar();
    expect(scripts(documento)[0].nonce).toBe('');
  });
});

describe('a chave nunca aparece noutro sítio', () => {
  test('o módulo não regista nada na consola, em nenhum caminho', async () => {
    const espias = ['log', 'info', 'warn', 'error', 'debug'].map((metodo) =>
      jest.spyOn(console, metodo).mockImplementation(() => {}),
    );
    const janela = janelaFalsa();
    const documento = documentoFalso();
    const primeiro = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    prepararGoogleMaps({ janela, documento, chave: 'outra-chave' });
    const falhada = primeiro.importar('maps');
    await esperar();
    scripts(documento)[0].onerror(new Error('rede'));
    await expect(falhada).rejects.toThrow(ERRO);
    const nova = primeiro.importar('maps');
    await esperar();
    carregarScript(janela);
    await nova;
    await primeiro.importar('marker');
    primeiro.aoFalharAutenticacao(() => {});
    janela.gm_authFailure();
    for (const espia of espias) expect(espia).not.toHaveBeenCalled();
  });

  test('a chave só está no src do script: nem na janela nem noutra propriedade', async () => {
    const { janela, documento, importar } = preparar();
    const promessa = importar('maps');
    await esperar();
    carregarScript(janela);
    await promessa;
    expect(JSON.stringify(janela)).not.toContain(CHAVE);
    for (const script of documento.criados) {
      const comChave = Object.entries(script)
        .filter(([nome, valor]) => nome !== 'src' && String(valor).includes(CHAVE))
        .map(([nome]) => nome);
      expect(comChave).toEqual([]);
      expect(script.src).toContain(`key=${CHAVE}`);
    }
  });

  test('o código do módulo não tem console nenhum', () => {
    const fonte = fs.readFileSync(path.join(__dirname, 'carregadorGoogle.js'), 'utf8');
    expect(fonte).not.toMatch(/console\s*\./);
  });
});

describe('a Google recusa a chave depois de carregar (gm_authFailure)', () => {
  // Com um referrer que a chave não autoriza, uma chave inválida ou uma API desligada, o script carrega na
  // mesma (o `importar` resolve e o mapa cria-se) e a Google só avisa depois, pelo `gm_authFailure` da janela.
  test('prepararGoogleMaps devolve também aoFalharAutenticacao; nada é avisado antes da falha', async () => {
    const preparado = preparar();
    expect(typeof preparado.aoFalharAutenticacao).toBe('function');
    const aviso = jest.fn();
    const desligar = preparado.aoFalharAutenticacao(aviso);
    expect(typeof desligar).toBe('function');
    await carregar(preparado);
    expect(typeof preparado.janela.gm_authFailure).toBe('function');
    expect(aviso).not.toHaveBeenCalled();
  });

  test('o gm_authFailure depois do __ib__ avisa quem está à escuta, uma só vez (sem argumentos)', async () => {
    const preparado = preparar();
    const um = jest.fn();
    const outro = jest.fn();
    preparado.aoFalharAutenticacao(um);
    preparado.aoFalharAutenticacao(outro);
    await carregar(preparado);
    preparado.janela.gm_authFailure();
    expect(um).toHaveBeenCalledTimes(1);
    expect(um.mock.calls[0]).toEqual([]);
    expect(outro).toHaveBeenCalledTimes(1);
    // A Google pode voltar a chamá-lo (outro mapa na mesma janela): ninguém é avisado duas vezes.
    preparado.janela.gm_authFailure();
    expect(um).toHaveBeenCalledTimes(1);
    expect(outro).toHaveBeenCalledTimes(1);
  });

  test('quem chega depois da falha é avisado numa microtarefa (a janela continua recusada), uma vez', async () => {
    const preparado = preparar();
    await carregar(preparado);
    preparado.janela.gm_authFailure();
    const tarde = jest.fn();
    const desligar = preparado.aoFalharAutenticacao(tarde);
    expect(typeof desligar).toBe('function');
    expect(tarde).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(tarde).toHaveBeenCalledTimes(1);
    expect(tarde.mock.calls[0]).toEqual([]);
    desligar();
    preparado.janela.gm_authFailure();
    await esperar();
    expect(tarde).toHaveBeenCalledTimes(1);
    // Um prepararGoogleMaps novo na mesma janela (outra página do CRM) também sabe.
    const outraPagina = prepararGoogleMaps({ janela: preparado.janela, documento: preparado.documento, chave: CHAVE });
    const aviso = jest.fn();
    outraPagina.aoFalharAutenticacao(aviso);
    await esperar();
    expect(aviso).toHaveBeenCalledTimes(1);
  });

  test('quem chega depois da falha e desliga logo (a montagem que o StrictMode desfaz) não é avisado', async () => {
    const preparado = preparar();
    await carregar(preparado);
    preparado.janela.gm_authFailure();
    const desfeita = jest.fn();
    const ficou = jest.fn();
    preparado.aoFalharAutenticacao(desfeita)();
    preparado.aoFalharAutenticacao(ficou);
    await esperar();
    expect(desfeita).not.toHaveBeenCalled();
    expect(ficou).toHaveBeenCalledTimes(1);
  });

  test('desligar: quem saiu (a página já desmontada) não é avisado', async () => {
    const preparado = preparar();
    const saiu = jest.fn();
    const ficou = jest.fn();
    const desligar = preparado.aoFalharAutenticacao(saiu);
    preparado.aoFalharAutenticacao(ficou);
    desligar();
    desligar();
    await carregar(preparado);
    preparado.janela.gm_authFailure();
    expect(saiu).not.toHaveBeenCalled();
    expect(ficou).toHaveBeenCalledTimes(1);
  });

  test('um gm_authFailure que já estava na janela continua a ser chamado, com os mesmos argumentos', async () => {
    const janela = janelaFalsa();
    const anterior = jest.fn();
    janela.gm_authFailure = anterior;
    const preparado = preparar({ janela });
    const aviso = jest.fn();
    preparado.aoFalharAutenticacao(aviso);
    await carregar(preparado);
    janela.gm_authFailure('x');
    expect(anterior).toHaveBeenCalledTimes(1);
    expect(anterior).toHaveBeenCalledWith('x');
    expect(aviso).toHaveBeenCalledTimes(1);
  });

  test('dois prepararGoogleMaps na mesma janela: o gm_authFailure instala-se uma vez e cada um é avisado uma vez', async () => {
    const janela = janelaFalsa();
    const anterior = jest.fn();
    janela.gm_authFailure = anterior;
    const documento = documentoFalso();
    const primeiro = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    const instalado = janela.gm_authFailure;
    const segundo = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    expect(janela.gm_authFailure).toBe(instalado);
    const a = jest.fn();
    const b = jest.fn();
    primeiro.aoFalharAutenticacao(a);
    segundo.aoFalharAutenticacao(b);
    const promessa = primeiro.importar('maps');
    await esperar();
    carregarScript(janela);
    await promessa;
    // Já carregado: um terceiro só delega, e também não reinstala nada.
    prepararGoogleMaps({ janela, documento, chave: CHAVE });
    expect(janela.gm_authFailure).toBe(instalado);
    janela.gm_authFailure();
    expect(anterior).toHaveBeenCalledTimes(1);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  test('a Google já carregada antes do CRM (importLibrary verdadeiro): também se vigia a autenticação', () => {
    const importLibrary = jest.fn(async (nome) => ({ nome }));
    const janela = { google: { maps: { importLibrary } } };
    const documento = documentoFalso();
    const { aoFalharAutenticacao } = prepararGoogleMaps({ janela, documento, chave: CHAVE });
    const aviso = jest.fn();
    aoFalharAutenticacao(aviso);
    janela.gm_authFailure();
    expect(aviso).toHaveBeenCalledTimes(1);
    expect(janela.google.maps.importLibrary).toBe(importLibrary);
  });

  test('sem chave nada se pede: a janela fica sem gm_authFailure e o aviso nunca chega', () => {
    for (const chave of ['', '   ', undefined, null]) {
      const janela = janelaFalsa();
      const { aoFalharAutenticacao } = prepararGoogleMaps({ janela, documento: documentoFalso(), chave });
      const aviso = jest.fn();
      const desligar = aoFalharAutenticacao(aviso);
      expect(typeof desligar).toBe('function');
      desligar();
      expect(janela.gm_authFailure).toBeUndefined();
      expect(aviso).not.toHaveBeenCalled();
    }
  });

  test('um aviso que não seja uma função não se regista (nem rebenta na falha)', async () => {
    const preparado = preparar();
    for (const invalido of [undefined, null, 'x', {}]) {
      expect(typeof preparado.aoFalharAutenticacao(invalido)).toBe('function');
    }
    await carregar(preparado);
    expect(() => preparado.janela.gm_authFailure()).not.toThrow();
    expect(typeof preparado.aoFalharAutenticacao('x')).toBe('function');
  });

  test('a chave não fica em lado nenhum do aviso (nem na janela, nem no que se entrega a quem ouve)', async () => {
    const preparado = preparar();
    const aviso = jest.fn();
    preparado.aoFalharAutenticacao(aviso);
    await carregar(preparado);
    preparado.janela.gm_authFailure();
    expect(JSON.stringify(preparado.janela)).not.toContain(CHAVE);
    expect(JSON.stringify(aviso.mock.calls)).not.toContain(CHAVE);
    expect(String(preparado.janela.gm_authFailure)).not.toContain(CHAVE);
  });
});
