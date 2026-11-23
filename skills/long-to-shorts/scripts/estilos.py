"""Estilos de legenda e de título (ASS/libass) e emojis coloridos (Pillow) do Sistema de Cortes."""
import math, os, re, sys
from pathlib import Path

W, H = 1080, 1920

# ---------------------------------------------------------------- catálogo

LEGENDAS = {
    "destaque": dict(desc="caixa alta branca, palavra falada em amarelo (padrão)", fonte="Arial Black", tam=82,
                     caixa_alta=True, por_vez=3, borda=7, sombra=3, cor="#FFFFFF", ativa="#FFE600", modo="ativa"),
    "beasty":   dict(desc="letra grossa colorida que pula, cada bloco numa cor", fonte="Impact", tam=112,
                     caixa_alta=True, por_vez=2, borda=9, sombra=5, ciclo=["#39FF14", "#FF3131", "#FFE600", "#00E5FF"],
                     modo="beasty"),
    "karaoke":  dict(desc="frase inteira; a palavra falada vai acendendo", fonte="Arial", tam=64, caixa_alta=False,
                     por_vez=6, borda=4, sombra=2, cor="#FFFFFF", ativa="#FFE600", modo="karaoke"),
    "caixa":    dict(desc="palavras em tarja preta, a falada em rosa", fonte="Arial Black", tam=70, caixa_alta=True,
                     por_vez=3, borda=14, sombra=0, cor="#FFFFFF", fundo="#111111", ativa="#FF2D9B", modo="caixa"),
    "minimal":  dict(desc="discreta, sem cor e sem caixa alta (podcast, aula)", fonte="Arial", tam=58,
                     caixa_alta=False, por_vez=4, borda=0, sombra=3, cor="#FFFFFF", modo="simples"),
    "emoji":    dict(desc="destaque + emoji colorido sobre as palavras-chave", fonte="Arial Black", tam=82,
                     caixa_alta=True, por_vez=3, borda=7, sombra=3, cor="#FFFFFF", ativa="#FFE600", modo="ativa",
                     emoji=True),
}

TITULOS = {
    "caixa":     dict(desc="faixa branca no topo, letra preta (padrão)", fonte="Arial Black", tam=62, pos="topo",
                      caixa=True, cor="#111111", fundo="#FFFFFF"),
    "meio":      dict(desc="faixa branca no meio: na emenda câmera/jogo ou na borda do vídeo", fonte="Arial Black",
                      tam=56, pos="meio", caixa=True, cor="#111111", fundo="#FFFFFF"),
    "faixa":     dict(desc="faixa na cor da marca, letra branca", fonte="Arial Black", tam=62, pos="topo", caixa=True,
                      cor="#FFFFFF", fundo=None),
    "contorno":  dict(desc="letra branca grande com contorno, sem caixa", fonte="Arial Black", tam=80, pos="topo",
                      caixa=False, cor="#FFFFFF", fundo="#000000"),
    "relampago": dict(desc="aparece grande no centro nos 3 primeiros segundos e some", fonte="Arial Black", tam=92,
                      pos="centro", caixa=True, cor="#111111", fundo="#FFFFFF", dur=3.0),
}

FONTES = {"Arial Black": "ariblk.ttf", "Impact": "impact.ttf", "Arial": "arialbd.ttf"}
FONTES_MAC = {"Arial Black": "Arial Black.ttf", "Impact": "Impact.ttf", "Arial": "Arial Bold.ttf"}

# ---------------------------------------------------------------- utilidades

def pastas_de_fontes():
    return [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
            Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts"),
            Path.home() / "Library/Fonts", Path("/usr/share/fonts"), Path.home() / ".fonts",
            Path(__file__).resolve().parent.parent / "fontes"]

def achar_fonte(nome):
    alvos = {FONTES.get(nome, nome).lower(), FONTES_MAC.get(nome, nome).lower()}
    for d in pastas_de_fontes():
        if d.exists():
            for p in d.rglob("*"):
                if p.name.lower() in alvos:
                    return p
    return None

def cor(hex_rgb, alfa="00"):
    h = hex_rgb.lstrip("#")
    return f"&H{alfa}{h[4:6]}{h[2:4]}{h[0:2]}&".upper()

def esc(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")")

def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

def quebrar(texto, max_chars):
    """Quebra em linhas de tamanho parecido (evita 'TÍTULO LONGO EM 2 / SEGUNDOS')."""
    ps = texto.split()
    n = max(1, math.ceil(len(texto) / max_chars))
    linhas = [texto]
    for _ in range(4):
        alvo = len(texto) / n
        linhas, atual = [], ""
        for p in ps:
            cand = (atual + " " + p).strip()
            if atual and len(linhas) < n - 1 and abs(len(cand) - alvo) > abs(len(atual) - alvo):
                linhas.append(atual)
                atual = p
            else:
                atual = cand
        linhas.append(atual)
        if max(len(l) for l in linhas) <= max_chars + 2:
            return linhas
        n += 1
    return linhas

def grupos(palavras, maximo):
    g, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(w)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        if len(atual) >= maximo or re.search(r"[.!?,;:]$", w["w"]) or prox is None or prox["s"] - w["e"] > 0.45:
            g.append(atual)
            atual = []
    return g

def linha_estilo(nome, fonte, tam, prim, contorno, fundo, borda_tipo, borda, sombra):
    return (f"Style: {nome},{fonte},{tam},{prim},{prim},{contorno},{fundo},-1,0,0,0,100,100,0,0,"
            f"{borda_tipo},{borda},{sombra},5,40,40,0,1")

# ---------------------------------------------------------------- legenda

def eventos_legenda(palavras, dur, est, y):
    ev = []
    gs = grupos(palavras, est["por_vez"])
    for gi, g in enumerate(gs):
        fim_g = g[-1]["e"]
        prox_ini = gs[gi + 1][0]["s"] if gi + 1 < len(gs) else dur
        if prox_ini - fim_g < 0.35:
            fim_g = prox_ini
        textos = [esc(x["w"].upper() if est["caixa_alta"] else x["w"]) for x in g]
        if est["modo"] == "simples":  # um evento por bloco, sem destaque
            ev.append(f"Dialogue: 0,{ts(g[0]['s'])},{ts(fim_g)},Leg,,0,0,0,,{{\\an5\\pos({W // 2},{y})\\fad(60,60)}}"
                      + " ".join(textos))
            continue
        for wi, w in enumerate(g):
            t0 = w["s"] if wi else g[0]["s"]
            t1 = g[wi + 1]["s"] if wi + 1 < len(g) else fim_g
            if t1 - t0 < 0.02:
                continue
            partes = []
            for k, t in enumerate(textos):
                if est["modo"] == "ativa":
                    partes.append(f"{{\\c{cor(est['ativa'])}}}{t}{{\\c{cor(est['cor'])}}}" if k == wi else t)
                elif est["modo"] == "karaoke":
                    partes.append(f"{{\\c{cor(est['ativa'])}\\1a&H00&}}{t}" if k <= wi else f"{{\\c{cor(est['cor'])}\\1a&H70&}}{t}")
                elif est["modo"] == "caixa":
                    partes.append(f"{{\\3c{cor(est['ativa'])}}}{t}{{\\3c{cor(est['fundo'])}}}" if k == wi else t)
                elif est["modo"] == "beasty":
                    partes.append(f"{{\\fscx122\\fscy122}}{t}{{\\fscx100\\fscy100}}" if k == wi else t)
            extra = ""
            if est["modo"] == "beasty":
                extra = f"\\c{cor(est['ciclo'][gi % len(est['ciclo'])])}\\frz{(-2, 2)[gi % 2]}"
                if wi == 0:
                    extra += "\\fscx70\\fscy70\\t(0,110,\\fscx100\\fscy100)"
            elif wi == 0 and est["modo"] in ("ativa", "caixa"):
                extra = "\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)"
            ev.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},Leg,,0,0,0,,{{\\an5\\pos({W // 2},{y}){extra}\\q0}}" + " ".join(partes))
    return ev

def estilo_legenda_ass(est, fonte=None, tam=None):
    f = fonte or est["fonte"]
    t = tam or est["tam"]
    if est["modo"] == "caixa":
        return linha_estilo("Leg", f, t, cor(est["cor"]), cor(est["fundo"]), "&H00000000&", 3, est["borda"], 0)
    prim = cor(est.get("cor", "#FFFFFF"))
    fundo = "&H80000000&" if est["modo"] == "simples" else "&H64000000&"
    return linha_estilo("Leg", f, t, prim, "&H00000000&", fundo, 1, est["borda"], est["sombra"])

# ---------------------------------------------------------------- título

def eventos_titulo(titulo, dur, est, y, cor_marca, dur_titulo=0):
    if not titulo:
        return [], []
    linhas = quebrar(esc(titulo), 16 if est["pos"] == "centro" else 20)
    fim = est.get("dur") or (dur_titulo if dur_titulo > 0 else dur)
    fim = min(dur, fim)
    fundo = cor(est["fundo"] or cor_marca) if est["caixa"] or est["fundo"] else "&H00000000&"
    borda_tipo, borda = (3, 14) if est["caixa"] else (1, 10)
    estilo = linha_estilo("Tit", est["fonte"], est["tam"], cor(est["cor"]), fundo, "&H00000000&", borda_tipo, borda,
                          0 if est["caixa"] else 4)
    anim = "\\fad(120,150)"
    if est["pos"] == "centro":
        anim = "\\fscx140\\fscy140\\t(0,180,\\fscx100\\fscy100)\\fad(0,250)"
    an = 8 if est["pos"] == "topo" else 5
    return [estilo], [f"Dialogue: 1,{ts(0)},{ts(fim)},Tit,,0,0,0,,{{\\an{an}\\pos({W // 2},{y}){anim}}}" + "\\N".join(linhas)]

# ---------------------------------------------------------------- arquivo ASS

def montar_ass(palavras, dur, *, legenda, titulo, titulo_estilo, y_legenda, y_titulo, marca="", cor_marca="#FF2D9B",
               fonte=None, tam_legenda=None, caixa_alta=None, por_vez=None, cor_destaque=None, dur_titulo=0):
    est = dict(LEGENDAS[legenda])
    if caixa_alta is not None:
        est["caixa_alta"] = caixa_alta
    if por_vez:
        est["por_vez"] = por_vez
    if cor_destaque and "ativa" in est:
        est["ativa"] = cor_destaque
    estilos = [estilo_legenda_ass(est, fonte, tam_legenda),
               "Style: Marca,Arial Black,34,&H80FFFFFF&,&H80FFFFFF&,&HA0000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,2,0,2,40,40,0,1"]
    est_t, ev_t = eventos_titulo(titulo, dur, TITULOS[titulo_estilo], y_titulo, cor_marca, dur_titulo)
    estilos += est_t
    ev = list(ev_t)
    if marca:
        ev.append(f"Dialogue: 0,{ts(0)},{ts(dur)},Marca,,0,0,0,,{{\\an2\\pos({W // 2},{H - 300})}}{esc(marca)}")
    if palavras:
        ev += eventos_legenda(palavras, dur, est, y_legenda)
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *estilos, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *ev, ""])

def fontes_usadas(legenda, titulo_estilo, fonte=None):
    return {fonte or LEGENDAS[legenda]["fonte"], TITULOS[titulo_estilo]["fonte"], "Arial Black"}

# ---------------------------------------------------------------- emojis

EMOJI_AUTO = [
    (r"sust|medo|socorro|assust|terror", "😱"), (r"k{3,}|haha|rindo|risada|engraçad|piada", "😂"),
    (r"fogo|explod|bomba|incend|queim", "🔥"), (r"morr|morto|morte|caveira|matou", "💀"),
    (r"pol[ií]cia|viatura|preso|cadeia", "🚓"), (r"carro|corrida|acelera|moto", "🏎️"),
    (r"avi[aã]o|turbina|voou|voar|pouso", "✈️"), (r"dinheiro|grana|reais|milh[aãõ]|rico|pagou", "💰"),
    (r"caraca|caramba|uau|wow|nossa|meu deus|omg", "🤯"), (r"n[aã]o acredit|absurd|imposs[ií]vel|s[eé]rio", "😳"),
    (r"ganh|venc|campe[aã]o|vit[oó]ria|gol", "🏆"), (r"olha|veja|repara", "👀"), (r"pul|caiu|queda|tombo", "😵"),
    (r"amor|cora[cç][aã]o|linda|lindo", "❤️"), (r"bug|erro|travou|glitch", "🐛"),
]

def emojis_automaticos(palavras, maximo=4, espaco=3.0):
    saida = []
    for w in palavras:
        t = w["w"].lower()
        for padrao, e in EMOJI_AUTO:
            if re.search(padrao, t) and all(abs(w["s"] - s) >= espaco for s, _ in saida):
                saida.append((w["s"], e))
                break
        if len(saida) >= maximo:
            break
    return saida

def fonte_emoji():
    for nome, tamanhos in [("seguiemj.ttf", [136]), ("Apple Color Emoji.ttc", [160, 96, 64]),
                           ("NotoColorEmoji.ttf", [109])]:
        for d in pastas_de_fontes():
            p = d / nome
            if not p.exists() and d.exists():
                achados = list(d.rglob(nome))
                p = achados[0] if achados else p
            if p.exists():
                return p, tamanhos
    return None, []

def emoji_png(e, destino, lado=170):
    """Desenha o emoji colorido num PNG transparente. Devolve False se o sistema não tiver fonte de emoji."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    caminho, tamanhos = fonte_emoji()
    if not caminho:
        return False
    for t in tamanhos:
        try:
            f = ImageFont.truetype(str(caminho), t)
            break
        except OSError:
            continue
    else:
        return False
    tela = Image.new("RGBA", (t * 3, t * 2), (0, 0, 0, 0))
    ImageDraw.Draw(tela).text((t // 2, t // 4), e, font=f, embedded_color=True)
    caixa = tela.getbbox()
    if not caixa:
        return False
    img = tela.crop(caixa)
    esc_ = lado / max(img.size)
    img = img.resize((max(1, int(img.width * esc_)), max(1, int(img.height * esc_))), Image.LANCZOS)
    img.save(destino)
    return True
