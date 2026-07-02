# Lisbonb RH — App iOS / Android (Capacitor)

A app móvel reutiliza a app web (`frontend`) embrulhada com **Capacitor**.
Mesmo código → site + iOS + Android. A localização do ponto usa o **GPS nativo**.

- **Nome:** Lisbonb RH · **ID:** `com.lisbonb.rh`
- **Backend:** a app fala com `https://rh.lisbonb.com` (definido no `build:mobile`).
- **Política de privacidade (lojas):** https://rh.lisbonb.com/privacidade

> A app traz a interface "embutida". Quando mudarmos a app web, é preciso
> `yarn build:mobile && npx cap sync` e publicar nova versão nas lojas.

---

## Pré-requisitos (uma vez, no Mac)
- Node 20+ e Yarn (já tens).
- **Xcode** (App Store) + **CocoaPods**: `sudo gem install cocoapods`.
- **Android Studio** (inclui SDK + JDK).
- Contas **Apple Developer** e **Google Play Console**.

## Fase 2 — Compilar e testar
```bash
cd frontend

# 1) instalar dependências (inclui o Capacitor)
yarn install

# 2) build da web a apontar para o backend de produção
yarn build:mobile

# 3) adicionar as plataformas nativas (só na 1.ª vez) — cria as pastas ios/ e android/
npx cap add ios
npx cap add android

# 4) sincronizar a build com as apps nativas (sempre que mudar a web)
npx cap sync

# 5) ícones e splash a partir de assets/icon.svg e assets/splash.svg
#    (a ferramenta lê PNG; converter antes — ver nota no fim)
npx @capacitor/assets generate --iconBackgroundColor '#1366F0' --splashBackgroundColor '#1366F0'

# 6) abrir e correr
npx cap open ios       # corre no Xcode (simulador ou iPhone real)
npx cap open android   # corre no Android Studio (emulador ou telemóvel)
```

### iOS — passos no Xcode
- **Signing & Capabilities** → escolher o teu *Team* (conta Apple Developer).
- Em `ios/App/App/Info.plist` confirmar a chave (o motivo aparece ao pedir GPS):
  - `NSLocationWhenInUseUsageDescription` = `A Lisbonb RH usa a sua localização apenas para validar o registo de ponto junto ao local de trabalho.`
- Correr no iPhone real para testar a localização.

### Android — notas
- As permissões de localização são adicionadas automaticamente pelo plugin.
- `applicationId` já é `com.lisbonb.rh`.

## Fase 3 — Publicar
**Apple (App Store Connect):** criar app com o ID `com.lisbonb.rh`; em *App Privacy*
declarar recolha de **Localização** (ligada ao utilizador, para "funcionalidade da
app", **não** para rastreio) e **Identificadores/Conta**; indicar a política de
privacidade. Distribuir primeiro por **TestFlight** (testar com colaboradores) e depois submeter.

**Google (Play Console):** criar app; preencher o formulário **Data safety**
(Localização + Informação de conta); indicar a política de privacidade; subir o
**AAB** assinado (Android Studio → Build → Generate Signed Bundle).

---

## Nota — converter o SVG para PNG (para o passo 5)
A ferramenta de assets usa `assets/icon.png` (1024×1024) e `assets/splash.png` (2732×2732).
No Mac, a partir dos SVG já criados:
```bash
# precisa de librsvg: brew install librsvg
rsvg-convert -w 1024 -h 1024 assets/icon.svg   -o assets/icon.png
rsvg-convert -w 2732 -h 2732 assets/splash.svg -o assets/splash.png
```
(Em alternativa, abrir o SVG no Preview e exportar como PNG com esses tamanhos.)
