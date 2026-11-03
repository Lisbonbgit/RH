/**
 * O QUE VAI NO PUT DO «EDITAR COLABORADOR» — corrido de verdade, não lido.
 *
 * A promessa: o email só segue quando o gestor o MUDOU (sem contar maiúsculas e
 * espaços), e segue sem os espaços. Mudar o email muda o login do colaborador e
 * apaga o código de recuperação pendente — não pode acontecer por acaso.
 *
 * O que isto NÃO prova: que o diálogo usa esta função. Isso vê-se com a app aberta.
 */
import { dadosParaAtualizar } from './colaboradores';

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
  test('maiúsculas e espaços não são mudança', () => {
    const dados = dadosParaAtualizar(formulario({ email: '  ZE.Errado@Example.com ' }), ficha);
    expect(dados).not.toHaveProperty('email');
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
