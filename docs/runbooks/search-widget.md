# Pesquisa de voos do Aviasales no site (widget)

Guia passo a passo para o Miguel (issue #16, decisão D34). O site já sabe mostrar a pesquisa de
voos do Aviasales nas páginas das rotas (`/voos/...`) e dos destinos (`/destinos/...`), só
quando o visitante chega a essa parte da página. Falta só o código do widget, que tem de vir do
construtor de widgets da Travelpayouts (nunca fazemos à mão links com o nosso `marker`: o termo
1.4 do Aviasales proíbe-o). Enquanto `site.search_widget` estiver vazio (`null`), não aparece
nada.

## 1. Gerar o widget na Travelpayouts

- [ ] Entra em https://app.travelpayouts.com → **Tools** (Ferramentas) → **Widgets**.
- [ ] Escolhe **Search form** (Formulário de pesquisa) → **Aviasales**.
- [ ] Em **Project** escolhe **Pontonomada** (ID **585209**, o Projeto do site). Não uses o do
      Instagram (584711): as comissões do site ficam separadas (D19).
- [ ] **Language** (idioma): **Português** (`pt`). **Currency** (moeda): **EUR**.
- [ ] O resto (cores, cidade de partida por omissão, tamanho) é à tua escolha; largura a 100 %
      fica melhor no telemóvel.
- [ ] Carrega em **Get code** / **Copiar código**. O código é parecido com isto:

  ```html
  <script async src="https://tpwgts.com/content?currency=eur&trs=...&shmarker=...&promo_id=...&locale=pt&..." charset="utf-8"></script>
  ```

- [ ] Copia **só o endereço** que está dentro de `src="…"` (começa por `https://`).

## 2. Colar no `config.yaml`

- [ ] No `config.yaml`, na secção `site:`, troca `search_widget: null` pelo endereço, entre
      aspas:

  ```yaml
  site:
    search_widget: "https://tpwgts.com/content?currency=eur&trs=...&locale=pt&..."
  ```

- [ ] Confirma que o endereço é aceite: `uv run escapadinha stats` (qualquer comando lê o
      `config.yaml`). Se o endereço não for `https` ou o domínio não for um dos da Travelpayouts
      (`tp.media`, `tpwgts.com`, `tpembd.com`, `tpemd.com`, `tpscr.com`), o comando para com uma
      mensagem sobre `site.search_widget`. Se a Travelpayouts passar a usar outro domínio, diz-me:
      tem de ser acrescentado em `config.py` e no contrato (`contract/site/v1/meta.schema.json`).
- [ ] Faz commit e push. A próxima execução do pipeline segue o caminho completo (o
      `config.yaml` mudou) e exporta o endereço com os dados do site. **Atenção:** só o site
      novo (Astro, `web/`) tem o widget; aparece no ar depois da passagem para o site novo
      (#23). Antes disso podes vê-lo no teu PC: `uv run escapadinha export site-data --out
      web/src/data`, depois `cd web`, `npm run build` e `npm run preview`.

## 3. Ver no site

- [ ] Abre uma página de rota, por exemplo https://pontonomada.pt/voos/lisboa-paris/, e desce até
      **Pesquisar outras datas**: o formulário do Aviasales aparece quando chegas lá.
- [ ] Faz uma pesquisa de teste e confirma, no endereço da página do Aviasales que abre, que tem
      o nosso `marker` (o número da tua conta Travelpayouts).
- [ ] A página inicial e as páginas das promoções **não** têm o widget (de propósito).

Para tirar o widget: volta a pôr `search_widget: null`.

## Estatísticas: não é preciso fazer nada

O Cloudflare Web Analytics já está ligado em **configuração automática** na zona
`pontonomada.pt`: a Cloudflare conta as visitas do lado dela, sem nada no código do site e sem
cookies. Por isso `site.analytics_token` fica `null`: com um token, cada visita contava duas
vezes. Só se desligares a configuração automática é que deves pôr o token
(Cloudflare → **Analytics & Logs** → **Web Analytics** → o site → **Manage site** → copia o
`token` do código JavaScript) em `site.analytics_token`; o site passa então a incluir o script
oficial da Cloudflare em todas as páginas.
