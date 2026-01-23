# Sistema de Gestão de Recursos Humanos - PRD

## Problema Original
Criar um Sistema Interno de Gestão de Recursos Humanos, totalmente em português (PT), para uso empresarial interno. Sistema para múltiplas empresas com colaboradores, controlo de ponto, férias, ausências e documentos.

## User Personas
1. **Administrador de RH**: Gestão completa de empresas, locais, colaboradores, aprovação de pedidos, documentos
2. **Colaborador**: Registo de ponto, pedidos de ausência, consulta de documentos

## Core Requirements (Estáticos)
- Autenticação JWT (email/palavra-passe)
- Perfis: Administrador e Colaborador
- Múltiplas empresas e locais
- CRUD de colaboradores
- Controlo de ponto (entrada/saída)
- Férias e ausências (pedidos e aprovações)
- Documentos organizados em pastas
- Notificações internas
- Interface em Português PT
- Tema claro profissional
- Responsivo (admin desktop, colaborador mobile)

## Implementado (23/01/2024)

### Backend (FastAPI + MongoDB)
- [x] Autenticação JWT completa
- [x] CRUD Empresas
- [x] CRUD Locais
- [x] CRUD Colaboradores (com criação automática de conta)
- [x] Registo de Ponto (entrada/saída)
- [x] Correção de Ponto (admin) com histórico
- [x] Pedidos de Férias/Ausências
- [x] Aprovação/Recusa de pedidos
- [x] Sistema de Pastas por colaborador
- [x] Upload/Download de Documentos
- [x] Notificações internas
- [x] Dashboard Admin com estatísticas
- [x] Dashboard Colaborador
- [x] Calendário de ausências

### Frontend (React + Shadcn UI)
- [x] Página de Login/Registo
- [x] Layout Admin com sidebar
- [x] Layout Colaborador mobile-first
- [x] Dashboard Admin (estatísticas, calendário)
- [x] Gestão de Empresas
- [x] Gestão de Locais
- [x] Gestão de Colaboradores
- [x] Controlo de Ponto (visualização, correção)
- [x] Férias e Ausências (aprovação/recusa)
- [x] Documentos (pastas, upload)
- [x] Dashboard Colaborador
- [x] Registo de Ponto (botões entrada/saída)
- [x] Pedidos de Ausência
- [x] Documentos do Colaborador
- [x] Notificações

## Prioritized Backlog

### P0 (Crítico) - Concluído
- ✅ Autenticação funcional
- ✅ CRUD básico (empresas, locais, colaboradores)
- ✅ Registo de ponto
- ✅ Pedidos de ausência

### P1 (Importante) - Concluído
- ✅ Aprovação de pedidos
- ✅ Sistema de documentos
- ✅ Notificações
- ✅ Dashboard com estatísticas

### P2 (Melhorias Futuras)
- [ ] Relatórios de ponto (PDF/Excel)
- [ ] Gráficos avançados no dashboard
- [ ] Histórico de férias utilizadas vs disponíveis
- [ ] Alertas de conflito de férias
- [ ] Integração com calendário externo

## Arquitetura
```
Frontend (React 19 + Shadcn UI + Tailwind)
    ↓
Backend (FastAPI + JWT Auth)
    ↓
MongoDB (Motor async driver)
```

## Próximas Ações
1. Relatórios de ponto em PDF/Excel
2. Cálculo automático de férias utilizadas
3. Sistema de alertas de conflitos
4. Export de dados para integração externa
