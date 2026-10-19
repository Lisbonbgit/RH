import React, { createContext, useCallback, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { apagar as apagarFaceId, emailGuardado, guardar as guardarFaceId } from '../lib/faceid';
import { abrirBarreira, ligarEntrada, reentrar } from '../lib/sessao';

const AuthContext = createContext(null);

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);
  // O `/auth/me` do arranque falhou SEM ser o servidor a recusar a sessão (rede
  // em baixo, 502 do deploy). O token fica; o `ProtectedRoute` mostra «Sem
  // ligação — tentar de novo» em vez de mandar para o login.
  const [semLigacao, setSemLigacao] = useState(false);

  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      fetchUser();
    } else {
      setLoading(false);
    }
  }, [token]);

  // **Só se termina a sessão quando o SERVIDOR a recusa.**
  //
  // Antes, qualquer erro aqui chamava `logout()` — e o `logout()` apaga o
  // token do browser. Um erro SEM resposta (o 4G a falhar num café, o VPS a
  // reiniciar, o telemóvel a acordar do bolso) não diz nada sobre a validade
  // da sessão, e apagar o token com base nele era uma afirmação sem base:
  // quem estava a trabalhar era atirado para o ecrã de entrar por causa de um
  // pedido que nunca chegou a ser respondido.
  //
  // Por isso há duas mudanças e não uma: sem resposta **insiste-se** (três
  // tentativas, 1 s e 2 s de intervalo — um piscar de rede dura menos do que
  // isso) e, se mesmo assim não vier resposta, o token **fica** e o
  // `ProtectedRoute` mostra «Sem ligação — tentar de novo» (`semLigacao`) em
  // vez do ecrã de entrar: pedir a senha por um pedido sem resposta era
  // afirmar que a sessão acabou sem o saber.
  const fetchUser = async (tentativa = 1) => {
    try {
      const response = await axios.get(`${API_URL}/auth/me`);
      setUser(response.data);
    } catch (error) {
      const status = error?.response?.status;
      // Sessão expirada (24 h): na casca com Face ID tenta-se a re-entrada;
      // sem Face ID, `reentrar()` diz logo que não e fica tudo como era.
      if (status === 401) {
        if (!(await reentrar())) logout();
        return;
      }
      if (status === 403) {
        logout();
        return;
      }
      if (!error?.response && tentativa < 3) {
        await new Promise((r) => setTimeout(r, 1000 * tentativa));
        return fetchUser(tentativa + 1);
      }
      console.error('Não foi possível confirmar a sessão (a sessão não foi terminada):', error);
      setSemLigacao(true);
    } finally {
      setLoading(false);
    }
  };

  const login = async (email, password) => {
    const response = await axios.post(`${API_URL}/auth/login`, { email, password });
    const { token: newToken, user: userData } = response.data;
    localStorage.setItem('token', newToken);
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`;
    setToken(newToken);
    setUser(userData);
    // Entrou: o servidor respondeu. Um «Sem ligação» de antes já não é verdade.
    setSemLigacao(false);
    // Quem acabou de entrar (senha ou Face ID) não leva com a barreira a seguir.
    abrirBarreira();
    return userData;
  };
  // A re-entrada do Face ID entra por aqui, para o token, o cabeçalho e o
  // estado ficarem iguais aos de um login com senha. Atribuição simples a cada
  // render (o `login` só usa setters e o localStorage — nunca fica velho).
  ligarEntrada(login);

  const tentarDeNovo = () => {
    setSemLigacao(false);
    setLoading(true);
    fetchUser();
  };

  const changePassword = async (currentPassword, newPassword) => {
    const response = await axios.post(`${API_URL}/auth/change-password`, {
      current_password: currentPassword,
      new_password: newPassword
    });
    
    // Update token with new token that has must_change_password = false
    if (response.data.token) {
      localStorage.setItem('token', response.data.token);
      axios.defaults.headers.common['Authorization'] = `Bearer ${response.data.token}`;
      setToken(response.data.token);
      
      // Update user state to reflect must_change_password = false
      setUser(prev => ({ ...prev, must_change_password: false }));
    }
    
    // Com o Face ID ligado PARA ESTA CONTA, o Keychain leva a senha nova: senão a
    // próxima re-entrada dava 401 e o Face ID perdia-se. O de outra pessoa fica.
    if (emailGuardado() === user?.email) await guardarFaceId(user.email, newPassword);
    return response.data;
  };

  // Estável (useCallback): a Barreira e o BolsoApp dependem dele em efeitos.
  // **Não apaga o Keychain** — é o que corre num 401 ou num Face ID cancelado.
  const logout = useCallback(() => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
    // Sem isto, quem saísse depois de um «Sem ligação» via-o outra vez em vez do login.
    setSemLigacao(false);
  }, []);

  // O botão «Terminar sessão»: sair E esquecer o Face ID deste telemóvel.
  const terminarSessao = useCallback(() => {
    logout();
    apagarFaceId();
  }, [logout]);

  const isAdmin = user?.role === 'admin';
  const isEmployee = user?.role === 'colaborador';
  const mustChangePassword = user?.must_change_password === true;

  return (
    <AuthContext.Provider value={{
      user,
      token,
      loading,
      login,
      logout,
      terminarSessao,
      semLigacao,
      tentarDeNovo,
      changePassword,
      isAdmin,
      isEmployee,
      isAuthenticated: !!user,
      mustChangePassword
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
