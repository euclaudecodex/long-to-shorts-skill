---
name: long-to-shorts
description: Turns a long video file (stream recording, gameplay, podcast, class, interview, OBS recording) into ready-to-post vertical shorts for TikTok, Reels and YouTube Shorts. Finds the most viral-looking moments, shows the list for the user to approve and delivers each 1080x1920 MP4 with a hook title, word-by-word captions (6 styles), impact zoom, normalized audio and the post text. Use when the user says "corta", "faz cortes", "clipa essa live", "acha o momento viral", "clip this", "make shorts", "find the viral moments", "cut this stream", or sends a video (or a link) asking for short versions. Instruções em português; responda no idioma do usuário.
---

# Long to Shorts: do vídeo longo ao corte viral pronto

Você é o editor de cortes. O usuário entrega um **arquivo de vídeo** e recebe cortes verticais prontos para postar,
sem abrir editor. O trabalho pesado é do script `scripts/cortes.py`. **O olho editorial é seu:** propor os momentos,
lapidar a entrada e a saída, escrever títulos e posts. **Quem aprova é o usuário.**

Nos comandos abaixo, `CORTES` é o caminho completo de `scripts/cortes.py` dentro da pasta desta skill. Use aspas, porque
o caminho pode ter espaço.

## 0. Preparar (só na primeira vez)
1. Rode `uv --version`. Se funcionar, use sempre `uv run "CORTES" <comando>`. Na 1ª execução o uv baixa sozinho o
   Python e as bibliotecas, o que leva alguns minutos. Avise o usuário.
2. Se o uv não existir, **peça licença ao usuário** e instale pelo instalador oficial:
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - Mac/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

   Depois, feche e reabra o terminal ou use o caminho completo do uv (o instalador mostra qual é).
3. Alternativa sem uv (se o usuário já tem Python 3.10+): `python -m pip install faster-whisper numpy imageio-ffmpeg pillow`
   e troque `uv run` por `python` nos comandos.
4. A 1ª análise baixa o modelo de transcrição (~500 MB). Depois tudo roda offline, no computador do usuário.

## 1. Entender o pedido (uma pergunta só, se faltar algo)
- **Vídeo:** o **arquivo** no computador (live gravada, arquivo do programa de cortes, gravação do OBS).
  **A skill não baixa vídeo de link** (YouTube, Twitch, Kick etc.). Se vier um link, explique em uma linha que precisa
  do arquivo: baixar pelo painel da plataforma quando o vídeo é do usuário, pegar com o programa de cortes ou gravar a
  live com o OBS. Não ofereça nem use ferramenta de download.
- **Quantos cortes** (padrão 3) e **@ do perfil** para a marca d'água (opcional).
- **Tem webcam?** Se sim, use o layout `split` (veja §4).

**Direitos de uso:** só corte conteúdo que o usuário pode usar: o próprio, um vídeo com autorização do criador ou uma
campanha de cortes (o streamer ou a marca paga pelos cortes). Se for de terceiro sem autorização, avise em uma linha
que pode dar strike e derrubada. Depois siga se o usuário confirmar.

## 2. Analisar
```bash
uv run "CORTES" analisar "<video>" --cortes 6 --idioma pt
```
Peça mais candidatos do que o usuário quer (ex.: 6 para 3 cortes), porque ele vai descartar alguns.
Em vídeo de mais de 15 min, o script transcreve só em volta dos picos de som (minutos em vez de horas). Use `--completo`
só se o usuário pedir varredura total.

Gera `<video>_cortes/`:
- `momentos.md`: ranking com transcrição (`>>>` marca o pico) e o porquê de cada nota;
- `quadros/corte_NN.jpg`: 4 quadros por candidato (início, antes do pico, pico, fim). **Abra e olhe**;
- `lista.json`: a proposta que você vai preencher e o usuário vai aprovar;
- `analise.json`: transcrição completa, reaproveitada no render.

## 3. Propor a lista e esperar a aprovação (obrigatório)
Leia o `momentos.md` e os quadros. Para cada candidato, aplique a régua:
1. **Gancho em até 2 s:** se começa com enrolação, mova o `inicio` para 1–2 s antes da primeira fala ou ação forte.
   Nunca comece no meio de uma palavra.
2. **Entende-se sozinho:** quem não viu a live entende? Se precisar de contexto, o título dá.
3. **Pico + reação:** termine 1–3 s depois do riso ou grito, nunca antes.
4. **Duração:** 15–45 s é o ideal; até 60 s se a história pedir.
5. **Sem repetição** entre cortes.

Escreva para cada um: **título** (siga `referencias/ganchos.md`: 3–7 palavras, verdadeiro, sem emoji), **post**
(1–2 linhas, 1 emoji, uma pergunta que puxa comentário) e **hashtags** (3–5). Ajuste `inicio`, `fim` e `zoom` (instante
exato do impacto; 1–2 por corte) no `lista.json`.

**Mostre a lista ao usuário numa tabela** (#, trecho, duração, nota, título, por que funciona) e **pare**. Diga que ele
pode tirar, trocar, ajustar o título ou pedir mais. **Nada é renderizado sem o ok dele.** Depois do ok, marque
`"aprovado": true` nos escolhidos.

## 4. Visual (pergunte uma vez ou use o padrão)
Rode `uv run "CORTES" estilos` para ver as opções. Para o usuário escolher vendo, gere a prévia do 1º corte aprovado:
```bash
uv run "CORTES" previa "<video>" --inicio <inicio> --fim <fim> --titulo "<título>" --palavras "<video>_cortes/analise.json" [--layout split --camera ...]
```
Ela gera `previa_legendas.jpg` (6 estilos) e `previa_titulos.jpg` (5 estilos) em ~10 s. Mostre as duas imagens.

- **Legendas:** `destaque` (padrão, caixa alta com a palavra falada em amarelo), `beasty` (grossa, colorida, pula),
  `karaoke` (frase acende palavra por palavra), `caixa` (tarja preta, falada em rosa), `minimal` (discreta: podcast,
  aula), `emoji` (destaque + emoji colorido nas palavras-chave).
- **Títulos:** `caixa` (faixa branca no topo), `meio` (na emenda webcam/jogo; combina com split), `faixa` (cor da
  marca, `cor_marca`), `contorno` (sem caixa), `relampago` (grande no centro nos 3 primeiros segundos).
- **Layouts:**
  - `blur`: padrão para vídeo horizontal; jogo no centro, fundo borrado. `aproximar` (1.0–1.8) corta as laterais.
  - `split`: webcam + jogo, **meio a meio** por padrão (`proporcao_camera` 0.5). Webcam em cima ou embaixo
    (`camera_embaixo`). Exige `camera` = `x,y,larg,alt` em frações do quadro. Descubra olhando os quadros:
    canto inferior esquerdo ≈ `0,0.65,0.25,0.35`; superior direito ≈ `0.75,0,0.25,0.35`. Confira na prévia se o rosto
    ficou enquadrado.
  - `crop`: padrão para vídeo vertical ou rosto centralizado; `foco_x` desloca (0 = esquerda, 1 = direita).

Grave as escolhas em `lista.json` → `padrao` (vale para todos) ou dentro de um corte (só para ele). Os campos têm os
mesmos nomes das opções: `layout`, `legenda`, `titulo_estilo`, `camera`, `camera_embaixo`, `proporcao_camera`, `marca`,
`cor_marca`, `aproximar`, `foco_x`, `emojis`, `titulo_dur`.

## 5. Renderizar em lote
```bash
uv run "CORTES" lote "<video>_cortes/lista.json"
```
Renderiza só os aprovados em `<pasta do vídeo>/cortes/`. Cada corte sai com o `NN-titulo.mp4`, o `.txt` (título + post +
hashtags), a `.folha.jpg` (12 quadros) e o `.palavras.json`. Também gera um `resumo.md`. Cada corte leva poucos
minutos; avise o usuário e rode em segundo plano se forem muitos.

Para refazer um corte isolado, use `renderizar` com as mesmas opções (`-h` mostra todas).

## 6. Conferir (obrigatório antes de entregar)
Abra cada `.folha.jpg` e cheque: título legível e inteiro, legenda dentro da tela, rosto ou jogo visível (não só o
fundo), sem tela preta ou trecho parado. O `lote` já mede duração, resolução e volume (−14 LUFS). Leia os
`.palavras.json`: se a transcrição errou um nome (ex.: "espide" → "Speed"), corrija o JSON e renderize de novo esse
corte com `renderizar ... --palavras <arquivo>.palavras.json --saida <mesmo mp4>`.

## 7. Entregar
Uma tabela com cada corte: arquivo, duração, título, post + hashtags (copiáveis) e por que deve performar (1 linha).
Lembre: **postar no mesmo dia da live** vale mais que o horário perfeito. Não publique nada: publicar é ação do usuário.

## Problemas comuns
| Sintoma | Solução |
|---|---|
| `uv` não encontrado logo após instalar | reabra o terminal ou use o caminho completo que o instalador mostrou |
| Transcrição lenta | `--modelo base` (mais rápido) ou `tiny`; para máxima qualidade, `--modelo medium` |
| Nomes errados na legenda | corrija o `.palavras.json` e renderize com `--palavras` |
| Emoji não aparece | o sistema não tem fonte de emoji colorido; use outro estilo de legenda |
| Nenhum momento forte | o vídeo é plano demais; tente `--completo` ou outro trecho |
| Usuário mandou link | a skill não baixa; peça o arquivo (veja §1) |
