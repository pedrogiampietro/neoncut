"""Motor de processamento do NeonCut: webcam -> recorte por IA -> composicao com o fundo.

Independente de interface: a UI so le/escreve Settings e recebe quadros prontos.
"""

import json
import os
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

APP_NAME = "NeonCut"
FROZEN = getattr(sys, "frozen", False)
# Arquivos que vem com o app (modelos, fundos de exemplo). No executavel do PyInstaller
# ficam em sys._MEIPASS; rodando do codigo, na pasta do projeto.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# Dados do usuario: instalado, a pasta do programa nao e gravavel -> %APPDATA%\NeonCut.
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME if FROZEN else APP_DIR
BG_DIR = DATA_DIR / "fundos"
CONFIG = DATA_DIR / "config.json"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".gif"}
VIRTUAL_CAMERAS = ("vcam", "virtual", "obs", "streamlabs", "unity", "xsplit", "nvidia broadcast")
RESOLUTIONS = [(1920, 1080), (1280, 720), (960, 540), (640, 480)]


@dataclass
class Settings:
    # Camera
    camera: str = ""            # nome do dispositivo; vazio = primeira camera fisica
    width: int = 1280
    height: int = 720
    fps: int = 30
    mirror: bool = True
    exposure_mode: str = "fixed"  # auto (melhor com pouca luz) | fixed (garante fps)
    exposure: int = -5            # DirectShow: 2^valor segundos (-5 = 1/32 s)
    gain: int = 64
    # Fundo
    bg_mode: str = "image"      # image | blur | color | none
    bg_file: str = ""
    bg_color: str = "#1b1030"
    blur_strength: int = 18     # modo desfoque
    bg_blur: int = 0            # desfoque aplicado ao fundo escolhido (profundidade)
    bg_dim: int = 0             # escurecer fundo (%)
    # Recorte
    model: int = 2              # 0 = MediaPipe preciso, 1 = MediaPipe rapido, 2 = RVM na GPU
    rvm_detail: int = 180       # resolucao interna do RVM (180 / 240 / 360), como os modelos x180/x240/x360 do VCam
    despill: bool = True        # usar a cor de primeiro plano estimada pelo RVM (tira o reflexo do fundo)
    cleanup: int = 60           # 0 = desligado; mantem so a regiao ligada a pessoa (tira objetos atras)
    feather: int = 4
    edge_shift: int = 0         # -30 (solto) .. +30 (justo)
    stability: int = 40         # % de suavizacao temporal
    show_mask: bool = False
    # Pessoa
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    scale: int = 100
    offset_x: int = 0
    offset_y: int = 0
    # Saida
    virtualcam: bool = False

    @classmethod
    def load(cls):
        s = cls()
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
            for f in fields(cls):
                if f.name in data:
                    setattr(s, f.name, type(getattr(s, f.name))(data[f.name]))
        except (OSError, ValueError, TypeError):
            pass
        return s

    def save(self):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


def list_cameras():
    try:
        from pygrabber.dshow_graph import FilterGraph
        return FilterGraph().get_input_devices()
    except Exception:
        return []


def is_virtual(name):
    return any(v in name.lower() for v in VIRTUAL_CAMERAS)


def resolve_camera(name):
    names = list_cameras()
    if name in names:
        return names.index(name), name
    for i, n in enumerate(names):
        if not is_virtual(n):
            return i, n
    return 0, names[0] if names else "Camera 0"


def list_backgrounds():
    if not BG_DIR.exists():
        BG_DIR.mkdir(parents=True)
        bundled = APP_DIR / "fundos"
        if FROZEN and bundled.is_dir():  # primeira execucao: copia os fundos de exemplo
            for p in bundled.iterdir():
                shutil.copy2(p, BG_DIR / p.name)
    return sorted(p for p in BG_DIR.iterdir() if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT)


def cover(img, w, h):
    """Preenche w x h sem distorcer (como background-size: cover)."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    img = cv2.resize(img, (max(w, int(iw * s + 0.5)), max(h, int(ih * s + 0.5))), interpolation=cv2.INTER_AREA)
    y, x = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
    return img[y:y + h, x:x + w]


def thumbnail(path, w=160, h=90):
    if path.suffix.lower() in VIDEO_EXT:
        cap = cv2.VideoCapture(str(path))
        ok, img = cap.read()
        cap.release()
        if not ok:
            return None
    else:
        img = cv2.imread(str(path))
        if img is None:
            return None
    return cover(img, w, h)


def hex_to_bgr(value):
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def guided_filter(guide, src, radius, eps):
    """Guided filter (He et al.): a borda da mascara segue as bordas reais da imagem."""
    k = (2 * radius + 1, 2 * radius + 1)
    mean_i = cv2.boxFilter(guide, -1, k)
    mean_p = cv2.boxFilter(src, -1, k)
    cov_ip = cv2.boxFilter(guide * src, -1, k) - mean_i * mean_p
    var_i = cv2.boxFilter(guide * guide, -1, k) - mean_i * mean_i
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    return cv2.boxFilter(a, -1, k) * guide + cv2.boxFilter(b, -1, k)


class Segmenter:
    def __init__(self, model):
        self.model_id = model
        self.model = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=model)
        self.prev = None

    def close(self):
        self.model.close()

    def mask(self, frame, s: Settings):
        h, w = frame.shape[:2]
        raw = self.model.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).segmentation_mask

        rw, rh = 640, int(640 * h / w)
        guide = cv2.cvtColor(cv2.resize(frame, (rw, rh)), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        m = cv2.resize(raw.astype(np.float32), (rw, rh))
        center = 0.55 + s.edge_shift / 100
        low, high = center - 0.2, center + 0.2
        m = np.clip((m - low) / (high - low), 0, 1)
        if s.feather > 0:
            m = np.clip(guided_filter(guide, m, s.feather, 1e-3), 0, 1)

        keep = s.stability / 100
        if keep > 0 and self.prev is not None and self.prev.shape == m.shape:
            m = (1 - keep) * m + keep * self.prev
        self.prev = m
        return cv2.resize(m, (w, h))


def keep_main_subject(alpha, strength):
    """Mantem so o maior bloco solido da mascara (voce) e apaga objetos soltos atras.

    strength 1..100 sobe o limite do que conta como "solido" (0,5 -> 0,95): mais forte
    separa objetos encostados em voce (cadeira, roupas), mas pode afinar roupas escuras.
    """
    h, w = alpha.shape
    small = cv2.resize(alpha, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    solid = (small > 0.5 + 0.45 * strength / 100).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    if n <= 2:  # nada alem do fundo e de um bloco so
        return alpha
    main = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    keep = (labels == main).astype(np.uint8) * 255
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    keep = cv2.GaussianBlur(keep, (0, 0), 3)
    return alpha * (cv2.resize(keep, (w, h)).astype(np.float32) / 255)


MODELS_DIR = APP_DIR / "models"


class RvmMatter:
    """Robust Video Matting via ONNX Runtime + DirectML (qualquer GPU DirectX 12).

    Diferente da segmentacao, estima a transparencia de cada pixel (fios de cabelo) e a
    cor real do primeiro plano. E recorrente: usa o quadro anterior, por isso a borda
    ja vem estavel sem suavizacao extra.
    """

    def __init__(self):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.log_severity_level = 3
        providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        self.on_gpu = providers[0] == "DmlExecutionProvider"
        # fp32 mesmo na GPU: o fp16 so ganha ~2 ms na placa, mas converter 1280x720
        # de/para float16 no processador custa ~30 ms por quadro.
        self.dtype = np.float32
        path = MODELS_DIR / "rvm_mobilenetv3_fp32.onnx"
        self.session = ort.InferenceSession(str(path), so, providers=providers)
        self.device = "GPU (DirectML)" if self.on_gpu else "CPU"
        self.shape = None
        self.rec = None

    def close(self):
        self.session = None

    def process(self, frame, s: Settings):
        h, w = frame.shape[:2]
        if (h, w, s.rvm_detail) != self.shape:
            self.shape = (h, w, s.rvm_detail)
            self.rec = [np.zeros((1, 1, 1, 1), self.dtype)] * 4
        src = cv2.dnn.blobFromImage(frame, 1 / 255, swapRB=True)
        ratio = np.array([min(1.0, s.rvm_detail / h)], np.float32)
        fgr, pha, *self.rec = self.session.run(None, {
            "src": src, "r1i": self.rec[0], "r2i": self.rec[1], "r3i": self.rec[2], "r4i": self.rec[3],
            "downsample_ratio": ratio})

        # Pos-processamento (rvm_finish) fica com a thread de composicao, para a GPU
        # ja comecar o proximo quadro.
        return pha[0, 0], fgr[0] if s.despill else None


def rvm_finish(alpha, fgr, s: Settings):
    if s.edge_shift:
        k = abs(s.edge_shift) / 100 * 1.5
        alpha = (alpha - k) / (1 - k) if s.edge_shift > 0 else alpha / (1 - k)
        alpha = np.clip(alpha, 0, 1)
    if fgr is None:
        return alpha, None
    r, g, b = fgr  # planos contiguos: montar BGR direto evita transpor 1280x720x3
    return alpha, cv2.convertScaleAbs(cv2.merge((b, g, r)), alpha=255)


class BackgroundSource:
    def __init__(self):
        self.key = None
        self.static = None
        self.video = None

    def close(self):
        if self.video is not None:
            self.video.release()
            self.video = None

    def get(self, frame, s: Settings):
        h, w = frame.shape[:2]
        if s.bg_mode == "blur":
            self.close()
            self.key = None
            k = max(1, s.blur_strength)
            small = cv2.resize(frame, (w // 4, h // 4))
            return cv2.resize(cv2.GaussianBlur(small, (0, 0), k / 3), (w, h))

        key = (s.bg_mode, s.bg_file, s.bg_color, s.bg_blur, s.bg_dim, w, h)
        if key != self.key:
            self.close()
            self.key = key
            self.static = None
            if s.bg_mode == "color":
                self.static = self._finish(np.full((h, w, 3), hex_to_bgr(s.bg_color), np.uint8), s)
            elif s.bg_mode == "image" and s.bg_file:
                path = BG_DIR / s.bg_file
                if path.suffix.lower() in VIDEO_EXT:
                    self.video = cv2.VideoCapture(str(path))
                else:
                    img = cv2.imread(str(path))
                    if img is not None:
                        self.static = self._finish(cover(img, w, h), s)
        if self.static is not None:
            return self.static
        if self.video is not None:
            ok, img = self.video.read()
            if not ok:
                self.video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = self.video.read()
            if ok:
                return self._finish(cover(img, w, h), s)
        return np.zeros_like(frame)

    @staticmethod
    def _finish(img, s):
        if s.bg_blur > 0:
            img = cv2.GaussianBlur(img, (0, 0), s.bg_blur / 2)
        if s.bg_dim > 0:
            img = cv2.convertScaleAbs(img, alpha=1 - s.bg_dim / 100)
        return img


def adjust_person(frame, s: Settings):
    if s.brightness or s.contrast:
        a = 1 + s.contrast / 100
        frame = cv2.convertScaleAbs(frame, alpha=a, beta=s.brightness * 1.5 + 128 * (1 - a))
    if s.saturation:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[..., 1] = cv2.convertScaleAbs(hsv[..., 1], alpha=1 + s.saturation / 100)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return frame


def place_person(frame, alpha, s: Settings):
    if s.scale == 100 and not s.offset_x and not s.offset_y:
        return frame, alpha
    h, w = frame.shape[:2]
    k = s.scale / 100
    tx = (1 - k) * w / 2 + s.offset_x / 100 * w
    ty = (1 - k) * h / 2 + s.offset_y / 100 * h
    m = np.float32([[k, 0, tx], [0, k, ty]])
    frame = cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    alpha = cv2.warpAffine(alpha, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    return frame, alpha


class CameraReader:
    """Le a webcam em thread propria: a IA processa um quadro enquanto o proximo chega."""

    def __init__(self, cap):
        self.cap = cap
        self.frame = None
        self.seq = 0
        self.cond = threading.Condition()
        self.running = True
        self.exposure_key = None
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            with self.cond:
                self.frame = frame
                self.seq += 1
                self.cond.notify_all()

    def latest(self, last_seq, timeout=0.5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq or not self.running, timeout)
            return self.frame, self.seq

    def apply_exposure(self, s: Settings):
        key = (s.exposure_mode, s.exposure, s.gain)
        if key == self.exposure_key:
            return
        self.exposure_key = key
        if s.exposure_mode == "auto":
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        else:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            self.cap.set(cv2.CAP_PROP_EXPOSURE, s.exposure)
        self.cap.set(cv2.CAP_PROP_GAIN, s.gain)

    def close(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()
        self.thread.join(timeout=2)  # nao liberar a camera no meio de um read()
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # devolve a camera no automatico
        self.cap.release()


class Engine:
    """Roda o pipeline numa thread. on_frame(bgr) e chamado com cada quadro pronto."""

    def __init__(self, settings: Settings, on_frame, on_status):
        self.s = settings
        self.on_frame = on_frame
        self.on_status = on_status
        self.running = False
        self.thread = None
        self.fps = 0.0
        self.camera_name = ""
        self.virtualcam_device = None
        self.matter_device = ""
        self.vcam = None
        self.job = None  # ultimo quadro com mascara, esperando a composicao
        self.job_cond = threading.Condition()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

    def _open_camera(self):
        index, self.camera_name = resolve_camera(self.s.camera)
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.on_status(f"Não consegui abrir \"{self.camera_name}\". Ela está em uso por outro programa? "
                           "Desative a fonte da webcam no Streamlabs.", True)
            return None
        # A ordem importa no DirectShow: fps e tamanho antes do formato, senao o
        # driver cai em YUY2 (sem compressao), que em 720p limita a ~7 fps no USB 2.
        cap.set(cv2.CAP_PROP_FPS, self.s.fps)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.s.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.s.height)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.on_status(f"Camera: {self.camera_name}", False)
        return CameraReader(cap)

    def _open_virtualcam(self):
        try:
            import pyvirtualcam
            cam = pyvirtualcam.Camera(self.s.width, self.s.height, self.s.fps, fmt=pyvirtualcam.PixelFormat.BGR)
            self.virtualcam_device = cam.device
            return cam
        except Exception as e:
            self.virtualcam_device = None
            self.on_status(f"Câmera virtual indisponível: {e}", True)
            return None

    def _run(self):
        cap = None
        cam_key = None
        seq = 0
        seg = None
        rvm = None
        rvm_failed = False
        vcam = None
        vcam_key = None
        compositor = threading.Thread(target=self._compose_loop, daemon=True)
        compositor.start()
        while self.running:
            s = self.s
            key = (s.camera, s.width, s.height, s.fps)
            if key != cam_key:
                if cap is not None:
                    cap.close()
                cap = self._open_camera()
                cam_key = key
            if cap is None:
                time.sleep(0.5)
                cam_key = None  # tenta reabrir
                continue
            use_rvm = s.model == 2 and not rvm_failed
            if use_rvm and rvm is None:
                try:
                    rvm = RvmMatter()
                    self.matter_device = rvm.device
                except Exception as e:
                    rvm_failed = True
                    use_rvm = False
                    self.on_status(f"Modelo da GPU indisponível ({e}). Usando MediaPipe.", True)
            mp_model = s.model if s.model in (0, 1) else 0
            if not use_rvm and (seg is None or seg.model_id != mp_model):
                if seg is not None:
                    seg.close()
                seg = Segmenter(mp_model)
                self.matter_device = "CPU"

            want_vcam = (s.virtualcam, s.width, s.height, s.fps)
            if want_vcam != vcam_key:
                if vcam is not None:
                    self.vcam = None
                    time.sleep(0.05)  # deixa a composicao terminar um send() em andamento
                    vcam.close()
                    vcam = None
                    self.virtualcam_device = None
                if s.virtualcam:
                    vcam = self._open_virtualcam()
                self.vcam = vcam
                vcam_key = want_vcam

            cap.apply_exposure(s)
            frame, new_seq = cap.latest(seq)
            if frame is None or new_seq == seq:
                continue
            seq = new_seq
            if frame.shape[1] != s.width or frame.shape[0] != s.height:
                frame = cv2.resize(frame, (s.width, s.height))
            if s.mirror:
                frame = cv2.flip(frame, 1)

            if use_rvm:
                alpha, fgr = rvm.process(frame, s)
                job = (frame, alpha, fgr, True)
                self.matter_device = rvm.device
            else:
                job = (frame, seg.mask(frame, s), None, False)
            with self.job_cond:
                self.job = job
                self.job_cond.notify()

        with self.job_cond:
            self.job_cond.notify()
        compositor.join(timeout=2)
        if cap is not None:
            cap.close()
        if seg is not None:
            seg.close()
        if rvm is not None:
            rvm.close()
        if vcam is not None:
            vcam.close()

    def _compose_loop(self):
        """Segunda etapa da linha de montagem: roda em paralelo com a IA do proximo quadro."""
        bg = BackgroundSource()
        t0, n = time.time(), 0
        while self.running:
            with self.job_cond:
                self.job_cond.wait_for(lambda: self.job is not None or not self.running, 0.5)
                job, self.job = self.job, None
            if job is None:
                continue
            s = self.s
            frame, alpha, fgr, is_rvm = job
            fg = None
            if is_rvm:
                alpha, fg = rvm_finish(alpha, fgr, s)
            if s.cleanup:
                alpha = keep_main_subject(alpha, s.cleanup)
            if s.show_mask:
                out = cv2.cvtColor((alpha * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            elif s.bg_mode == "none":
                out = adjust_person(frame, s)
            else:
                person, alpha = place_person(adjust_person(frame if fg is None else fg, s), alpha, s)
                back = bg.get(frame, s)
                out = cv2.blendLinear(person, back, alpha, 1 - alpha)

            self.on_frame(out)
            vcam = self.vcam
            if vcam is not None:
                vcam.send(out)

            n += 1
            if time.time() - t0 >= 1:
                self.fps = n / (time.time() - t0)
                t0, n = time.time(), 0
        bg.close()
