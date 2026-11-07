/**
 * @jest-environment node
 */
// OS CAMPOS DE EMAIL DA ENTRADA E DO «ESQUECI A PALAVRA-PASSE» — o teclado do
// telemóvel não lhes mexe.
//
// O caso que o pediu: o email do Carlos estava gravado «Carlos.Silva@…» e ele
// escrevia-o em minúsculas; repunha a palavra-passe e o login dava 401. O
// servidor já não diferencia maiúsculas (backend/tests/test_login_maiusculas.py);
// isto é o resto: o teclado não põe a primeira letra em maiúscula nem «corrige»
// o email, nos três ecrãs onde se escreve.
//
// Os ecrãs desenham-se para texto com o `renderToStaticMarkup` (sem DOM, como em
// lib/crm/privacidade.test.js) e lêem-se os atributos do <input> do email.
import React from 'react';
// Com outro nome, para o ESLint do testing-library não o tomar por um `render` de ecrã.
import { renderToStaticMarkup as marcacaoEstatica } from 'react-dom/server';
import LoginPage from './LoginPage';
import ForgotPasswordPage from './ForgotPasswordPage';
import ResetPasswordPage from './ResetPasswordPage';

// Os componentes de components/ui importam por `@/…`, um alias do webpack que o
// Jest não conhece: aponta-se para os mesmos ficheiros.
jest.mock('@/lib/utils', () => jest.requireActual('../lib/utils'), { virtual: true });
jest.mock('@/components/ui/button', () => jest.requireActual('../components/ui/button'), { virtual: true });
// O react-router-dom 7 só se carrega pelos `exports` do package.json, que o Jest
// do CRA não lê; aqui só se desenha o ecrã, não se navega.
jest.mock('react-router-dom', () => {
  const React = jest.requireActual('react');
  return {
    Link: ({ to, children, ...resto }) => React.createElement('a', { href: to, ...resto }, children),
    useNavigate: () => () => {},
    useLocation: () => ({ state: null }),
    useSearchParams: () => [new URLSearchParams(), () => {}],
  };
});
// O ecrã de entrada só precisa de saber que ainda ninguém entrou.
jest.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ login: async () => ({}), isAuthenticated: false, user: null }),
}));

// Os atributos do <input id="…">, com os nomes em minúsculas (o HTML não as
// diferencia, e o React escreve uns em camelCase e outros não).
const atributosDoCampo = (Ecra, id) => {
  const html = marcacaoEstatica(<Ecra />);
  const etiqueta = html.match(new RegExp(`<input[^>]*\\sid="${id}"[^>]*>`));
  expect(etiqueta).not.toBeNull();
  const atributos = {};
  for (const [, nome, valor] of etiqueta[0].matchAll(/([\w-]+)="([^"]*)"/g)) {
    atributos[nome.toLowerCase()] = valor;
  }
  return atributos;
};

test.each([
  ['a entrada', LoginPage, 'login-email'],
  ['o «Esqueci a palavra-passe»', ForgotPasswordPage, 'email'],
  ['o ecrã do código', ResetPasswordPage, 'reset-email'],
])('%s: o teclado não põe maiúsculas nem corrige o email', (_, Ecra, id) => {
  const campo = atributosDoCampo(Ecra, id);
  expect(campo.type).toBe('email');
  expect(campo.autocapitalize).toBe('none');
  expect(campo.autocorrect).toBe('off');
  expect(campo.spellcheck).toBe('false');
});

test('a entrada continua reconhecida pelo gestor de palavras-passe', () => {
  const campo = atributosDoCampo(LoginPage, 'login-email');
  expect(campo.name).toBe('email');
  expect(campo.autocomplete).toBe('username');
});
