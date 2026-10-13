/**
 * @jest-environment node
 */
// POLÍTICA DE PRIVACIDADE — a secção do CRM (T2.31; desenho original §6.8 e §11;
// correção "T2.31 (política de privacidade)").
//
// A página (`pages/PrivacyPolicy.js`) é do portal e partilhada com o Matheus; este
// teste só confere o que o CRM lá pôs, pelo texto que a pessoa lê: a página é
// desenhada para texto com o `renderToStaticMarkup` (sem DOM, ambiente node), e
// as frases comparam-se depois de tirar as etiquetas. Assim, um espaço que falte
// à volta de um <strong> também se apanha.
//
// O que fica preso:
//   - a secção "CRM Purple House (equipa comercial)" logo antes de "Alterações",
//     e os números das secções seguidos (1, 2, 3…);
//   - o GPS só ao tocar no botão com o texto verdadeiro do seletor, uma leitura,
//     só o ponto da loja, nunca a posição da pessoa nem percursos, sem seguimento;
//   - as atribuições tal e qual as de `atribuicoes.js`, e o Leaflet (o `mapa.js`
//     tira o prefixo do Leaflet e diz que ele é creditado aqui);
//   - o §3 a falar só do registo de ponto e o §4 a nomear a Geoapify e o
//     OpenStreetMap, sem dados pessoais enviados pelo servidor;
//   - a data do topo não é anterior a esta versão.
// A redação é do dono (CRM_PORTING_GUIDE.md §14, ponto 7): se ele a mudar, este
// teste muda com ela, mas os compromissos acima ficam.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import PrivacyPolicy from '../../pages/PrivacyPolicy';
import { ATRIBUICOES } from './atribuicoes';
import { TEXTO_ESTOU_NESTA_LOJA } from './seletor';

const TITULO_CRM = 'CRM Purple House (equipa comercial)';
const DATA_DA_SECCAO_CRM = '2026-10-10';

const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
];

const ENTIDADES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'", '&#39;': "'" };

// Etiquetas de bloco → mudança de linha; as outras (strong, a…) saem sem deixar espaço, como no ecrã.
function texto(html) {
  return html
    .replace(/<\/?(?:div|section|h1|h2|p|ul|ol|li)\b[^>]*>/g, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&(?:amp|lt|gt|quot|#x27|#39);/g, (e) => ENTIDADES[e])
    .split('\n')
    .map((linha) => linha.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n');
}

function pagina() {
  const html = renderToStaticMarkup(React.createElement(PrivacyPolicy));
  const seccoes = html.split(/<section\b/).slice(1).map((pedaco) => {
    const h2 = /<h2\b[^>]*>([\s\S]*?)<\/h2>/.exec(pedaco);
    return { titulo: h2 ? texto(h2[1]) : null, texto: texto(`<section${pedaco}`) };
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

test('atribuições tal e qual as do mapa (atribuicoes.js), a origem das moradas e o Leaflet', () => {
  const crm = seccao(pagina().seccoes, TITULO_CRM).texto;
  expect(crm).toContain(ATRIBUICOES.geoapify.texto);
  expect(crm).toContain(`ou só ${ATRIBUICOES.osm.texto}`);
  expect(crm).toContain(ATRIBUICOES.pesquisa.texto);
  expect(crm).toContain('moradas sugeridas vêm da Geoapify (dados OpenStreetMap)');
  expect(crm).toContain('Leaflet');
});

test('§3: a localização do registo de ponto serve só para validar o registo', () => {
  const { seccoes, tudo } = pagina();
  const finalidades = seccao(seccoes, 'Finalidades e base legal').texto;
  expect(finalidades).toContain('No registo de ponto, a localização serve exclusivamente para validar o registo.');
  expect(tudo).not.toContain('A localização serve exclusivamente para validar o registo de ponto.');
});

test('§4: a Geoapify e o OpenStreetMap como prestadores do mapa e da morada, sem dados pessoais', () => {
  const partilha = seccao(pagina().seccoes, 'Partilha de dados').texto;
  expect(partilha).toContain('o mapa e a pesquisa de morada usam a Geoapify e o OpenStreetMap');
  expect(partilha).toContain('o servidor só envia à Geoapify o texto pesquisado e pontos do mapa, sem dados pessoais');
  expect(partilha).toContain('endereço IP');
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
