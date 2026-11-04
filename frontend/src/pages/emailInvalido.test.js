/**
 * @jest-environment jsdom
 */
// OS ECRÃS DE ENTRADA COM UM EMAIL QUE O BROWSER ACEITA E O SERVIDOR NÃO.
//
// O caso que o pediu (registos de produção): «carlos@gmailcom» no login. O
// <input type="email"> deixa passar, o EmailStr do servidor responde 422 com o
// `detail` em LISTA, o sonner desenhou a lista como filho React e o portal
// ficou todo branco.
//
// Aqui os ecrãs desenham-se a sério (react-dom/client + act) ao lado do Toaster
// verdadeiro do sonner, com o servidor a recusar como recusa: o toast diz a
// frase em português e o ecrã continua lá. O interceptor do AuthContext NÃO está
// ligado (o AuthContext é falso): isto prova o tratamento dos próprios ecrãs.
// Mocks locais como em camposDeEmail.test.js.
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios, { AxiosError } from 'axios';
import { Toaster } from 'sonner';
import LoginPage from './LoginPage';
import ForgotPasswordPage from './ForgotPasswordPage';
import ResetPasswordPage from './ResetPasswordPage';

jest.mock('@/lib/utils', () => jest.requireActual('../lib/utils'), { virtual: true });
jest.mock('@/components/ui/button', () => jest.requireActual('../components/ui/button'), { virtual: true });
jest.mock('react-router-dom', () => {
  const React = jest.requireActual('react');
  return {
    Link: ({ to, children, ...resto }) => React.createElement('a', { href: to, ...resto }, children),
    useNavigate: () => () => {},
    useLocation: () => ({ state: null }),
    useSearchParams: () => [new URLSearchParams(), () => {}],
  };
});
// O `jest.fn` reinicia-se antes de cada teste (resetMocks do CRA): cada um diz o que o login faz.
const mockLogin = jest.fn();
jest.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ login: mockLogin, isAuthenticated: false, user: null }),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const LISTA_EMAIL = [{
  type: 'value_error', loc: ['body', 'email'], input: 'carlos@gmailcom',
  msg: 'value is not a valid email address: The part after the @-sign is not valid. It should have a period.',
  ctx: { reason: 'The part after the @-sign is not valid. It should have a period.' },
}];
const recusa = (status, detail) => new AxiosError(
  `Request failed with status code ${status}`, 'ERR_BAD_REQUEST', {}, {},
  { status, statusText: '', data: { detail }, headers: {}, config: {} },
);

let caixa;
let raiz;
const adaptadorDeSempre = axios.defaults.adapter;
beforeEach(() => {
  caixa = document.createElement('div');
  document.body.appendChild(caixa);
  raiz = createRoot(caixa);
});
afterEach(async () => {
  axios.defaults.adapter = adaptadorDeSempre;
  await act(async () => raiz.unmount());
  caixa.remove();
});

const desenhar = async (Ecra) => {
  await act(async () => raiz.render(<><Ecra /><Toaster theme="light" /></>));
};
// Escrever num <input> controlado pelo React: o valor pelo setter nativo e o evento `input`.
const escrever = (id, valor) => {
  const campo = caixa.querySelector(`#${id}`);
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(campo, valor);
  campo.dispatchEvent(new Event('input', { bubbles: true }));
};
// Submeter o formulário do ecrã, e esperar pelo pedido recusado e pelo toast (o sonner
// desenha-o num setTimeout). Em cada um destes ecrãs só há um <form> à vista.
const submeter = async () => {
  await act(async () => {
    caixa.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await new Promise((r) => setTimeout(r, 20));
  });
};
const textoDoToast = () => [...document.querySelectorAll('[data-sonner-toast]')].map((t) => t.textContent).join(' | ');

test('a entrada: o 422 do email mostra a frase em português e o ecrã fica', async () => {
  mockLogin.mockRejectedValue(recusa(422, LISTA_EMAIL));
  await desenhar(LoginPage);
  await act(async () => {
    escrever('login-email', 'carlos@gmailcom');
    escrever('login-password', 'segredo123');
  });
  await submeter();
  expect(mockLogin).toHaveBeenCalledWith('carlos@gmailcom', 'segredo123');
  expect(textoDoToast()).toContain('Email inválido. Verifique como está escrito.');
  expect(caixa.querySelector('#login-email')).not.toBeNull();
  expect(caixa.querySelector('[data-testid="login-submit-btn"]').textContent).toBe('Entrar');
});

test('a entrada: um 422 de outro campo mostra a mensagem do validador, sem o «Value error,»', async () => {
  mockLogin.mockRejectedValue(recusa(422, [{ type: 'value_error', loc: ['body', 'password'], msg: 'Value error, A palavra-passe é obrigatória' }]));
  await desenhar(LoginPage);
  await act(async () => {
    escrever('login-email', 'carlos@gmail.com');
    escrever('login-password', 'x');
  });
  await submeter();
  expect(textoDoToast()).toContain('A palavra-passe é obrigatória');
  expect(caixa.querySelector('#login-email')).not.toBeNull();
});

test('o «Esqueci a palavra-passe»: o 422 diz que o email está mal, e não «Email Enviado»', async () => {
  axios.defaults.adapter = () => Promise.reject(recusa(422, LISTA_EMAIL));
  await desenhar(ForgotPasswordPage);
  await act(async () => escrever('email', 'carlos@gmailcom'));
  await submeter();
  expect(textoDoToast()).toContain('Email inválido. Verifique como está escrito.');
  expect(caixa.querySelector('[data-testid="forgot-form"]')).not.toBeNull();
  expect(caixa.querySelector('[data-testid="forgot-success-state"]')).toBeNull();
});

test('o «Esqueci a palavra-passe»: outro erro continua a dar a resposta de sempre', async () => {
  axios.defaults.adapter = () => Promise.reject(recusa(500, 'Internal Server Error'));
  await desenhar(ForgotPasswordPage);
  await act(async () => escrever('email', 'carlos@gmail.com'));
  await submeter();
  expect(caixa.querySelector('[data-testid="forgot-success-state"]')).not.toBeNull();
});

test('o ecrã do código: o 422 do email mostra a frase em português e o ecrã fica', async () => {
  axios.defaults.adapter = () => Promise.reject(recusa(422, LISTA_EMAIL));
  await desenhar(ResetPasswordPage);
  await act(async () => {
    escrever('reset-email', 'carlos@gmailcom');
    escrever('reset-code', '123456');
  });
  await submeter();
  expect(textoDoToast()).toContain('Email inválido. Verifique como está escrito.');
  expect(caixa.querySelector('[data-testid="reset-code-form"]')).not.toBeNull();
});
