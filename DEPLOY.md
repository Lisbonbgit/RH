# Guia de Migração — Emergent ➜ Hostinger

Sistema **RH grupo Lisbonb** (FastAPI + React + MongoDB).
Este guia leva-o do zero até ter o sistema a correr no seu próprio servidor.

---

## ⭐ REGRA DE OURO (trabalho em equipa — ler primeiro)

> **A produção corre SEMPRE o `main`. Nunca se faz deploy/`checkout` de um branch de
> funcionalidade no servidor. Antes de juntar ao `main`, traz o `main` para o teu branch,
> resolve conflitos, faz merge — e só depois se faz deploy, sempre do `main`.**

Porquê: o servidor mostra o branch que estiver em *checkout*. Fazer `git checkout <branch>`
de um branch antigo no servidor faz a produção **recuar** e "apagar" do site o trabalho que
já estava no `main` (mesmo estando a salvo no GitHub).

**As 6 práticas:**
1. O servidor vive no `main`. Deploy **só** com `./deploy.sh` (recusa qualquer coisa que não seja o `main`).
2. Começa sempre do `main` atualizado: `git checkout main && git pull` **antes** de `git checkout -b o-meu-branch`.
3. Antes de fechar a tua fase: no teu branch, `git fetch && git merge origin/main` e resolve conflitos.
4. Junta ao `main` por Pull Request, **um de cada vez**, avisando o outro.
5. **Nunca** `git push --force` no `main`; **nunca** editar ficheiros diretamente no servidor.
6. Deploy só **depois** do merge, e sempre do `main`.

Deploy correto (no servidor):
```bash
cd ~/RH && ./deploy.sh
```

---

## 0. O que vai precisar

| Item | Onde | Custo |
|------|------|-------|
| **VPS Hostinger** (KVM 1 chega para começar) | hpanel.hostinger.com ➜ VPS | ~5-8 €/mês |
| **MongoDB Atlas** (cluster M0 grátis) | mongodb.com/atlas | Grátis |
| **Conta Resend** (emails de recuperação) | resend.com | Grátis até 3000 emails/mês |
| **Domínio** (ex.: rh.grupolisbonb.pt) | já tem na Hostinger | — |

> ⚠️ **Importante:** o plano **Business Web Hosting** que já tem **NÃO serve** para correr
> este sistema (é alojamento partilhado, só PHP/MySQL). É preciso um **VPS**, que se
> compra à parte no mesmo painel da Hostinger. O domínio do Business pode ser reutilizado.

---

## 1. Base de dados — MongoDB Atlas (grátis)

1. Crie conta em **https://www.mongodb.com/atlas** e um projeto.
2. **Build a Database** ➜ **M0 (Free)** ➜ escolha a região mais perto (ex.: Frankfurt/Paris).
3. **Database Access** ➜ *Add New Database User*:
   - Username: `rh_app`  ·  Password: (gere uma forte e guarde)
4. **Network Access** ➜ *Add IP Address* ➜ por agora `0.0.0.0/0` (qualquer IP).
   - 🔒 Mais tarde substitua pelo **IP do seu VPS** para maior segurança.
5. **Connect** ➜ *Drivers* ➜ copie a *connection string*. Fica algo como:
   ```
   mongodb+srv://rh_app:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Substitua `<password>` pela password do utilizador. Guarde — vai para o `.env`.

---

## 2. Comprar e aceder ao VPS Hostinger

1. No **hPanel** ➜ **VPS** ➜ comprar **KVM 1**.
2. No setup, escolha o template **Ubuntu 24.04 com Docker** (se existir) ou só **Ubuntu 24.04**.
3. Anote o **IP do VPS** e a **password de root**.
4. Aceda por SSH (no seu Mac, no Terminal):
   ```bash
   ssh root@IP_DO_SEU_VPS
   ```

---

## 3. Instalar o Docker (se o template não o trouxe)

```bash
curl -fsSL https://get.docker.com | sh
docker --version            # confirmar
```

---

## 4. Obter o código no VPS

```bash
apt-get update && apt-get install -y git
git clone https://github.com/Lisbonbgit/RH.git
cd RH
```

---

## 5. Configurar as variáveis (backend/.env)

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Preencha:

- **MONGO_URL** — a connection string do Atlas (passo 1).
- **DB_NAME** — `rh_lisbonb` (ou outro nome).
- **JWT_SECRET** — gere uma chave forte:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- **ADMIN_EMAIL** — o seu email de administrador.
- **ADMIN_PASSWORD_HASH** — gere o hash da sua password:
  ```bash
  docker run --rm python:3.11-slim sh -c "pip install -q bcrypt && python -c \"import bcrypt,sys; print(bcrypt.hashpw(b'A-SUA-PASSWORD', bcrypt.gensalt()).decode())\""
  ```
  (substitua `A-SUA-PASSWORD`). Cole o resultado no `.env`.
- **CORS_ORIGINS** e **FRONTEND_URL** — o seu domínio, ex.: `https://rh.grupolisbonb.pt`.
- **RESEND_API_KEY** e **SENDER_EMAIL** — da conta Resend (veja passo 8).

Grave com `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## 6. Arrancar o sistema

```bash
docker compose up -d --build
```

Verifique:
```bash
docker compose ps          # ambos os serviços "running"
docker compose logs -f     # ver arranque (Ctrl+C para sair)
```

Abra no browser `http://IP_DO_SEU_VPS` — deve aparecer o ecrã de login.
Entre com o **ADMIN_EMAIL** e a password que escolheu.

---

## 7. Apontar o domínio e ativar HTTPS

1. No hPanel ➜ **DNS** do seu domínio ➜ crie um registo **A**:
   - Nome: `rh` (ou `@`) ·  Aponta para: **IP do VPS**.
2. Instale HTTPS gratuito (Let's Encrypt) no VPS:
   ```bash
   apt-get install -y certbot
   docker compose stop frontend            # libertar a porta 80
   certbot certonly --standalone -d rh.grupolisbonb.pt
   docker compose start frontend
   ```
   > Para HTTPS automático e renovação, recomendo depois passar a usar um proxy
   > (Caddy ou Nginx Proxy Manager). Posso configurar isto consigo numa próxima fase.

---

## 8. Emails de recuperação (Resend)

1. Em **https://resend.com** crie conta e uma **API Key**.
2. **Domains** ➜ adicione e verifique `grupolisbonb.pt` (adicionar registos DNS no hPanel).
3. No `backend/.env`:
   - `RESEND_API_KEY=re_...`
   - `SENDER_EMAIL=nao-responder@grupolisbonb.pt`
4. Reinicie: `docker compose up -d --build backend`

---

## 9. Manutenção do dia a dia

```bash
# Atualizar para a versão mais recente do código
cd ~/RH && git pull && docker compose up -d --build

# Ver logs
docker compose logs -f backend

# Reiniciar
docker compose restart

# Parar tudo
docker compose down
```

**Backups:** o Atlas já faz backup da base de dados. Os documentos enviados ficam no
volume `uploads_data` do Docker — para os copiar:
```bash
docker run --rm -v rh_uploads_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/uploads-backup.tar.gz -C /data .
```

---

## Migrar os dados que já existem no Emergent (opcional)

Se quiser trazer os dados que já tem no Emergent:
1. Exporte a base de dados antiga (no Emergent) com `mongodump`.
2. Importe para o Atlas com `mongorestore --uri "mongodb+srv://..."`.

Diga-me se precisa e ajudo no processo de exportação/importação.
