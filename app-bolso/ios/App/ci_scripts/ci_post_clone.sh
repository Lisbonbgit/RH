#!/bin/sh
# Xcode Cloud: o que corre logo a seguir a clonar o repositório.
#
# **Sem isto a build falha, e falha de uma maneira confusa.** O projecto usa
# CocoaPods (é o Capacitor que o traz), e a pasta `Pods/` NÃO vai no
# repositório — nem deve ir, é código de terceiros que se reinstala a partir do
# `Podfile.lock`. O Xcode Cloud clona, encontra o `App.xcworkspace` a apontar
# para um `Pods.xcodeproj` que não existe, e desiste a meio da compilação com
# um erro que não diz "faltam os pods".
#
# `--deployment` é deliberado: instala EXACTAMENTE as versões do
# `Podfile.lock`, e recusa-se a resolver versões novas por sua conta. Uma build
# na nuvem que actualize dependências sozinha deixa de ser reprodutível — e a
# que sai daqui vai para o telemóvel do dono.
set -e

echo "[ci_post_clone] a instalar os pods em $CI_PRIMARY_REPOSITORY_PATH"

# O CocoaPods já vem na imagem do Xcode Cloud; se algum dia deixar de vir, esta
# linha instala-o em vez de a build falhar por uma razão que ninguém adivinha.
if ! command -v pod > /dev/null 2>&1; then
  echo "[ci_post_clone] CocoaPods não encontrado — a instalar"
  export HOMEBREW_NO_AUTO_UPDATE=1
  brew install cocoapods
fi

cd "$CI_PRIMARY_REPOSITORY_PATH/app-bolso/ios/App"
pod install --deployment

echo "[ci_post_clone] pods instalados"
