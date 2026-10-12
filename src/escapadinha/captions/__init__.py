"""pt-PT Instagram captions rendered from Jinja templates."""

from __future__ import annotations

import re

from jinja2 import Environment, PackageLoader, StrictUndefined

from escapadinha import i18n_pt as pt
from escapadinha.guides import Guide
from escapadinha.presentation import DISCLOSURE, DealView, PhotoCredit

_env = Environment(loader=PackageLoader("escapadinha.captions", "templates"),
                   undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True,
                   keep_trailing_newline=False)


def _tidy(text: str) -> str:
    """Collapse 3+ newlines left by optional blocks into one blank line."""
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def deal_hashtags(view: DealView, brand_name: str) -> list[str]:
    tags = [pt.hashtag(view.destination_city), pt.hashtag(view.origin_city),
            "#voosbaratos", "#viagens", "#promocoesdeviagem", "#ferias", pt.hashtag(brand_name)]
    return list(dict.fromkeys(tags))


def _detail_lines(view: DealView) -> list[str]:
    lines = []
    if view.airline:
        flights = {True: " · voos diretos", False: " · com escala", None: ""}[view.direct]
        lines.append(f"🛫 {view.airline}{flights}")
    if view.arrival_airport:
        lines.append(f"🛬 Chegada: aeroporto {view.arrival_airport}")
    if view.discount_pct:
        lines.append(f"📉 {view.discount_pct}% abaixo do preço mínimo habitual desta rota "
                     f"para partidas em {view.departure_month}")
    return lines


def deal_caption(view: DealView, *, brand_name: str) -> str:
    template = _env.get_template("deal.txt.j2")
    return _tidy(template.render(v=view, detail_lines=_detail_lines(view),
                                 hashtags=deal_hashtags(view, brand_name)))


def guide_caption(guide: Guide, photo: PhotoCredit) -> str:
    template = _env.get_template("guide.txt.j2")
    return _tidy(template.render(g=guide, photo=photo, disclosure=DISCLOSURE))
