/**
 * O QUE VAI NO PUT DO «EDITAR COLABORADOR» — corrido de verdade, não lido.
 *
 * A promessa: o email só segue quando o gestor o MUDOU (sem contar os espaços;
 * as maiúsculas contam, porque é como o email fica gravado), e segue sem os
 * espaços. Mudar o email muda o login do colaborador e apaga o código de
 * recuperação pendente — não pode acontecer por acaso.
 *
 * E um erro do servidor chega ao toast sempre como texto: o 422 do FastAPI traz
 * uma LISTA de objetos, que o sonner desenhava como filho React (portal em branco).
 *
 * O que isto NÃO prova: que o diálogo usa esta função. Isso vê-se com a app aberta.
 */
import { dadosParaAtualizar, mensagemDoErro } from './colaboradores';

const ficha = {
  id: 'e-ze',
  name: 'Zé',
  email: 'ze.errado@example.com',
  photo: 'data:image/jpeg;base64,AAAA',
};

const formulario = (extra = {}) => ({
  name: 'Zé',
  email: 'ze.errado@example.com',
  password: '',
  company_id: 'emp-1',
  position: 'Motorista',
  photo: 'data:image/jpeg;base64,AAAA',
  ...extra,
});

describe('dadosParaAtualizar — o email', () => {
  test('sem mudança, o email não vai', () => {
    expect(dadosParaAtualizar(formulario(), ficha)).not.toHaveProperty('email');
  });
  test('só espaços não são mudança', () => {
    const dados = dadosParaAtualizar(formulario({ email: '  ze.errado@example.com ' }), ficha);
    expect(dados).not.toHaveProperty('email');
  });
  test('só maiúsculas é mudança: muda como fica gravado, por isso vai', () => {
    const gravado = { ...ficha, email: 'Ze.Errado@example.com' };
    const dados = dadosParaAtualizar(formulario({ email: ' ze.errado@example.com ' }), gravado);
    expect(dados.email).toBe('ze.errado@example.com');
  });
  test('mudou: vai, sem os espaços e tal como foi escrito', () => {
    const dados = dadosParaAtualizar(formulario({ email: ' Ze@example.com ' }), ficha);
    expect(dados.email).toBe('Ze@example.com');
  });
  test('ficha sem email (dados antigos): o que se escrever vai', () => {
    const dados = dadosParaAtualizar(formulario({ email: 'ze@example.com' }), { ...ficha, email: undefined });
    expect(dados.email).toBe('ze@example.com');
  });
});

describe('dadosParaAtualizar — os outros campos, como antes', () => {
  test('a palavra-passe nunca vai na edição', () => {
    expect(dadosParaAtualizar(formulario({ password: 'Nova#2026x' }), ficha)).not.toHaveProperty('password');
  });
  test('a foto que não mudou não é reenviada', () => {
    expect(dadosParaAtualizar(formulario(), ficha)).not.toHaveProperty('photo');
  });
  test('a foto nova vai, e a removida vai vazia', () => {
    expect(dadosParaAtualizar(formulario({ photo: 'data:image/jpeg;base64,BBBB' }), ficha).photo)
      .toBe('data:image/jpeg;base64,BBBB');
    expect(dadosParaAtualizar(formulario({ photo: '' }), ficha).photo).toBe('');
  });
  test('sem foto na ficha e sem foto no formulário, não vai', () => {
    expect(dadosParaAtualizar(formulario({ photo: '' }), { ...ficha, photo: null })).not.toHaveProperty('photo');
  });
  test('o resto vai tal e qual, e o formulário não é alterado', () => {
    const form = formulario({ name: 'Zé Silva', email: 'ze@example.com' });
    const copia = { ...form };
    const dados = dadosParaAtualizar(form, ficha);
    expect(dados).toEqual({ name: 'Zé Silva', email: 'ze@example.com', company_id: 'emp-1', position: 'Motorista' });
    expect(form).toEqual(copia);
  });
});

describe('mensagemDoErro — o que vai para o toast é sempre texto', () => {
  const erro = (status, detail) => ({ response: { status, data: { detail } } });

  test('a mensagem do servidor vai tal e qual', () => {
    expect(mensagemDoErro(erro(400, 'Email já registado'))).toBe('Email já registado');
  });
  test('um 422 do email (lista de objetos, em inglês) dá uma frase em português', () => {
    const detalhe = [{ type: 'value_error', loc: ['body', 'email'], input: 'motorista@gmail',
      msg: 'value is not a valid email address: The part after the @-sign is not valid. It should have a period.' }];
    const texto = mensagemDoErro(erro(422, detalhe));
    expect(typeof texto).toBe('string');
    expect(texto).toMatch(/^Email inválido/);
  });
  test('um 422 de outro campo mostra a mensagem do validador, sem o «Value error,»', () => {
    const detalhe = [{ type: 'value_error', loc: ['body', 'password'],
      msg: 'Value error, A palavra-passe deve ter pelo menos 8 caracteres' }];
    expect(mensagemDoErro(erro(422, detalhe))).toBe('A palavra-passe deve ter pelo menos 8 caracteres');
  });
  test('sem resposta, ou com um detalhe que não se sabe ler, a frase de sempre', () => {
    expect(mensagemDoErro(new Error('Network Error'))).toBe('Erro ao guardar colaborador');
    expect(mensagemDoErro(erro(500, { estranho: true }))).toBe('Erro ao guardar colaborador');
    expect(mensagemDoErro(erro(422, []))).toBe('Erro ao guardar colaborador');
  });
});
