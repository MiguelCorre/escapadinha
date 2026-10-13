"""The three visual directions: fonts, palettes (light/dark), contrast pairs and rationale.

Palettes live here, not in CSS, so the contrast check and the pages can't drift apart:
the templates emit these tokens as CSS custom properties.
"""

from __future__ import annotations

from dataclasses import dataclass

from escapadinha.design_directions.contrast import MINIMUM, over, ratio

OFL = "SIL Open Font License 1.1"


@dataclass(frozen=True)
class Font:
    family: str
    role: str
    licence: str
    url: str


@dataclass(frozen=True)
class Pair:
    label: str
    fg: str      # token name
    bg: str      # token name; 'photo' = the scrim over a white photo pixel (worst case)
    role: str    # body | large | ui


@dataclass(frozen=True)
class ContrastRow:
    mode: str
    label: str
    fg: str
    bg: str
    ratio: float
    role: str
    minimum: float

    @property
    def ok(self) -> bool:
        return self.ratio >= self.minimum


@dataclass(frozen=True)
class Direction:
    key: str            # 'A'
    slug: str           # output folder
    name: str
    summary: tuple[str, str]
    rationale: str
    fonts: tuple[Font, ...]
    google_css: str
    light: dict[str, str]
    dark: dict[str, str]
    swatches: tuple[str, ...]          # tokens shown as the palette
    pairs: tuple[Pair, ...]
    scrim: str = "#000000"              # text-on-photo backdrop colour
    scrim_alpha: float = 0.6

    def palette(self, mode: str) -> dict[str, str]:
        return self.light if mode == "light" else self.dark

    def contrast(self) -> list[ContrastRow]:
        rows = []
        for mode in ("light", "dark"):
            tokens = self.palette(mode)
            for p in self.pairs:
                bg = over(self.scrim, self.scrim_alpha, "#FFFFFF") if p.bg == "photo" else tokens[p.bg]
                fg = tokens.get(p.fg, p.fg)
                rows.append(ContrastRow(mode, p.label, fg, bg, round(ratio(fg, bg), 2), p.role,
                                        MINIMUM[p.role]))
        return rows

    def css_vars(self, mode: str) -> str:
        tokens = dict(self.palette(mode))
        r, g, b = (int(self.scrim.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        tokens["scrim"] = f"rgba({r}, {g}, {b}, {self.scrim_alpha})"
        return " ".join(f"--{k}: {v};" for k, v in tokens.items())


CADERNO = Direction(
    key="A", slug="a-caderno", name="Caderno de Viagem",
    summary=("Revista de viagens em papel: serifas expressivas, muito branco, fotografias grandes "
             "com legenda, ritmo de colunas e filetes.",
             "Tom literário e calmo; os preços aparecem como factos dentro de uma história."),
    rationale=(
        "O Ponto Nómada nasce de um esboço com montanhas, pôr do sol e uma serifa de assinatura: "
        "esta direção leva isso para o registo de uma revista de viagens. A Fraunces dá títulos "
        "com personalidade (itálicos quentes, números de estilo antigo) e a Source Serif 4 garante "
        "leitura longa confortável, o que prepara o terreno para roteiros e dicas. A paleta é "
        "papel, tinta e um ferrugem de terracota, com a fotografia a fazer o trabalho da cor. "
        "Cada preço é tratado como notícia verificada: quem o encontrou, quando, e quanto costuma "
        "custar. É a direção mais aspiracional e a que melhor envelhece, mas é a menos rápida "
        "de ler num telemóvel à procura só do número."),
    fonts=(Font("Fraunces", "Títulos e números", OFL, "https://fonts.google.com/specimen/Fraunces"),
           Font("Source Serif 4", "Texto corrido e dados", OFL,
                "https://fonts.google.com/specimen/Source+Serif+4")),
    google_css=("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..800;"
                "1,9..144,400..700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400..700;"
                "1,8..60,400&display=swap"),
    light={"bg": "#F5F0E6", "surface": "#FFFDF8", "ink": "#1E1B16", "muted": "#5F574B",
           "accent": "#A23E1C", "on-accent": "#FFFFFF", "rule": "#D3C8B4"},
    dark={"bg": "#16140F", "surface": "#201D17", "ink": "#EEE7D8", "muted": "#B3A994",
          "accent": "#F0936B", "on-accent": "#16140F", "rule": "#3D372C"},
    swatches=("bg", "surface", "ink", "muted", "accent", "rule"),
    pairs=(Pair("Texto sobre papel", "ink", "bg", "body"),
           Pair("Texto sobre cartão", "ink", "surface", "body"),
           Pair("Legendas e metadados", "muted", "bg", "body"),
           Pair("Metadados em cartão", "muted", "surface", "body"),
           Pair("Ligações e destaques", "accent", "bg", "body"),
           Pair("Botão", "on-accent", "accent", "body"),
           Pair("Título sobre fotografia (pior caso)", "#FFFFFF", "photo", "body")),
    scrim="#000000", scrim_alpha=0.62,
)

POR_DO_SOL = Direction(
    key="B", slug="b-por-do-sol", name="Pôr do Sol",
    summary=("A leitura mais fiel ao esboço: pôr do sol, mar e montanha, cantos redondos, "
             "gradiente quente sobre as fotos e ondas a separar secções.",
             "Tom próximo e inspirador, por tu; o preço é o convite, a viagem é o assunto."),
    rationale=(
        "Esta direção parte diretamente do esboço da marca: o sol a pôr-se atrás das montanhas, "
        "o mar por baixo e a frase “A Nocas pelo mundo, o mundo ao teu alcance.” como promessa. "
        "A DM Serif Display traz a serifa de contraste alto do logótipo desenhado e a DM Sans, "
        "da mesma família, mantém a interface limpa e legível em ecrãs pequenos. A paleta vai da "
        "areia ao coral e ao roxo do crepúsculo, com um azul-petróleo de mar para ligações "
        "secundárias; no modo escuro vira noite de verão. As fotos levam um véu quente e cantos "
        "redondos para parecerem postais. É a direção mais emocional e a que melhor casa com o "
        "Instagram, com o risco de parecer genérica se o gradiente for usado em excesso."),
    fonts=(Font("DM Serif Display", "Títulos e preços", OFL,
                "https://fonts.google.com/specimen/DM+Serif+Display"),
           Font("DM Sans", "Interface e texto", OFL, "https://fonts.google.com/specimen/DM+Sans")),
    google_css=("https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1"
                "&family=DM+Sans:ital,opsz,wght@0,9..40,400..700;1,9..40,400&display=swap"),
    light={"bg": "#FFF7EE", "surface": "#FFFFFF", "ink": "#2A1E2E", "muted": "#6B5560",
           "coral": "#B23A1A", "button": "#B8401F", "on-button": "#FFFFFF", "sea": "#0E5A6B",
           "sun": "#F2A541", "dusk": "#3D2C5E", "line": "#F0DCCB"},
    dark={"bg": "#14121F", "surface": "#1F1B2E", "ink": "#FBEFE3", "muted": "#C9B7B0",
          "coral": "#FF9A6B", "button": "#FF9A6B", "on-button": "#14121F", "sea": "#6FC7D6",
          "sun": "#F2A541", "dusk": "#3D2C5E", "line": "#342D47"},
    swatches=("bg", "surface", "ink", "muted", "coral", "sea", "sun", "dusk"),
    pairs=(Pair("Texto sobre areia", "ink", "bg", "body"),
           Pair("Texto em cartão", "ink", "surface", "body"),
           Pair("Texto secundário", "muted", "bg", "body"),
           Pair("Texto secundário em cartão", "muted", "surface", "body"),
           Pair("Preço e destaques", "coral", "bg", "body"),
           Pair("Preço em cartão", "coral", "surface", "body"),
           Pair("Ligações (mar)", "sea", "bg", "body"),
           Pair("Botão", "on-button", "button", "body"),
           Pair("Texto sobre fotografia (pior caso)", "#FFFFFF", "photo", "body")),
    scrim="#2A1E2E", scrim_alpha=0.72,
)

QUADRO = Direction(
    key="C", slug="c-quadro", name="Quadro de Partidas",
    summary=("Painel de partidas de aeroporto: grotesca + mono, amarelo de sinalização, "
             "tabelas densas, números alinhados e fotos pequenas a preto e branco.",
             "Tom seco e factual; o número manda, cada linha é verificável."),
    rationale=(
        "Uma alternativa deliberadamente oposta à fotografia aspiracional: o site como um painel "
        "de partidas que mostra, sem enfeites, onde se pode ir e por quanto. A Space Grotesk dá "
        "uma voz técnica e moderna e a JetBrains Mono alinha preços, datas e códigos IATA como "
        "num ecrã de aeroporto. O amarelo de sinalização só aparece por trás de texto preto (nunca "
        "como cor de texto em fundo claro), com verde para “abaixo do habitual” e vermelho "
        "para “expirada”. As fotos ficam pequenas e a preto e branco para não competirem com "
        "os números. É a direção mais rápida de ler e a mais honesta com os dados, e a que mais se "
        "afasta do esboço; a montanha da marca vive só no símbolo."),
    fonts=(Font("Space Grotesk", "Títulos e interface", OFL,
                "https://fonts.google.com/specimen/Space+Grotesk"),
           Font("JetBrains Mono", "Preços, datas e códigos", OFL,
                "https://fonts.google.com/specimen/JetBrains+Mono")),
    google_css=("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400..700"
                "&family=JetBrains+Mono:wght@400..800&display=swap"),
    light={"bg": "#F4F4F0", "surface": "#FFFFFF", "ink": "#0A0A0A", "muted": "#4A4A4A",
           "signal": "#FFD400", "on-signal": "#0A0A0A", "good": "#0B6B3A", "bad": "#B42318",
           "line": "#0A0A0A", "board": "#0A0A0A", "board-ink": "#FFD400"},
    dark={"bg": "#0B0C0D", "surface": "#15171A", "ink": "#F2F2EE", "muted": "#A7A9AC",
          "signal": "#FFD400", "on-signal": "#0A0A0A", "good": "#3DDC84", "bad": "#FF6B5E",
          "line": "#3A3D42", "board": "#000000", "board-ink": "#FFD400"},
    swatches=("bg", "surface", "ink", "muted", "signal", "good", "bad"),
    pairs=(Pair("Texto sobre fundo", "ink", "bg", "body"),
           Pair("Texto em linha do quadro", "ink", "surface", "body"),
           Pair("Texto secundário", "muted", "bg", "body"),
           Pair("Texto secundário em linha", "muted", "surface", "body"),
           Pair("Etiqueta amarela", "on-signal", "signal", "body"),
           Pair("Painel (amarelo sobre preto)", "board-ink", "board", "body"),
           Pair("Abaixo do habitual", "good", "surface", "body"),
           Pair("Expirada", "bad", "surface", "body"),
           Pair("Expirada sobre fundo", "bad", "bg", "body")),
    scrim="#000000", scrim_alpha=0.6,
)

DIRECTIONS = (CADERNO, POR_DO_SOL, QUADRO)
