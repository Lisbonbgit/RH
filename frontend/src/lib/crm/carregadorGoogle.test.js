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
 *   - a chave só aparece no `src` do script: o módulo não regista nada.
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
  const janela = janelaFalsa();
  const documento = documentoFalso(opcoes.documento);
  const { importar } = prepararGoogleMaps({ janela, documento, chave: CHAVE, ...opcoes.preparacao });
  return { janela, documento, importar };
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
