"""A casca iOS «Gestão Lisbonb» (`app-bolso/`): o que vai no TestFlight como build 3.

A casca carrega o site que está no ar; o que ela própria leva é pouco, e cada
coisa daqui é uma build nova se sair errada:

- a peça nativa do Face ID, numa versão FIXA — a 6.0.4 é a única que aceita o
  Capacitor 6 e traz as cinco funções de que o site precisa; um `^` deixava o
  `npm install` trazer outra;
- o texto que o iPhone mostra ao pedir licença para o Face ID (sem ele, o iOS
  fecha a app no primeiro pedido);
- o número da build (o App Store Connect recusa um número repetido);
- o endereço que a casca abre: o ensaio no simulador troca-o por um local, e
  uma build enviada assim abria um ecrã branco nos telemóveis dos gestores.
"""
import json
import re
from pathlib import Path

_CASCA = Path(__file__).resolve().parents[3] / "app-bolso"
_IOS = _CASCA / "ios" / "App"


def test_a_casca_da_build_3_leva_o_face_id_e_abre_a_producao():
    pacote = json.loads((_CASCA / "package.json").read_text(encoding="utf-8"))
    assert pacote["dependencies"].get("@capgo/capacitor-native-biometric") == "6.0.4"

    plist = (_IOS / "App" / "Info.plist").read_text(encoding="utf-8")
    assert re.search(
        r"<key>NSFaceIDUsageDescription</key>\s*<string>Usamos o Face ID para entrar na "
        r"Gestão Lisbonb sem escrever a senha\.</string>",
        plist,
    )
    # O ensaio no simulador abre a rede local; isso nunca vai numa build.
    assert "NSAppTransportSecurity" not in plist

    projecto = (_IOS / "App.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    assert re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", projecto) == ["3", "3"]
    assert re.findall(r"MARKETING_VERSION = ([\d.]+);", projecto) == ["1.0", "1.0"]

    config = json.loads((_CASCA / "capacitor.config.json").read_text(encoding="utf-8"))
    assert config["server"]["url"] == "https://rh.lisbonb.com/bolso"
    assert config["server"].get("cleartext") is False

    assert "CapgoCapacitorNativeBiometric" in (_IOS / "Podfile").read_text(encoding="utf-8")
    assert "CapgoCapacitorNativeBiometric" in (_IOS / "Podfile.lock").read_text(encoding="utf-8")
