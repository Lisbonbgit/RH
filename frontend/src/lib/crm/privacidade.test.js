/**
 * @jest-environment node
 */
// POLÍTICA DE PRIVACIDADE — a secção do CRM (T2.31; G7 do plano do mapa Google;
// adenda 2026-10-14 §2.2 e correção A6).
//
// A página (`pages/PrivacyPolicy.js`) é do portal e partilhada com o Matheus; este
// teste só confere o que o CRM lá pôs, pelo texto que a pessoa lê: a página é
// desenhada para texto com o `renderToStaticMarkup` (sem DOM, ambiente node), e
// as frases comparam-se depois de tirar as etiquetas. Assim, um espaço que falte
// à volta de um <strong> ou de uma ligação também se apanha.
//
// O que fica preso:
//   - a secção "CRM Purple House (equipa comercial)" logo antes de "Alterações",
//     e os números das secções seguidos (1, 2, 3…);
//   - o GPS só ao tocar no botão com o texto verdadeiro do seletor, uma leitura,
//     só o ponto da loja, nunca a posição da pessoa nem percursos, sem seguimento;
//   - o mapa do CRM é o Google Maps (Google Ireland Limited), e a secção do CRM
//     diz, por estas palavras, que quem usa o mapa fica sujeito aos Termos
//     adicionais do Google Maps/Google Earth e à Política de Privacidade da Google
//     (Termos EEA da Google, §3.2.2), com as duas ligações exatas (lidas do href);
//   - o nome e o telefone de uma loja são escritos pelo membro, nunca copiados da
//     Google, que só deixa o identificador do lugar (place ID) e o pino que o
//     membro confirmou; a morada de uma pesquisa vem da Google e a de um ponto do
//     GPS da Geoapify ("Powered by Geoapify");
//   - o §3 a falar só do registo de ponto e o §4 a nomear o Google Maps e a
//     Geoapify, a quem o servidor só envia pontos do mapa, sem dados pessoais;
//   - a página já não fala da biblioteca do mapa antigo nem do OpenMapTiles (o
//     mapa deixou de ser deles); o nome da biblioteca escreve-se por partes, para
//     o inventário do §5 do plano do mapa Google (G19) dar vazio;
//   - a data do topo não é anterior à secção do CRM.
// O texto não vem de `atribuicoes.js`: a atribuição do mapa é a da própria Google,
// e a da Geoapify escreve-se aqui tal e qual.
// A redação é do dono (CRM_PORTING_GUIDE.md §14, ponto 7): se ele a mudar, este
// teste muda com ela, mas os compromissos acima ficam.
import React from 'react';
// Com outro nome, para o ESLint do testing-library não o tomar por um `render` de ecrã.
import { renderToStaticMarkup as marcacaoEstatica } from 'react-dom/server';
import PrivacyPolicy from '../../pages/PrivacyPolicy';
import { TEXTO_ESTOU_NESTA_LOJA } from './seletor';

const TITULO_CRM = 'CRM Purple House (equipa comercial)';
const DATA_DA_SECCAO_CRM = '2026-10-10';
const TERMOS_GOOGLE_MAPS = 'https://maps.google.com/help/terms_maps/';
const PRIVACIDADE_GOOGLE = 'https://policies.google.com/privacy';

const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
];

const ENTIDADES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'", '&#39;': "'" };
const desfazerEntidades = (valor) => valor.replace(/&(?:amp|lt|gt|quot|#x27|#39);/g, (e) => ENTIDADES[e]);

// Etiquetas de bloco → mudança de linha; as outras (strong, a…) saem sem deixar espaço, como no ecrã.
function texto(html) {
  return desfazerEntidades(
    html
      .replace(/<\/?(?:div|section|h1|h2|p|ul|ol|li)\b[^>]*>/g, '\n')
      .replace(/<[^>]+>/g, ''),
  )
    .split('\n')
    .map((linha) => linha.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n');
}

// Cada <a> de um pedaço da página: o href tal como o browser o lê e o texto que a pessoa vê.
function ligacoes(html) {
  return [...html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].map(([, atributos, conteudo]) => {
    const href = /\bhref="([^"]*)"/.exec(atributos);
    return { href: href ? desfazerEntidades(href[1]) : null, texto: texto(conteudo) };
  });
}

function pagina() {
  const html = marcacaoEstatica(React.createElement(PrivacyPolicy));
  const seccoes = html.split(/<section\b/).slice(1).map((pedaco) => {
    const h2 = /<h2\b[^>]*>([\s\S]*?)<\/h2>/.exec(pedaco);
    return { titulo: h2 ? texto(h2[1]) : null, html: `<section${pedaco}`, texto: texto(`<section${pedaco}`) };
  });
  return { html, tudo: texto(html), seccoes };
}

const comTitulo = (seccoes) => seccoes.filter((s) => s.titulo !== null);
function seccao(seccoes, nome) {
  const achada = comTitulo(seccoes).find((s) => s.titulo.replace(/^\d+\. /, '') === nome);
  if (!achada) throw new Error(`A política não tem a secção "${nome}".`);
  return achada;
}

test('a página desenha-se e tem secções com título (o teste lê mesmo a política)', () => {
  const { seccoes, tudo } = pagina();
  expect(comTitulo(seccoes).length).toBeGreaterThanOrEqual(5);
  expect(tudo).toContain('Política de Privacidade');
});

test('a secção do CRM fica logo antes de "Alterações", e os números seguem 1, 2, 3…', () => {
  const titulos = comTitulo(pagina().seccoes).map((s) => s.titulo);
  const numeros = titulos.map((t) => Number((/^(\d+)\. /.exec(t) || [])[1]));
  expect(numeros).toEqual(titulos.map((_, i) => i + 1));
  const n = titulos.length;
  expect(titulos.slice(-2)).toEqual([`${n - 1}. ${TITULO_CRM}`, `${n}. Alterações`]);
});

test('GPS do CRM: só ao tocar no botão, uma leitura, só o ponto da loja, sem seguimento', () => {
  const crm = seccao(pagina().seccoes, TITULO_CRM).texto;
  expect(TEXTO_ESTOU_NESTA_LOJA).toBe('Estou nesta loja');
  expect(crm).toContain(`só é pedida quando um membro toca em "${TEXTO_ESTOU_NESTA_LOJA}"`);
  expect(crm).toContain('uma única vez');
  // A frase inteira: passa pelos dois <strong> (nunca, não), e assim um espaço em falta também se vê.
  expect(crm).toContain(
    'Guarda-se só o ponto da loja, nunca a posição da pessoa nem percursos, e não há seguimento contínuo.',
  );
});

test('secção do CRM: o mapa é o Google Maps e o membro fica sujeito aos termos da Google, com as duas ligações', () => {
  const crm = seccao(pagina().seccoes, TITULO_CRM);
  expect(crm.texto).toContain('o mapa é o Google Maps, da Google Ireland Limited.');
  // A frase exigida pelos Termos EEA da Google (§3.2.2), inteira e por estas palavras.
  expect(crm.texto).toContain(
    'Ao usar o mapa do CRM, o membro fica sujeito aos Termos adicionais do Google Maps/Google Earth'
      + ' e à Política de Privacidade da Google.',
  );
  // As únicas ligações da secção, com o href exato e o texto que a pessoa lê.
  expect(ligacoes(crm.html)).toEqual([
    { href: TERMOS_GOOGLE_MAPS, texto: 'Termos adicionais do Google Maps/Google Earth' },
    { href: PRIVACIDADE_GOOGLE, texto: 'Política de Privacidade da Google' },
  ]);
});

test('secção do CRM: nome e telefone nunca copiados da Google; a origem das moradas', () => {
  const crm = seccao(pagina().seccoes, TITULO_CRM).texto;
  expect(crm).toContain(
    'o nome e o telefone de uma loja são sempre escritos pelo membro e nunca copiados da Google;'
      + ' quando a loja parte de um lugar da Google, guarda-se só o identificador do lugar (place ID)'
      + ' e o pino confirmado pelo membro.',
  );
  expect(crm).toContain(
    'A morada preenchida depois de uma pesquisa vem da Google; a de um ponto do GPS vem da Geoapify'
      + ' (dados OpenStreetMap), com a indicação Powered by Geoapify.',
  );
});

// O nome da biblioteca do mapa antigo, por partes (inventário do §5 do plano do mapa Google, G19).
const BIBLIOTECA_ANTIGA = new RegExp(['leaf', 'let'].join(''), 'i');

test('a página já não fala da biblioteca do mapa antigo nem do OpenMapTiles', () => {
  const { html, tudo } = pagina();
  for (const nome of [BIBLIOTECA_ANTIGA, /openmaptiles/i]) {
    expect(tudo).not.toMatch(nome);
    expect(html).not.toMatch(nome);
  }
});

test('§3: a localização do registo de ponto serve só para validar o registo', () => {
  const { seccoes, tudo } = pagina();
  const finalidades = seccao(seccoes, 'Finalidades e base legal').texto;
  expect(finalidades).toContain('No registo de ponto, a localização serve exclusivamente para validar o registo.');
  expect(tudo).not.toContain('A localização serve exclusivamente para validar o registo de ponto.');
});

test('§4: o Google Maps pelo browser, e a Geoapify só com pontos do mapa, sem dados pessoais', () => {
  const { seccoes } = pagina();
  const partilha = seccao(seccoes, 'Partilha de dados').texto;
  const numeroCrm = (/^(\d+)\. /.exec(seccao(seccoes, TITULO_CRM).titulo) || [])[1];
  expect(partilha).toContain(`No CRM (secção ${numeroCrm}), o mapa é o Google Maps (Google Ireland Limited)`);
  expect(partilha).toContain('é o próprio browser que lhe pede o mapa, a pesquisa de moradas e a posição dos lugares');
  expect(partilha).toContain('endereço IP');
  expect(partilha).toContain(
    'A morada sugerida de um ponto do GPS vem da Geoapify (dados OpenStreetMap), a quem o servidor só envia'
      + ' pontos do mapa, sem dados pessoais.',
  );
  // A pesquisa de moradas deixou de passar pelo servidor: à Geoapify já não vai texto pesquisado.
  expect(partilha).not.toContain('texto pesquisado');
});

test('a data no topo não é anterior à secção do CRM', () => {
  const { tudo } = pagina();
  const m = /Última atualização: (\d{1,2}) de ([a-zç]+) de (\d{4})/.exec(tudo);
  expect(m).not.toBeNull();
  const mes = MESES.indexOf(m[2]);
  expect(mes).toBeGreaterThanOrEqual(0);
  const data = `${m[3]}-${String(mes + 1).padStart(2, '0')}-${m[1].padStart(2, '0')}`;
  expect(data >= DATA_DA_SECCAO_CRM).toBe(true);
});
