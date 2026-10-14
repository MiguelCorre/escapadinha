# Publicação automática no Instagram

Guia passo a passo para o Miguel (issue #24, decisão D36). O pipeline já sabe publicar no
Instagram cada promoção aprovada: à hora marcada (`queue list`) publica um **carrossel** com as
imagens da promoção e a legenda de sempre, e logo a seguir uma **story** com a capa. Antes de
publicar confirma o preço (como até aqui), que as imagens JPEG já estão no site
(`https://pontonomada.pt/img/promos/<id>/slide_01.jpg`, …) e que o limite diário de publicações
da API não foi atingido. Depois do carrossel escreve a decisão "publicado" (com o link do post),
que a execução seguinte aplica: a página da promoção passa a ter o link para o Instagram.

Enquanto faltar `INSTAGRAM_ACCESS_TOKEN` ou `INSTAGRAM_ACCOUNT_ID`, o Instagram continua em
**dry run**: o registo da execução diz *"Instagram em dry run: faltam INSTAGRAM_ACCESS_TOKEN
e/ou INSTAGRAM_ACCOUNT_ID"* e mostra o que seria publicado, sem publicar nada.

Usamos a **Instagram API com login do Instagram** (`graph.instagram.com`): não precisa de Página
do Facebook. Se a conta estiver ligada a uma Página e preferires o login do Facebook, diz-me:
é só `instagram.login: facebook` no `config.yaml` (e um token de Página, que não expira).

## 1. A conta do Instagram

- [ ] A conta (@ondestaanocas, mais tarde @pontonomada) tem de ser **profissional** (Criador
      de conteúdo ou Empresa): Instagram → Definições → Tipo de conta e ferramentas → Mudar
      para conta profissional. Já é, se vês as estatísticas dos posts.

## 2. Criar a app na Meta

- [ ] Entra em https://developers.facebook.com com a tua conta → **My Apps** → **Create app**.
- [ ] Caso de utilização: **Other** (Outro) → tipo **Business** (Empresa). Nome: por exemplo
      "Ponto Nómada publicação". Não ligues nenhum Business Manager se não te pedir.
- [ ] No painel da app: **Add product** → **Instagram** → **Set up**.
- [ ] Escolhe **API setup with Instagram login** (configuração da API com login do Instagram).
- [ ] Em **Permissions** confirma que estão pedidas:
  - `instagram_business_basic` (ler a conta e os posts: o pipeline usa-o para não publicar
    duas vezes o mesmo carrossel);
  - `instagram_business_content_publish` (publicar carrosséis e stories).
- [ ] A app pode ficar em **modo de desenvolvimento**: a tua própria conta, com um papel na app,
      publica sem revisão da Meta. Em **App roles** → **Roles** → **Add people** →
      **Instagram Tester**, adiciona a conta do Instagram, e aceita o convite no Instagram
      (Definições → Apps e sites → Convites de testador).

## 3. Gerar o token de longa duração

- [ ] Ainda em **Instagram** → **API setup with Instagram login** → **Generate access tokens**
      → **Add account** → entra com a conta do Instagram e autoriza as duas permissões.
- [ ] Carrega em **Generate token** ao lado da conta. Copia o token (começa por `IG…`). É um
      token **de longa duração: vale 60 dias**. Gera-o mesmo antes de o colar (passo 4): o
      pipeline conta os 60 dias a partir da primeira vez que o vê.
- [ ] Copia também o **ID** que aparece ao lado do nome da conta (só números, por exemplo
      `17841400000000000`): é o `INSTAGRAM_ACCOUNT_ID`.

## 4. Onde pôr os dois valores

- [ ] No `.env` do PC (nunca no Git):

  ```
  INSTAGRAM_ACCESS_TOKEN=IG...
  INSTAGRAM_ACCOUNT_ID=17841400000000000
  ```

- [ ] No GitHub: repositório → **Settings** → **Secrets and variables** → **Actions** → **New
      repository secret**, um para cada: `INSTAGRAM_ACCESS_TOKEN` e `INSTAGRAM_ACCOUNT_ID`
      (o workflow já os passa ao pipeline).
- [ ] O `config.yaml` já tem `posting.publishers.instagram: instagram`. Para voltar ao dry run
      sem apagar os secrets, muda para `dry-run`.

## 5. Primeiro post real (teste)

- [ ] Escolhe uma promoção verdadeira que queiras mesmo publicar e aprova-a (página de revisão
      no telemóvel ou `uv run escapadinha deal approve <id>`).
- [ ] A execução seguinte aplica a aprovação, mete o Instagram na próxima hora livre (09:00,
      13:00 ou 19:00) e segue o caminho completo: o site passa a ter a página e as imagens JPEG
      da promoção. Vê a hora com `uv run escapadinha queue list` (depois de
      `uv run escapadinha store pull`).
- [ ] Na primeira execução depois dessa hora (o pipeline corre de 2 em 2 horas), o registo do
      passo **Run** no GitHub Actions mostra `publicação Instagram deal <id>: publicada
      (instagram)` e `Story Instagram deal <id>: publicada`. Se aparecer *à espera*, o motivo
      vem a seguir (por exemplo as imagens ainda não estão no site: espera pelo deploy).
- [ ] Confirma no Instagram o carrossel (todas as imagens, legenda com "Publicidade") e a story.
- [ ] Na execução seguinte a promoção fica **publicada** e a página dela no site mostra
      **Ver no Instagram**. `uv run escapadinha queue list --all` mostra o link do post.
- [ ] Diz-me se correu bem (fecho a issue #24) ou cola-me a linha do erro.

## 6. Quando o pipeline renovar o token

O token dura 60 dias. Quando faltarem menos de 10 (ou, para um token novo, um dia depois de o
pipeline o ver pela primeira vez, para saber quando expira), o pipeline renova-o sozinho. O
GitHub não deixa o pipeline mudar um secret, por isso:

- o token novo fica guardado no bucket R2 (`private/instagram/token.json`) e as execuções
  seguintes usam-no: **as publicações não param** se demorares a atualizar o secret;
- o registo da execução e o `uv run escapadinha queue list` dizem: *"Token do Instagram
  renovado a …: atualiza o secret INSTAGRAM_ACCESS_TOKEN no GitHub e no .env"*.

Para atualizar:

- [ ] No PC: `uv run escapadinha instagram token`. Mostra o token novo e até quando vale (só no
      teu PC: no CI o comando recusa-se, para o token nunca ficar num registo).
- [ ] Copia-o para o secret `INSTAGRAM_ACCESS_TOKEN` no GitHub (**Settings** → **Secrets and
      variables** → **Actions** → `INSTAGRAM_ACCESS_TOKEN` → **Update**) e para o `.env`.
- [ ] Na execução seguinte o aviso desaparece do `queue list`.

## Se algo correr mal

- *"Token do Instagram inválido ou expirado"* ou *"O token do Instagram expirou a …"*: nada é
  publicado e as publicações esperam (não contam como falhas). Gera um token novo (passo 3) e
  atualiza o `.env` e o secret (passo 4).
- *"A app não tem permissão para publicar"*: falta uma das duas permissões do passo 2, ou a
  conta deixou de ser testadora da app.
- *"Limite de publicações do Instagram: … nas últimas 24 h"*: a Meta limita as publicações
  feitas pela API por dia; o post espera pela execução seguinte.
- *"O Instagram recusou as imagens: …"*: a publicação é cancelada com o motivo (por exemplo
  formato ou proporção); diz-me, é um problema das imagens.
- Outro erro da API: o post fica na fila e é tentado nas execuções seguintes; ao fim de 5
  falhas é cancelado com o motivo (`queue list --all`). Uma story que falhe nunca volta a
  publicar o carrossel: é tentada outra vez durante 6 horas e depois fica como *não sai*.
