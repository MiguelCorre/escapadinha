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
    if view.baggage_line:                   # only when the GraphQL match said so (D43)
        lines.append(f"🧳 {view.baggage_line.capitalize()}")
    # The claim (D44): "−x %" only with medium or high confidence in the typical low; a new low
    # is said as such (alone when the typical low is not trusted enough for a percentage).
    if view.claimed_discount:
        line = (f"📉 {view.claimed_discount}% abaixo do preço mínimo habitual desta rota "
                f"para partidas em {view.departure_month}")
        lines.append(f"{line}: {view.new_low_line.split(' nesta rota')[0]}" if view.new_low
                     else line)
    elif view.new_low_line:
        lines.append(f"📉 {view.new_low_line[0].upper()}{view.new_low_line[1:]}")
    return lines


def deal_caption(view: DealView, *, brand_name: str) -> str:
    template = _env.get_template("deal.txt.j2")
    return _tidy(template.render(v=view, detail_lines=_detail_lines(view),
                                 hashtags=deal_hashtags(view, brand_name)))


def whatsapp_text(view: DealView) -> str:
    """Ready-to-paste WhatsApp text for an approved promotion (D32): shorter than the caption,
    no hashtags, with the stored partner link and the disclosure, and the same claim line as the
    caption (D44: a percentage only at medium or high confidence). Raises ValueError without a
    link (the text is the link's carrier; there is never a hand-built one)."""
    if not view.affiliate_url:
        raise ValueError(f"deal {view.deal_id} has no partner link")
    return _tidy(_env.get_template("whatsapp.txt.j2").render(v=view,
                                                             detail_lines=_detail_lines(view)))


def guide_caption(guide: Guide, photo: PhotoCredit) -> str:
    template = _env.get_template("guide.txt.j2")
    return _tidy(template.render(g=guide, photo=photo, disclosure=DISCLOSURE))
