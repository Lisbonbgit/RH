# -*- mode: python ; coding: utf-8 -*-
"""Como se faz o .exe. Correr NUM PC WINDOWS:  pyinstaller agente.spec
Sai um ficheiro só: dist/ImpressaoLacai.exe — ver INSTALAR-IMPRESSAO.md."""

a = Analysis(
    ['arrancar.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # `win32print` é importado dentro de um try/except em windows.py (para o
    # ficheiro se poder importar num Mac e os testes correrem). O PyInstaller
    # segue imports normais, mas um dentro de try/except pode escapar-lhe —
    # e o .exe saía sem ele, a dizer «só imprime no Windows» EM Windows.
    hiddenimports=['win32print'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nada disto é preciso e tudo isto pesa. Um .exe mais pequeno copia-se
    # para cinco lojas por email sem chatices.
    excludes=['numpy', 'pandas', 'matplotlib', 'PIL', 'pytest', 'unittest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='ImpressaoLacai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # **`console=False`**: sem janela preta de linha de comandos por trás da
    # janela do programa. Numa loja, uma janela preta é uma janela que alguém
    # fecha — e fechá-la matava a impressão do dia inteiro.
    console=False,
)
