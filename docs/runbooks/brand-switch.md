# Mudança de marca: pontonomada.pt, redirecionamentos, Travelpayouts e Instagram

Guia passo a passo para o Miguel (issue #22, decisões D16 e D19). Marca cada caixa quando
terminares. Os passos estão por ordem: não saltes para a frente, porque alguns dependem dos
anteriores (por exemplo, o Projeto Travelpayouts do site só se cria depois de o domínio estar no ar).

Os nomes dos botões são os do painel em inglês, tal como aparecem hoje. Se algum mudou, procura
o nome indicado na barra de pesquisa do painel.

**O código já está pronto** (D19). Só tens de mexer em três linhas do `config.yaml` (passos 5, 8
e 9). Tudo o resto são cliques fora do repositório.

## 0. Antes de começar

- [ ] Tens à mão: cartão para pagar o domínio, o teu NIF, acesso à conta Cloudflare (a mesma
      do projeto Pages `ondestaanocas`), acesso ao Travelpayouts e a app do Instagram.
- [ ] Tempo: cerca de 1 hora de cliques, mais a espera dos nameservers (minutos a 24 h).
- [ ] Nada disto apaga o site atual: https://ondestaanocas.pages.dev continua a funcionar e,
      no fim, passa a redirecionar para https://pontonomada.pt com o mesmo caminho.

## 1. Registar `pontonomada.pt` (pagas tu)

A Cloudflare não vende domínios `.pt`: o registo faz-se num registrar acreditado pelo .PT.

- [ ] Abre https://www.pt.pt/pt/dominios/ e pesquisa `pontonomada`. Confirma que `pontonomada.pt`
      aparece como **disponível**. (Se não estiver, para aqui e avisa-me.)
- [ ] Escolhe um registrar da lista de registrars acreditados no mesmo site (por exemplo PTisp ou
      Amen.pt). Compara o preço de **renovação**, não só o do primeiro ano.
- [ ] No registrar, pesquisa `pontonomada.pt` → **Adicionar ao carrinho**.
- [ ] Duração: 1 ano chega. Ativa a **renovação automática**.
- [ ] **Recusa todos os extras**: alojamento, email, construtor de sites, "DNS premium",
      certificado SSL (a Cloudflare dá-o grátis).
- [ ] Titular: tu, como pessoa singular, com o teu NIF. Usa um email que leias (é para lá que
      vão os avisos de renovação).
- [ ] Paga e guarda a fatura.
- [ ] Ainda **não** mexas nos nameservers: isso é no passo 3.

### 1b. (Opcional, defensivo) `pontonomada.com`

- [ ] Cloudflare → menu lateral **Domain Registration** → **Register Domains** → pesquisa
      `pontonomada.com` → **Purchase**. A Cloudflare cobra o preço de custo e cria logo a zona,
      por isso este domínio salta os passos 2 e 3.
- [ ] Em **DNS** → **Records** de `pontonomada.com`, cria dois registos só para o redirecionamento
      funcionar (o IP é um endereço reservado, nunca é usado porque o pedido é redirecionado antes):
  - [ ] **Add record** → Type `A`, Name `@`, IPv4 `192.0.2.1`, Proxy status **Proxied** (nuvem
        laranja) → **Save**.
  - [ ] **Add record** → Type `A`, Name `www`, IPv4 `192.0.2.1`, **Proxied** → **Save**.

## 2. Adicionar `pontonomada.pt` à Cloudflare

- [ ] Entra em https://dash.cloudflare.com → página inicial da conta → **Add a domain**
      (pode aparecer como **+ Add** → **Connect a domain**).
- [ ] Escreve `pontonomada.pt`, deixa **Quick scan for DNS records** ligado → **Continue**.
- [ ] Plano: **Free** → **Continue**.
- [ ] Revê os registos DNS encontrados. Apaga os que o registrar criou para alojamento
      (por exemplo um `A` para `@` ou `www` que aponte para o registrar). → **Continue**.
- [ ] A Cloudflare mostra **dois nameservers** (algo como `nome.ns.cloudflare.com`). Copia-os.

## 3. Mudar os nameservers no registrar

- [ ] No painel do registrar → os teus domínios → `pontonomada.pt` → **DNS** / **Servidores de
      nomes** (ou "Nameservers").
- [ ] Se o registrar tiver **DNSSEC** ligado para este domínio, desliga-o primeiro.
- [ ] Substitui os nameservers pelos **dois da Cloudflare** (apaga os outros) → **Guardar**.
      O .PT verifica os nameservers no momento: como a zona já existe na Cloudflare (passo 2),
      a verificação passa. Se der erro, espera 10 minutos e tenta de novo.
- [ ] Na Cloudflare, na página do domínio, clica **Check nameservers now**.
- [ ] Espera pelo email da Cloudflare "pontonomada.pt is now active on a Cloudflare Free plan"
      (minutos a 24 h). A página do domínio passa a mostrar **Active**.
- [ ] (Recomendado, depois de ativo) Cloudflare → `pontonomada.pt` → **DNS** → **Settings** →
      **DNSSEC** → **Enable DNSSEC**. Copia o registo **DS** e cola-o no registrar (secção DNSSEC).

## 4. Ligar o domínio ao site (Pages → Custom domains)

- [ ] Cloudflare → **Workers & Pages** → projeto **ondestaanocas** → separador **Custom domains**
      → **Set up a custom domain**.
- [ ] Escreve `pontonomada.pt` → **Continue** → **Activate domain**. A Cloudflare cria o registo
      DNS sozinha.
- [ ] Repete com `www.pontonomada.pt` (**Set up a custom domain** → `www.pontonomada.pt` →
      **Continue** → **Activate domain**).
- [ ] Espera que os dois mostrem **Active** (o certificado HTTPS demora alguns minutos).
- [ ] Abre https://pontonomada.pt: deve aparecer o site (ainda com links canónicos para o
      endereço antigo; isso muda no passo 5).

O nome do projeto Pages fica `ondestaanocas`: a Cloudflare não deixa mudar o nome de um projeto
e o nome não aparece a ninguém depois do redirecionamento.

## 5. Mudar `site.base_url` (config.yaml)

Podes pedir-me isto ("liga o site ao pontonomada.pt") ou fazer tu:

- [ ] Em `config.yaml`, secção `site:`:
  ```yaml
  base_url: https://pontonomada.pt
  legacy_hosts:
    - ondestaanocas.pages.dev
    - www.pontonomada.pt
    - pontonomada.com          # só se fizeste o passo 1b
    - www.pontonomada.com      # só se fizeste o passo 1b
  ```
- [ ] Corre:
  ```bash
  uv run escapadinha export site-data
  uv run escapadinha site build
  uv run escapadinha site deploy --force
  ```
  O `site build` deixa de mostrar o aviso "final domain ... not connected yet".
- [ ] Confirma em https://pontonomada.pt (ver código-fonte da página): o `<link rel="canonical"`
      e o `sitemap.xml` já usam `https://pontonomada.pt`.
- [ ] Faz commit da alteração ao `config.yaml`.

A partir daqui, o ficheiro `_headers` gerado marca os endereços antigos como `noindex`, para o
Google indexar só o domínio novo, mesmo antes do passo 6.

## 6. Redirecionar os endereços antigos (Bulk Redirects)

Porquê assim (D19): o ficheiro `_redirects` do Pages só olha para o caminho, nunca para o
domínio, por isso não consegue redirecionar `ondestaanocas.pages.dev`. A Cloudflare recomenda um
**Bulk Redirect** ao nível da conta: grátis (o plano Free dá 15 regras e 10 000 redirecionamentos),
sem código e sem custos por pedido.

- [ ] Cloudflare → página inicial da **conta** (não a do domínio) → menu lateral **Bulk Redirects**
      (se não o vires, pesquisa "Bulk Redirects").
- [ ] **Create Bulk Redirect List** → Name `pontonomada_hosts`, Description
      `Domínios antigos para pontonomada.pt` → **Next**.
- [ ] **Or, manually add URL redirects** e preenche uma linha por domínio antigo:

  | Source URL | Target URL | Status | Edit parameters |
  |---|---|---|---|
  | `ondestaanocas.pages.dev` | `https://pontonomada.pt` | 301 | ✓ Preserve query string, ✓ Include subdomains, ✓ Subpath matching, ✓ Preserve path suffix |
  | `www.pontonomada.pt` | `https://pontonomada.pt` | 301 | ✓ Preserve query string, ✓ Subpath matching, ✓ Preserve path suffix |
  | `pontonomada.com` (só com 1b) | `https://pontonomada.pt` | 301 | ✓ Preserve query string, ✓ Include subdomains, ✓ Subpath matching, ✓ Preserve path suffix |

  "Include subdomains" na primeira linha apanha também os endereços de cada deploy
  (`<código>.ondestaanocas.pages.dev`); na terceira apanha `www.pontonomada.com`.
- [ ] **Next** → revê → **Next** → **Continue to Redirect Rules**.
- [ ] Rule name `Dominios antigos para pontonomada.pt` → escolhe a lista `pontonomada_hosts` →
      **Save and Deploy**.
- [ ] Testa (num terminal ou numa janela anónima do browser):
  ```bash
  curl -sI https://ondestaanocas.pages.dev/voos/lisboa-londres/ | grep -i -E "^HTTP|^location"
  curl -sI https://www.pontonomada.pt/sobre/ | grep -i -E "^HTTP|^location"
  ```
  Esperado: `HTTP/2 301` e `location: https://pontonomada.pt/voos/lisboa-londres/` (e
  `.../sobre/`). Os links antigos já partilhados (`/promos/<id>-<origem>-<destino>/`) continuam
  a abrir a mesma promoção.

O `site deploy` continua a funcionar igual: o wrangler envia para o projeto, não para o endereço.

## 7. (Opcional) Pesquisa e estatísticas

- [ ] Cloudflare Web Analytics: Cloudflare → **Analytics & Logs** → **Web Analytics** → confirma
      que o site `pontonomada.pt` aparece. Está em configuração automática (a Cloudflare conta as
      visitas do lado dela, sem nada no código do site), por isso `site.analytics_token` fica `null` (D34); só com a
      configuração automática desligada é que o token vai para o `config.yaml`. A pesquisa de
      voos do Aviasales tem o seu guia: [search-widget.md](search-widget.md).
- [ ] Google Search Console → **Adicionar propriedade** → **Domínio** `pontonomada.pt` → copia o
      registo TXT → Cloudflare → `pontonomada.pt` → **DNS** → **Add record** (Type `TXT`, Name `@`)
      → **Verificar**. Depois **Sitemaps** → `https://pontonomada.pt/sitemap.xml` → **Enviar**.

## 8. Travelpayouts: Projeto para o site

Só depois de o passo 6 estar feito: o link de um Projeto **não se pode mudar** depois de ligado
a programas, por isso tem de ser já o domínio final.

- [ ] https://app.travelpayouts.com → seletor de projetos (canto superior) → **Add project**.
- [ ] Tipo **Website**; URL `https://pontonomada.pt`; tema Viagens; idioma Português; descreve
      o site em uma frase (promoções de voos a partir de Portugal, revistas à mão) → criar.
- [ ] Com o projeto novo selecionado → **Programs** → **Aviasales** → **Join** / **Connect**
      (aceita os termos do programa para este projeto). Se pedir verificação do site com uma meta
      tag, envia-me o código e eu ponho-o no template.
- [ ] Copia o **ID do projeto** (número; aparece nas definições do projeto e no endereço da
      página quando o projeto está selecionado).
- [ ] Em `config.yaml`:
  ```yaml
  affiliate:
    projects:
      instagram: 584711
      website: <ID novo>
  ```
- [ ] `uv run escapadinha export site-data` e `uv run escapadinha site build` → abre uma promoção
      ativa em `web/dist/promos/` e confirma que o botão de reserva tem um link
      `https://aviasales.tpo.lu/...` (os links do site são criados pela exportação e ficam
      guardados na base de dados, com `sub_id=site-deal-<id>`). Se um link falhar, o site usa o
      link da promoção (Projeto do Instagram) e volta a tentar na exportação seguinte.
- [ ] `uv run escapadinha site deploy` e faz commit do `config.yaml`.
- [ ] Marca no `LAUNCH_CHECKLIST.md`: "Create a separate Project for the website".

## 9. Instagram: mudar o nome e novo Projeto Travelpayouts

Quando quiseres (pode ser noutro dia; issue #27). Os slides e as legendas usam `brand.handle`.

- [ ] App do Instagram → **Perfil** → **Editar perfil** → **Nome de utilizador** → `pontonomada`
      → ✓. Em **Nome**, escreve `Ponto Nómada`.
- [ ] Na bio, põe o link `https://pontonomada.pt`.
- [ ] Atenção: o nome antigo `@ondestaanocas` fica livre para outra pessoa. O Instagram deixa-te
      voltar atrás durante 14 dias. Se quiseres protegê-lo, cria uma segunda conta com esse nome
      e só um link para `@pontonomada`.
- [ ] Travelpayouts → **Add project** → tipo rede social / Instagram → URL
      `https://www.instagram.com/pontonomada/` → criar → **Programs** → **Aviasales** → **Join**.
      Copia o ID.
- [ ] Em `config.yaml` (as duas linhas juntas, no mesmo commit):
  ```yaml
  brand:
    handle: "@pontonomada"
  affiliate:
    projects:
      instagram: <ID novo do Instagram>
      website: <ID do passo 8>
  ```
- [ ] Promoções novas passam a ter links do Projeto novo. As antigas mantêm o link que já têm
      guardado: **não arquives o Projeto 584711** enquanto houver promoções ativas com esses links
      (depois disso, Travelpayouts → projeto "Instagram" antigo → **Archive**).
- [ ] Promoções já renderizadas mas ainda não publicadas têm o nome antigo no último slide:
      volta a renderizá-las antes de publicar (`uv run escapadinha render deals --status rendered`
      e `--status approved`).
- [ ] Marca no `LAUNCH_CHECKLIST.md`: "Rename the Instagram handle to match".

## 10. Fecho

- [ ] Diz-me "domínio ligado": eu atualizo README.md, DECISIONS.md e LAUNCH_CHECKLIST.md
      (endereço do site, data) e fecho a issue #22 no commit.
