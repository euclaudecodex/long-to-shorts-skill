#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["faster-whisper>=1.0", "numpy>=1.24", "imageio-ffmpeg>=0.4.9", "pillow>=10"]
# ///
"""Sistema de Cortes: acha os momentos virais de um vídeo longo e entrega cortes verticais prontos.

Comandos (rode com -h para ver as opções de cada um):
  analisar   <video>      acha os melhores momentos: analise.json, momentos.md, lista.json e quadros/
  lote       <lista.json> renderiza os cortes aprovados na lista, confere cada um e escreve o texto dos posts
  renderizar <video>      gera um corte 1080x1920 (título, legenda palavra a palavra, zoom, áudio a -14 LUFS)
  previa     <video>      mesmo quadro com cada estilo de legenda e de título, para escolher
  estilos                 lista os estilos de legenda e de título
  conferir   <mp4>        mede duração, resolução e volume e monta uma folha de quadros

Entrada: sempre um arquivo de vídeo no computador (live gravada, arquivo do programa de cortes, gravação do OBS).
Tempos aceitam segundos (754.2) ou relógio (00:12:34.2).
"""
import argparse, json, math, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estilos import (LEGENDAS, TITULOS, achar_fonte, emoji_png, emojis_automaticos,  # noqa: E402
                     fontes_usadas, montar_ass)

SR = 16000
W, H = 1080, 1920

# ---------------------------------------------------------------- utilidades

def ffmpeg_exe():
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg não encontrado. Instale com: pip install imageio-ffmpeg")
    return exe

FF = None

def ff(args, **kw):
    return subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **kw)

def info(video):
    """Duração (s), largura e altura, lidas do cabeçalho pelo próprio ffmpeg."""
    r = subprocess.run([FF, "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        sys.exit(f"Não consegui ler o vídeo: {video}")
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    w, h = (int(v[1]), int(v[2])) if v else (0, 0)
    rot = re.search(r"rotate\s*:\s*(-?\d+)", r.stderr)
    if rot and abs(int(rot[1])) in (90, 270):
        w, h = h, w
    return dur, w, h

def tempo(s):
    """'01:02:03.5', '02:03' ou '123.5' -> segundos."""
    s = str(s).strip()
    if ":" in s:
        p = [float(x) for x in s.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(p)))
    return float(s)

def relogio(t):
    t = max(0.0, t)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"

# ---------------------------------------------------------------- áudio

def ler_audio(video, ini=None, fim=None):
    """Áudio mono 16 kHz em int16 (lido em blocos para aguentar lives de horas)."""
    args = [FF, "-hide_banner", "-loglevel", "error"]
    if ini is not None:
        args += ["-ss", f"{ini:.3f}"]
    args += ["-i", str(video)]
    if fim is not None:
        args += ["-t", f"{fim - (ini or 0):.3f}"]
    args += ["-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE)
    partes = []
    while True:
        b = p.stdout.read(SR * 2 * 60)
        if not b:
            break
        partes.append(np.frombuffer(b, dtype=np.int16))
    p.wait()
    return np.concatenate(partes) if partes else np.zeros(0, np.int16)

def volume_por_segundo(a):
    n = len(a) // SR
    if n == 0:
        return np.zeros(0)
    x = a[: n * SR].astype(np.float32).reshape(n, SR) / 32768.0
    rms = np.sqrt((x ** 2).mean(axis=1))
    return 20 * np.log10(rms + 1e-6)

def cenas(video):
    """Trocas bruscas de imagem, olhando só os quadros-chave (rápido mesmo em live de horas)."""
    r = subprocess.run([FF, "-hide_banner", "-skip_frame", "nokey", "-i", str(video), "-an",
                        "-vf", "scale=160:-2,select='gt(scene,0.30)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace")
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]

# ---------------------------------------------------------------- transcrição

_MODELO = {}

def transcrever(audio_i16, offset, idioma, modelo):
    from faster_whisper import WhisperModel
    if modelo not in _MODELO:
        _MODELO[modelo] = WhisperModel(modelo, device="auto", compute_type="int8")
    m = _MODELO[modelo]
    x = audio_i16.astype(np.float32) / 32768.0
    segs, inf = m.transcribe(x, language=idioma, word_timestamps=True, vad_filter=True,
                             beam_size=5, condition_on_previous_text=False)
    palavras, frases = [], []
    for s in segs:
        frases.append({"s": round(s.start + offset, 2), "e": round(s.end + offset, 2), "t": s.text.strip()})
        for w in s.words or []:
            t = w.word.strip()
            if t:
                palavras.append({"w": t, "s": round(w.start + offset, 2), "e": round(w.end + offset, 2)})
    return palavras, frases, inf.language

# ---------------------------------------------------------------- pontuação

GATILHOS = [
    # português
    "meu deus", "nossa", "caraca", "caramba", "não acredito", "nao acredito", "olha isso", "olha só", "que isso",
    "socorro", "corre", "acabou", "ganhei", "perdi", "impossível", "absurdo", "inacreditável",
    "é sério", "mentira", "cuidado", "voou", "morreu", "bora", "eita", "uau", "rapaz", "olha o", "olha a",
    # inglês
    "oh my god", "omg", "no way", "bro what", "let's go", "lets go", "insane", "crazy", "wait what",
    "holy", "dude", "wow", "clip that", "clip it", "oh no",
    # espanhol
    "dios mío", "no puede ser", "increíble",
]
RISOS = re.compile(r"(k{3,}|(ha){2,}|(he){3,}|(ja){2,}|\[ris|\(ris|\[laugh|\(laugh|lol\b|lmao)", re.I)

def norm(t):
    return re.sub(r"[^\wà-úñ' ]", " ", t.lower())

def pontuar(dur, vol, cen, palavras):
    n = max(1, int(math.ceil(dur)))
    v = np.full(n, np.nan)
    v[: len(vol)] = vol[:n]
    v = np.nan_to_num(v, nan=np.nanmedian(vol) if len(vol) else -60)
    med = np.median(v)
    mad = np.median(np.abs(v - med)) * 1.4826 + 1e-3
    alto = np.clip((v - med) / mad, 0, 5) / 5                       # grito / explosão
    base = np.convolve(v, np.ones(5) / 5, mode="full")[:n]
    salto = np.clip(v - np.concatenate([[v[0]], base[:-1]]), 0, 15) / 15  # pico repentino
    troca = np.zeros(n)
    for t in cen:
        i = int(t)
        troca[max(0, i - 1): i + 2] += 1
    troca = np.clip(troca, 0, 3) / 3
    gat = np.zeros(n)
    fala = np.zeros(n)
    texto = " " + " ".join(norm(w["w"]) for w in palavras) + " "
    for i, w in enumerate(palavras):
        k = min(n - 1, int(w["s"]))
        fala[k] += 1
        janela = " " + norm(" ".join(x["w"] for x in palavras[i:i + 3])) + " "
        if any(janela.startswith(" " + g + " ") for g in GATILHOS):
            gat[k] += 1
        if "!" in w["w"] or "?!" in w["w"]:
            gat[k] += 0.5
        if RISOS.search(w["w"]):
            gat[k] += 1
    gat = np.clip(np.convolve(gat, np.ones(3), mode="same"), 0, 3) / 3
    fala = np.clip(np.convolve(fala, np.ones(5) / 5, mode="same"), 0, 4) / 4
    bruto = 0.35 * alto + 0.25 * salto + 0.25 * gat + 0.10 * troca + 0.05 * fala
    nota = np.convolve(bruto, np.ones(3) / 3, mode="same")
    partes = {"alto": alto, "salto": salto, "gatilho": gat, "troca": troca, "fala": fala}
    return nota, partes, (v - med)

def ajustar_inicio(t, frases, folga=5.0):
    c = [f["s"] for f in frases if abs(f["s"] - t) <= folga]
    return min(c, key=lambda x: abs(x - t)) if c else t

def ajustar_fim(t, frases, minimo, folga=5.0):
    c = [f["e"] for f in frases if abs(f["e"] - t) <= folga and f["e"] >= minimo]
    return min(c, key=lambda x: abs(x - t)) if c else t

def motivos(i, partes, desvio_db, palavras, ini, fim):
    m = []
    if partes["alto"][i] > 0.5:
        m.append(f"volume {desvio_db[i]:+.0f} dB acima do normal (grito/explosão)")
    if partes["salto"][i] > 0.4:
        m.append("pico repentino de som")
    achadas = sorted({g for g in GATILHOS for w in [" " + norm(" ".join(x["w"] for x in palavras if ini <= x["s"] <= fim)) + " "]
                      if f" {g} " in w})
    if achadas:
        m.append("falas de reação: " + ", ".join(f'"{a}"' for a in achadas[:6]))
    if any(RISOS.search(x["w"]) for x in palavras if ini <= x["s"] <= fim):
        m.append("risadas")
    if partes["troca"][i] > 0.3:
        m.append("mudança brusca de imagem")
    return m or ["pico combinado de som e fala"]

# ---------------------------------------------------------------- analisar

def cmd_analisar(a):
    video = Path(a.video).resolve()
    pasta = Path(a.pasta or video.with_suffix("").as_posix() + "_cortes")
    (pasta / "quadros").mkdir(parents=True, exist_ok=True)
    dur, w, h = info(video)
    print(f"Vídeo: {video.name} | {relogio(dur)} | {w}x{h}")

    print("1/4 Lendo o áudio...")
    audio = ler_audio(video)
    vol = volume_por_segundo(audio)
    print("2/4 Procurando trocas de cena...")
    cen = cenas(video)

    # vídeos longos: transcreve só em volta dos picos de som (minutos em vez de horas)
    rapido = (dur > 15 * 60 and not a.completo)
    if rapido:
        pre, _, _ = pontuar(dur, vol, cen, [])
        regioes, nota_tmp = [], pre.copy()
        for _ in range(max(8, a.cortes * 3)):
            p = int(np.argmax(nota_tmp))
            if nota_tmp[p] <= 0:
                break
            regioes.append([max(0, p - 60), min(dur, p + 45)])
            nota_tmp[max(0, p - 90): p + 90] = -1
        regioes.sort()
        unidas = []
        for r in regioes:
            if unidas and r[0] <= unidas[-1][1]:
                unidas[-1][1] = max(unidas[-1][1], r[1])
            else:
                unidas.append(r)
        regioes = unidas
    else:
        regioes = [[0, dur]]
    total = sum(r[1] - r[0] for r in regioes)
    print(f"3/4 Transcrevendo {relogio(total)} de fala (modelo {a.modelo})...")
    palavras, frases, idioma = [], [], a.idioma
    for r0, r1 in regioes:
        pw, pf, idioma = transcrever(audio[int(r0 * SR): int(r1 * SR)], r0, a.idioma, a.modelo)
        palavras += pw
        frases += pf
    del audio

    print("4/4 Pontuando momentos...")
    nota, partes, desvio = pontuar(dur, vol, cen, palavras)
    if rapido:  # só concorre quem foi transcrito
        mascara = np.zeros_like(nota, dtype=bool)
        for r0, r1 in regioes:
            mascara[int(r0): int(r1)] = True
        nota = np.where(mascara, nota, -1)
    alvo = min(max(a.alvo, a.min), a.max)
    cands, livre = [], nota.copy()
    while len(cands) < a.cortes:
        p = int(np.argmax(livre))
        if livre[p] <= 0:
            break
        ini = ajustar_inicio(max(0.0, p - 0.62 * alvo), frases)
        fim = ajustar_fim(min(dur, ini + alvo), frases, minimo=p + 3)
        if fim - ini < a.min:
            fim = min(dur, ini + a.min)
        if fim - ini > a.max:
            fim = ini + a.max
        livre[max(0, int(ini) - 5): int(fim) + 5] = -1
        for c in cands:  # dois cortes nunca repetem o mesmo trecho: apara o novo
            if ini < c["fim"] and fim > c["inicio"]:
                if p < c["inicio"]:
                    fim = min(fim, c["inicio"])
                else:
                    ini = max(ini, c["fim"])
        if fim - ini < a.min or not (ini <= p <= fim):
            continue
        trecho = nota[int(ini): int(fim) + 1]
        trecho = trecho[trecho >= 0]
        top = np.sort(trecho)[-max(1, len(trecho) // 5):].mean() if len(trecho) else 0
        cands.append({"inicio": round(ini, 2), "fim": round(fim, 2), "pico": float(p),
                      "forca": float(0.6 * nota[p] + 0.4 * top),
                      "motivos": motivos(p, partes, desvio, palavras, ini, fim)})
    if not cands:
        sys.exit("Nenhum momento forte encontrado. Tente --completo ou um trecho com mais ação.")
    maior = max(c["forca"] for c in cands)
    for c in cands:
        c["nota"] = int(round(100 * c["forca"] / maior))
    cands.sort(key=lambda c: -c["nota"])

    for i, c in enumerate(cands, 1):
        c["id"] = i
        tiras = []
        for j, t in enumerate([c["inicio"] + 0.5, c["pico"] - 1, c["pico"] + 0.5, c["fim"] - 1]):
            f = pasta / "quadros" / f"_t{j}.jpg"
            ff(["-ss", f"{max(0, t):.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:360", "-q:v", "4", str(f)])
            tiras.append(f)
        c["quadros"] = f"quadros/corte_{i:02d}.jpg"
        ff([x for f in tiras for x in ("-i", str(f))] + ["-filter_complex", "".join(f"[{k}:v]" for k in range(4)) + "hstack=4",
            "-q:v", "4", str(pasta / c["quadros"])])
        for f in tiras:
            f.unlink(missing_ok=True)

    dados = {"video": str(video), "duracao": dur, "largura": w, "altura": h, "idioma": idioma,
             "modo": "rapido (só em volta dos picos)" if rapido else "completo",
             "cortes": cands, "frases": frases, "palavras": palavras}
    (pasta / "analise.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")

    linhas = [f"# Momentos de {video.name}", "",
              f"Duração {relogio(dur)} · {w}x{h} · idioma {idioma} · transcrição {dados['modo']}", "",
              "A nota (0–100) é relativa a este vídeo: 100 = o momento mais forte encontrado nele.", ""]
    for c in cands:
        linhas += [f"## Corte {c['id']} — nota {c['nota']} — {relogio(c['inicio'])} → {relogio(c['fim'])} "
                   f"({c['fim'] - c['inicio']:.0f} s) — pico em {relogio(c['pico'])}",
                   "Por quê: " + "; ".join(c["motivos"]),
                   f"Quadros (início · antes do pico · pico · fim): {c['quadros']}", "", "```"]
        for f in frases:
            if f["e"] >= c["inicio"] - 8 and f["s"] <= c["fim"] + 5:
                marca = ">>>" if f["s"] <= c["pico"] <= f["e"] + 1 else ("   " if c["inicio"] <= f["s"] <= c["fim"] else " · ")
                linhas.append(f"{marca} [{relogio(f['s'])}] {f['t']}")
        linhas += ["```", ""]
    (pasta / "momentos.md").write_text("\n".join(linhas), encoding="utf-8")

    # proposta para o usuário aprovar: o Claude preenche título, post e hashtags e marca "aprovado"
    lista = {"video": str(video),
             "padrao": {"layout": "auto", "legenda": "destaque", "titulo_estilo": "caixa", "camera": None,
                        "camera_embaixo": False, "marca": ""},
             "cortes": [{"id": c["id"], "aprovado": False, "nota": c["nota"], "inicio": relogio(c["inicio"]),
                         "fim": relogio(c["fim"]), "zoom": [relogio(c["pico"])], "titulo": "", "post": "",
                         "hashtags": "", "motivos": c["motivos"]} for c in cands]}
    lp = pasta / "lista.json"
    if lp.exists() and not a.refazer_lista:
        print(f"(lista.json já existia e foi mantida; use --refazer-lista para sobrescrever)")
    else:
        lp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nPronto: {len(cands)} momentos em {pasta}")
    for c in cands:
        print(f"  #{c['id']}  nota {c['nota']:3d}  {relogio(c['inicio'])} → {relogio(c['fim'])}  {c['motivos'][0]}")

# ---------------------------------------------------------------- renderizar

def expr_zoom(tempos, forca):
    if not tempos:
        return "1"
    termos = [f"{forca}*clip((T-{t:.3f})/0.15,0,1)*clip(({t + 1.6:.3f}-T)/0.35,0,1)" for t in tempos]
    return ("1+" + "+".join(termos)).replace("T", "(on/30)")

def palavras_do_trecho(a, video, ini, fim):
    """Palavras com tempo relativo ao corte: do JSON (se cobrir o trecho) ou transcrevendo só o corte."""
    if a.sem_legenda:
        return []
    if a.palavras and Path(a.palavras).is_file():
        bruto = json.loads(Path(a.palavras).read_text(encoding="utf-8"))
        if isinstance(bruto, dict):  # analise.json: tempos do vídeo inteiro
            pw = [{"w": x["w"], "s": round(x["s"] - ini, 2), "e": round(x["e"] - ini, 2)}
                  for x in bruto["palavras"] if ini - 0.1 <= x["s"] < fim]
            if pw:
                return pw
        else:                        # .palavras.json de um corte (já corrigido)
            return bruto
    print("Transcrevendo o trecho para a legenda...")
    return transcrever(ler_audio(video, ini, fim), 0.0, a.idioma, a.modelo)[0]

def posicoes(layout, w, h, a):
    """Monta o grafo de vídeo do layout e devolve (grafo, y_legenda, {posição do título: y})."""
    fx = min(max(a.foco_x, 0.0), 1.0)
    if layout == "blur":
        fg_h = min(int(round(W * h / w * a.aproximar / 2) * 2), 1400)
        y_fg = (H - fg_h) // 2 - 40
        grafo = (f"[0:v]fps=30,setsar=1,split[a][b];"
                 f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,eq=brightness=-0.18:saturation=1.2[bg];"
                 f"[b]scale=-2:{fg_h},crop={W}:{fg_h}:(iw-{W})*{fx}:0[fg];[bg][fg]overlay=0:{y_fg}[v0]")
        return grafo, min(1440, y_fg + fg_h + 110), {"topo": max(230, y_fg - 250), "meio": y_fg, "centro": H * 42 // 100}
    if layout == "crop":
        grafo = (f"[0:v]fps=30,setsar=1,scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:(iw-{W})*{fx}:(ih-{H})/2[v0]")
        return grafo, 1260, {"topo": 260, "meio": 780, "centro": H * 42 // 100}
    if layout == "split":
        if not a.camera:
            sys.exit("Layout split precisa de --camera x,y,larg,alt (frações de 0 a 1 do quadro da webcam)")
        cx, cy, cw, ch = [float(v) for v in a.camera.split(",")]
        cam_h = int(H * min(max(a.proporcao_camera, 0.25), 0.6)) // 2 * 2
        jogo_h = H - cam_h
        cam = (f"[a]crop=iw*{cw}:ih*{ch}:iw*{cx}:ih*{cy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,"
               f"crop={W}:{cam_h}[cam]")
        jogo = f"[b]scale=-2:{jogo_h},crop={W}:{jogo_h}:(iw-{W})*{fx}:0[jogo]"
        if a.camera_embaixo:
            grafo = f"[0:v]fps=30,setsar=1,split[a][b];{cam};{jogo};[jogo][cam]vstack[v0]"
            emenda, y_leg, topo = jogo_h, min(1440, jogo_h - 160), 240
        else:
            grafo = f"[0:v]fps=30,setsar=1,split[a][b];{cam};{jogo};[cam][jogo]vstack[v0]"
            emenda, y_leg, topo = cam_h, 1340, 240
        return grafo, y_leg, {"topo": topo, "meio": emenda, "centro": H * 42 // 100}
    sys.exit(f"Layout desconhecido: {layout}")

def render(a):
    """Renderiza um corte (ou só um quadro, com a.quadro) a partir das opções do comando renderizar."""
    video = Path(a.video).resolve()
    dur_v, w, h = info(video)
    ini, fim = tempo(a.inicio), min(tempo(a.fim), dur_v)
    if not (0 <= ini < fim):
        sys.exit(f"Trecho inválido: {a.inicio}–{a.fim} (vídeo tem {dur_v:.1f} s)")
    dur = fim - ini
    if a.legenda not in LEGENDAS:
        sys.exit(f"Estilo de legenda inválido: {a.legenda}. Opções: {', '.join(LEGENDAS)}")
    if a.titulo_estilo not in TITULOS:
        sys.exit(f"Estilo de título inválido: {a.titulo_estilo}. Opções: {', '.join(TITULOS)}")
    quadro = tempo(a.quadro) - ini if a.quadro else None
    saida = Path(a.saida or f"{video.stem}_corte_{int(ini)}.{'jpg' if quadro is not None else 'mp4'}").resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    trab = Path(tempfile.mkdtemp(prefix="corte_"))

    palavras = [x for x in palavras_do_trecho(a, video, ini, fim) if 0 <= x["s"] < dur]
    desloc = 0.0
    if quadro is not None and quadro > 2:  # quadro único: decodifica só 1,5 s antes dele (bem mais rápido)
        desloc = quadro - 1.5
        ini, dur, quadro = ini + desloc, dur - desloc, 1.5
        palavras = [{**x, "s": round(x["s"] - desloc, 2), "e": round(x["e"] - desloc, 2)} for x in palavras if x["e"] > desloc]
    if quadro is None:
        saida.with_suffix(".palavras.json").write_text(json.dumps(palavras, ensure_ascii=False, indent=0), encoding="utf-8")

    layout = a.layout
    if layout == "auto":
        layout = "split" if a.camera else ("crop" if h >= w else "blur")
    grafo, y_legenda, ys = posicoes(layout, w, h, a)
    y_titulo = ys[TITULOS[a.titulo_estilo]["pos"]]

    zooms = [tempo(z) - ini for z in str(a.zoom).split(",") if str(z).strip()] if a.zoom else []
    zooms = [z for z in zooms if 0 <= z < dur]
    if zooms:
        grafo += (f";[v0]scale={W * 2}:{H * 2},zoompan=z='{expr_zoom(zooms, a.forca_zoom)}':"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30[v1]")
    else:
        grafo += ";[v0]null[v1]"

    for nome in fontes_usadas(a.legenda, a.titulo_estilo, a.fonte):
        f = achar_fonte(nome)
        if f:
            shutil.copy(f, trab / f.name)
        else:
            print(f"Aviso: fonte '{nome}' não encontrada; o libass vai usar uma parecida.")
    titulo = a.titulo if a.titulo_normal else a.titulo.upper()
    ass = montar_ass(palavras, dur, legenda=a.legenda, titulo=titulo, titulo_estilo=a.titulo_estilo,
                     y_legenda=y_legenda, y_titulo=y_titulo, marca=a.marca, cor_marca=a.cor_marca, fonte=a.fonte,
                     tam_legenda=a.tam_legenda, caixa_alta=(False if a.legenda_normal else None),
                     por_vez=a.palavras_por_vez, cor_destaque=a.cor_destaque, dur_titulo=a.titulo_dur)
    (trab / "legenda.ass").write_text(ass, encoding="utf-8")
    grafo += ";[v1]ass=legenda.ass:fontsdir=.[v2]"

    # emojis coloridos (estilo emoji ou --emojis "tempo:😱,tempo:🔥")
    entradas, atual = [], "v2"
    pedidos = []
    if a.emojis:
        for par in a.emojis.split(","):
            t, e = par.split(":", 1)
            pedidos.append((tempo(t) - ini, e.strip()))
    elif LEGENDAS[a.legenda].get("emoji"):
        pedidos = emojis_automaticos(palavras)
        if not pedidos and zooms:  # nenhuma palavra-chave: pelo menos um emoji no pico
            pedidos = [(zooms[0], "🤯")]
    for k, (t, e) in enumerate(p for p in pedidos if 0 <= p[0] < dur):
        png = trab / f"emoji{k}.png"
        if not emoji_png(e, png):
            print("Aviso: sem fonte de emoji colorido no sistema; emojis ignorados.")
            break
        entradas += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
        idx = len(entradas) // 6
        grafo += (f";[{atual}][{idx}:v]overlay=x=(W-w)/2:y={y_legenda - 175}-h/2:"
                  f"enable='between(t,{t:.2f},{min(dur, t + 1.3):.2f})'[e{k}]")
        atual = f"e{k}"
    grafo += f";[{atual}]null[v]"

    base = [FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(video), *entradas]
    if quadro is not None:
        cmd = base + ["-filter_complex", grafo, "-map", "[v]", "-ss", f"{max(0.0, quadro):.3f}", "-frames:v", "1",
                      "-q:v", "3", str(saida)]
    else:
        fade = min(0.08, dur / 4)
        grafo += (f";[0:a]aresample=48000,afade=t=in:d={fade},afade=t=out:st={dur - fade:.3f}:d={fade},"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[au]")
        print(f"Renderizando {relogio(ini)} → {relogio(fim)} ({dur:.1f} s) · layout {layout} · legenda {a.legenda} · "
              f"título {a.titulo_estilo}...")
        cmd = base + ["-filter_complex", grafo, "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-preset", a.preset,
                      "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", str(saida)]
    subprocess.run(cmd, check=True, cwd=trab)
    shutil.rmtree(trab, ignore_errors=True)
    return saida

def cmd_renderizar(a):
    saida = render(a)
    print(f"Pronto: {saida}")
    if not a.quadro:
        print(f"Palavras da legenda (corrija e rode de novo com --palavras): {saida.with_suffix('.palavras.json')}")

# ---------------------------------------------------------------- lote (lista aprovada)

def opcoes_render(parser_render, video, item, padrao):
    """Monta as opções do renderizar para um item da lista (padrão da lista + campos do item)."""
    a = parser_render.parse_args([str(video), "--inicio", str(item["inicio"]), "--fim", str(item["fim"])])
    campos = {**padrao, **{k: v for k, v in item.items() if v not in (None, "")}}
    for k, v in campos.items():
        k = k.replace("-", "_")
        if k == "zoom" and isinstance(v, list):
            v = ",".join(str(x) for x in v)
        if hasattr(a, k) and k not in ("video", "inicio", "fim"):
            setattr(a, k, v)
    return a

def apelido(texto, i):
    t = re.sub(r"[^a-z0-9]+", "-", texto.lower().translate(str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc"))).strip("-")
    return f"{i:02d}-{t[:40] or 'corte'}"

def cmd_lote(a, parser_render):
    lista_p = Path(a.lista).resolve()
    lista = json.loads(lista_p.read_text(encoding="utf-8"))
    video = Path(lista["video"])
    padrao = lista.get("padrao", {})
    analise = lista_p.parent / "analise.json"
    itens = [c for c in lista["cortes"] if a.todos or c.get("aprovado")]
    if not itens:
        sys.exit("Nenhum corte aprovado na lista. Marque \"aprovado\": true nos cortes que o usuário escolheu.")
    pasta = Path(a.saida or video.parent / "cortes")
    pasta.mkdir(parents=True, exist_ok=True)
    resumo = [f"# Cortes de {video.name}", ""]
    for i, item in enumerate(itens, 1):
        if analise.exists() and "palavras" not in item:
            item = {**item, "palavras": str(analise)}
        op = opcoes_render(parser_render, video, item, padrao)
        nome = apelido(item.get("titulo") or f"corte {item.get('id', i)}", i)
        op.saida = str(pasta / f"{nome}.mp4")
        print(f"\n[{i}/{len(itens)}] {item.get('titulo', '')}")
        mp4 = render(op)
        conf = conferir(mp4)
        texto = [item.get("titulo", ""), "", item.get("post", ""), item.get("hashtags", "")]
        mp4.with_suffix(".txt").write_text("\n".join(texto).strip() + "\n", encoding="utf-8")
        resumo += [f"## {i}. {item.get('titulo', '')}", f"- Arquivo: `{mp4.name}` · {conf['duracao']:.0f} s · "
                   f"{conf['volume']} LUFS · {'ok' if conf['ok'] else 'conferir'}",
                   f"- Trecho: {relogio(tempo(item['inicio']))} → {relogio(tempo(item['fim']))}",
                   f"- Post: {item.get('post', '')} {item.get('hashtags', '')}", f"- Folha: `{Path(conf['folha']).name}`", ""]
    (pasta / "resumo.md").write_text("\n".join(resumo), encoding="utf-8")
    print(f"\n{len(itens)} cortes prontos em {pasta} (resumo.md com os textos de cada post)")

# ---------------------------------------------------------------- prévia dos estilos

def folha(imagens, saida, cols, lw=270):
    lh = lw * 16 // 9
    lay = "|".join(f"{(i % cols) * lw}_{(i // cols) * lh}" for i in range(len(imagens)))
    ff([x for f in imagens for x in ("-i", str(f))] + ["-filter_complex",
       "".join(f"[{i}:v]scale={lw}:{lh}[s{i}];" for i in range(len(imagens))) + "".join(f"[s{i}]" for i in range(len(imagens)))
       + f"xstack=inputs={len(imagens)}:layout={lay}", "-frames:v", "1", "-q:v", "3", str(saida)])

def cmd_previa(a, parser_render):
    """Mesmo quadro com cada estilo de legenda e de título, lado a lado, para o usuário escolher."""
    base = parser_render.parse_args([a.video, "--inicio", a.inicio, "--fim", a.fim, "--preset", "veryfast"])
    for k, v in vars(a).items():
        if hasattr(base, k) and k not in ("video", "inicio", "fim", "quadro", "saida", "f", "cmd"):
            setattr(base, k, v)
    ini, fim = tempo(a.inicio), tempo(a.fim)
    if not a.palavras:  # transcreve uma vez só e reaproveita nos 11 quadros
        pw = transcrever(ler_audio(Path(a.video), ini, fim), 0.0, a.idioma, a.modelo)[0]
        tmp = Path(tempfile.mkdtemp(prefix="previa_")) / "palavras.json"
        tmp.write_text(json.dumps(pw, ensure_ascii=False), encoding="utf-8")
        base.palavras = str(tmp)
    else:
        pw = palavras_do_trecho(base, Path(a.video), ini, fim)
    if a.quadro:
        t = tempo(a.quadro)
    else:  # meio de uma fala com pelo menos 3 palavras perto do centro do corte
        meio = (fim - ini) / 2
        t = ini + min((x["s"] + 0.15 for x in pw), key=lambda s: abs(s - meio), default=meio)
    pasta = Path(a.saida or Path(a.video).with_suffix("").as_posix() + "_previa")
    pasta.mkdir(parents=True, exist_ok=True)
    for grupo, catalogo, campo in (("legendas", LEGENDAS, "legenda"), ("titulos", TITULOS, "titulo_estilo")):
        imgs = []
        for nome in catalogo:
            op = argparse.Namespace(**vars(base))
            setattr(op, campo, nome)
            op.quadro = str(ini + 0.6) if nome == "relampago" else str(t)  # o relâmpago só aparece no começo
            if nome == "emoji":
                op.emojis = f"{t - 0.2}:🤯"  # garante um emoji no quadro de exemplo
            op.saida = str(pasta / f"{grupo}_{nome}.jpg")
            imgs.append(render(op))
        folha(imgs, pasta / f"previa_{grupo}.jpg", cols=len(imgs))
        print(f"{grupo}: " + " · ".join(catalogo) + f"  →  {pasta / f'previa_{grupo}.jpg'}")

def cmd_estilos(a):
    print("Legendas (--legenda):")
    for k, v in LEGENDAS.items():
        print(f"  {k:10s} {v['desc']}")
    print("Títulos (--titulo-estilo):")
    for k, v in TITULOS.items():
        print(f"  {k:10s} {v['desc']}")

# ---------------------------------------------------------------- conferir

def conferir(mp4):
    mp4 = Path(mp4).resolve()
    dur, w, h = info(mp4)
    r = subprocess.run([FF, "-hide_banner", "-i", str(mp4), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace")
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    saida_folha = mp4.with_suffix(".folha.jpg")
    tmp = Path(tempfile.mkdtemp(prefix="folha_"))
    for i in range(12):
        ff(["-ss", f"{dur * (i + 0.5) / 12:.2f}", "-i", str(mp4), "-frames:v", "1", str(tmp / f"{i:02d}.jpg")])
    folha(sorted(tmp.glob("*.jpg")), saida_folha, cols=6, lw=240)
    shutil.rmtree(tmp, ignore_errors=True)
    vol = float(lufs[-1]) if lufs else None
    ok = (w, h) == (W, H) and vol is not None and abs(vol + 14) <= 1.5 and 5 <= dur <= 90
    return {"arquivo": str(mp4), "duracao": dur, "largura": w, "altura": h, "volume": vol, "folha": str(saida_folha), "ok": ok}

def cmd_conferir(a):
    c = conferir(a.mp4)
    print(f"Arquivo:   {Path(c['arquivo']).name}")
    print(f"Duração:   {c['duracao']:.1f} s {'(ok)' if 10 <= c['duracao'] <= 90 else '(atenção: fora de 10–90 s)'}")
    print(f"Resolução: {c['largura']}x{c['altura']} {'(ok)' if (c['largura'], c['altura']) == (W, H) else '(esperado 1080x1920)'}")
    print(f"Volume:    {c['volume']} LUFS {'(ok)' if c['volume'] is not None and abs(c['volume'] + 14) <= 1.5 else '(esperado -14)'}")
    print(f"Folha de quadros: {c['folha']}")

# ---------------------------------------------------------------- CLI

SO_ARQUIVO = ("O Sistema de Cortes trabalha com o arquivo de vídeo no seu computador: a sua live gravada, o arquivo "
              "que o programa de cortes te enviou ou a gravação do OBS. Ele não baixa vídeo de link.")

def opcoes_de_corte(s):
    """Opções comuns a renderizar e previa (layout, estilos, legenda)."""
    s.add_argument("--titulo", default="", help="texto do título (vira caixa alta)")
    s.add_argument("--titulo-estilo", default="caixa", help="caixa, meio, faixa, contorno, relampago (veja: estilos)")
    s.add_argument("--titulo-dur", type=float, default=0, help="segundos com título na tela (0 = o corte todo)")
    s.add_argument("--titulo-normal", action="store_true", help="não converter o título para caixa alta")
    s.add_argument("--legenda", default="destaque", help="destaque, beasty, karaoke, caixa, minimal, emoji (veja: estilos)")
    s.add_argument("--layout", default="auto", choices=["auto", "blur", "crop", "split"])
    s.add_argument("--camera", help="webcam para o layout split: x,y,larg,alt em frações (ex.: 0,0.65,0.25,0.35)")
    s.add_argument("--camera-embaixo", action="store_true", help="no split, webcam embaixo e jogo em cima")
    s.add_argument("--proporcao-camera", type=float, default=0.5, help="altura da webcam no split (0.25–0.6; 0.5 = meio a meio)")
    s.add_argument("--aproximar", type=float, default=1.25, help="zoom fixo do vídeo no layout blur (1.0–1.8)")
    s.add_argument("--foco-x", type=float, default=0.5, help="0 = esquerda, 0.5 = centro, 1 = direita")
    s.add_argument("--marca", default="", help="@ do perfil, discreto no rodapé")
    s.add_argument("--cor-marca", default="#FF2D9B", help="cor da faixa no título 'faixa' (hex RGB)")
    s.add_argument("--palavras", help="JSON de palavras já transcritas (analise.json ou .palavras.json corrigido)")
    s.add_argument("--idioma", default=None)
    s.add_argument("--modelo", default="small")

def main():
    global FF
    for fluxo in (sys.stdout, sys.stderr):  # console do Windows não é UTF-8 por padrão
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    FF = ffmpeg_exe()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analisar", help="acha os momentos com mais cara de viral")
    s.add_argument("video")
    s.add_argument("--pasta", help="onde gravar (padrão: <video>_cortes/)")
    s.add_argument("--cortes", type=int, default=5, help="quantos momentos sugerir (5)")
    s.add_argument("--alvo", type=float, default=35, help="duração alvo de cada corte em s (35)")
    s.add_argument("--min", type=float, default=15)
    s.add_argument("--max", type=float, default=60)
    s.add_argument("--idioma", default=None, help="pt, en, es... (padrão: detecta)")
    s.add_argument("--modelo", default="small", help="tiny/base/small/medium/large-v3 (small)")
    s.add_argument("--completo", action="store_true", help="transcreve o vídeo inteiro mesmo se for longo")
    s.add_argument("--refazer-lista", action="store_true", help="sobrescreve o lista.json existente")
    s.set_defaults(f=cmd_analisar)

    rp = sub.add_parser("renderizar", help="gera um corte vertical pronto")
    rp.add_argument("video")
    rp.add_argument("--inicio", required=True)
    rp.add_argument("--fim", required=True)
    rp.add_argument("--saida")
    opcoes_de_corte(rp)
    rp.add_argument("--zoom", default="", help="tempos (do vídeo original) para o zoom de impacto, separados por vírgula")
    rp.add_argument("--forca-zoom", type=float, default=0.18)
    rp.add_argument("--emojis", default="", help='emojis manuais: "tempo:😱,tempo:🔥" (tempos do vídeo original)')
    rp.add_argument("--sem-legenda", action="store_true")
    rp.add_argument("--legenda-normal", action="store_true", help="legenda sem caixa alta")
    rp.add_argument("--palavras-por-vez", type=int, default=None)
    rp.add_argument("--fonte", default=None, help="troca a fonte da legenda")
    rp.add_argument("--tam-legenda", type=int, default=None)
    rp.add_argument("--cor-destaque", default=None, help="cor da palavra falada (hex RGB)")
    rp.add_argument("--quadro", default=None, help="em vez do vídeo, salva só o quadro desse tempo (jpg)")
    rp.add_argument("--preset", default="medium", help="velocidade do x264 (veryfast para testes)")
    rp.set_defaults(f=cmd_renderizar)

    s = sub.add_parser("lote", help="renderiza os cortes aprovados no lista.json")
    s.add_argument("lista")
    s.add_argument("--saida", help="pasta dos cortes (padrão: <pasta do vídeo>/cortes)")
    s.add_argument("--todos", action="store_true", help="renderiza todos, mesmo sem aprovado=true")
    s.set_defaults(f=lambda a: cmd_lote(a, rp))

    s = sub.add_parser("previa", help="mostra o mesmo quadro em cada estilo de legenda e de título")
    s.add_argument("video")
    s.add_argument("--inicio", required=True)
    s.add_argument("--fim", required=True)
    s.add_argument("--quadro", default=None, help="tempo do quadro (padrão: uma fala no meio do trecho)")
    s.add_argument("--saida", help="pasta (padrão: <video>_previa/)")
    opcoes_de_corte(s)
    s.set_defaults(f=lambda a: cmd_previa(a, rp))

    s = sub.add_parser("estilos", help="lista os estilos de legenda e de título")
    s.set_defaults(f=cmd_estilos)

    s = sub.add_parser("conferir", help="checa duração, resolução e volume e monta folha de quadros")
    s.add_argument("mp4")
    s.set_defaults(f=cmd_conferir)

    a = p.parse_args()
    entrada = getattr(a, "video", None) or getattr(a, "mp4", None) or getattr(a, "lista", None)
    if entrada is not None:
        if re.match(r"^(https?:|www\.)", entrada.strip(), re.I):
            sys.exit(SO_ARQUIVO)
        if not Path(entrada).is_file():
            sys.exit(f"Arquivo não encontrado: {entrada}" + ("" if a.cmd == "lote" else f"\n{SO_ARQUIVO}"))
    a.f(a)

if __name__ == "__main__":
    main()
