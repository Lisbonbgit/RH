/**
 * @jest-environment jsdom
 */
// A ÚLTIMA DEFESA — um filho que rebenta a desenhar deixa «Algo correu mal.» e
// um botão, não a página branca. Desenhado a sério (react-dom/client + act).
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import ErrorBoundary from './ErrorBoundary';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let caixa;
let raiz;
beforeEach(() => {
  caixa = document.createElement('div');
  document.body.appendChild(caixa);
  raiz = createRoot(caixa);
});
afterEach(() => {
  act(() => raiz.unmount());
  caixa.remove();
  jest.restoreAllMocks();
});

// O que o sonner fazia com o `detail` de um 422: uma lista de objetos como filho.
const Rebenta = () => <div>{[{ type: 'value_error', loc: ['body', 'email'], msg: 'x' }]}</div>;

test('um filho que rebenta mostra o ecrã de recurso, e o erro fica registado', () => {
  const registo = jest.spyOn(console, 'error').mockImplementation(() => {});
  act(() => raiz.render(<ErrorBoundary><p>antes</p><Rebenta /></ErrorBoundary>));
  expect(caixa.textContent).toContain('Algo correu mal.');
  expect(caixa.textContent).not.toContain('antes');
  const botao = caixa.querySelector('button');
  expect(botao).not.toBeNull();
  expect(botao.textContent).toBe('Recarregar');
  expect(registo.mock.calls.some(([primeiro]) => primeiro === 'Erro inesperado no portal:')).toBe(true);
});

test('sem erro, desenha os filhos e mais nada', () => {
  act(() => raiz.render(<ErrorBoundary><p>o portal</p></ErrorBoundary>));
  expect(caixa.textContent).toBe('o portal');
  expect(caixa.querySelector('button')).toBeNull();
});
