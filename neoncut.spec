# Receita do PyInstaller: gera dist\NeonCut\NeonCut.exe (pasta unica, abre rapido).
# Uso: .venv\Scripts\pyinstaller neoncut.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

VERSION = "1.0.0"
BUNDLED_BACKGROUNDS = ["setup-roxo.jpg", "setup-roxo-animado.mp4", "setup-azul.jpg", "setup-vermelho.jpg"]

datas = [
    ("assets/icon.png", "assets"),
    ("models/rvm_mobilenetv3_fp32.onnx", "models"),
    ("LICENSE", "."),
]
datas += [(f"fundos/{name}", "fundos") for name in BUNDLED_BACKGROUNDS]
# So o grafo e os modelos da segmentacao de selfie (o mediapipe inteiro tem ~100 MB de modelos)
datas += collect_data_files("mediapipe", includes=["modules/selfie_segmentation/*"])

# Recurso de versao do .exe (aparece em Propriedades > Detalhes)
Path("build").mkdir(exist_ok=True)
nums = ", ".join(VERSION.split(".") + ["0"])
Path("build/version.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),
  kids=[StringFileInfo([StringTable('041604B0', [
    StringStruct('CompanyName', 'Pedro Giampietro'),
    StringStruct('FileDescription', 'NeonCut - troca o fundo da webcam com IA'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', 'NeonCut'),
    StringStruct('LegalCopyright', 'GPL-3.0'),
    StringStruct('OriginalFilename', 'NeonCut.exe'),
    StringStruct('ProductName', 'NeonCut'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])])
""", encoding="utf-8")

a = Analysis(
    ["app.py"],
    datas=datas,
    binaries=collect_dynamic_libs("onnxruntime"),
    hiddenimports=collect_submodules("pygrabber") + ["comtypes.stream"],
    excludes=["tkinter", "tensorflow", "torch", "jax", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeonCut",
    icon="assets/icon.ico",
    version="build/version.txt",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="NeonCut")
