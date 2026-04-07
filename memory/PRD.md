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
- [x] **Cálculo automático de férias utilizadas vs disponíveis**

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
- [x] Dashboard Colaborador com resumo de férias
- [x] Registo de Ponto (botões entrada/saída)
- [x] Pedidos de Ausência
- [x] Documentos do Colaborador
- [x] Notificações

## Credenciais do Sistema
- **Admin Principal**: geral@olacai.com

## Arquitetura
```
Frontend (React 19 + Shadcn UI + Tailwind)
    ↓
Backend (FastAPI + JWT Auth)
    ↓
MongoDB (Motor async driver)
```

## Atualizações Recentes (07/04/2026)
- [x] Fluxo de “Esqueci a Palavra-passe” com envio de código de 6 dígitos via email (Resend)
- [x] Verificação do código no site antes de permitir redefinição
- [x] UI atualizada para inserir código e nova palavra-passe

## Fase Concluída
O sistema está estável e pronto para validação com a equipa.
