import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';

const AuthContext = createContext(null);

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);

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
  // isso) e, se mesmo assim não vier resposta, o token **fica**. Aí o ecrã de
  // entrar aparece na mesma (o `isAuthenticated` é `!!user`), mas o próximo
  // recarregamento já recupera a sessão sozinho, sem escrever nada.
  const fetchUser = async (tentativa = 1) => {
    try {
      const response = await axios.get(`${API_URL}/auth/me`);
      setUser(response.data);
    } catch (error) {
      const status = error?.response?.status;
      if (status === 401 || status === 403) {
        logout();
        return;
      }
      if (!error?.response && tentativa < 3) {
        await new Promise((r) => setTimeout(r, 1000 * tentativa));
        return fetchUser(tentativa + 1);
      }
      console.error('Não foi possível confirmar a sessão (a sessão não foi terminada):', error);
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
    return userData;
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
    
    return response.data;
  };

  const logout = () => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
  };

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
