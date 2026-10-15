# Publicação automática no Telegram

Guia passo a passo para o Miguel (issue #21, decisão D38). O pipeline já sabe publicar cada
promoção aprovada num **canal público do Telegram**: uma mensagem com a imagem de capa da
promoção e o mesmo texto do WhatsApp (destino, preço, datas, quando o preço foi encontrado e
verificado, o link de reserva e o aviso de publicidade). Sai na primeira execução depois da
aprovação em que a imagem de capa já está no site (`https://pontonomada.pt/img/promos/<id>/slide_01.jpg`):
normalmente a execução que aplica a aprovação faz o deploy e a seguinte (até 2 horas depois)
publica. Antes de publicar confirma o preço, como no Instagram.

A mensagem do Telegram **não** marca a promoção como publicada (isso continua a ser o Instagram,
o canal principal); o link da mensagem fica guardado na fila (`queue list --all`).

Enquanto faltar `TELEGRAM_BOT_TOKEN` ou `TELEGRAM_CHANNEL`, nada é publicado no Telegram e as
publicações **ficam à espera** (não se perdem nem contam como falhas): o registo da execução e o
`queue list` dizem *"À espera do bot: faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHANNEL"*. Uma
promoção que expire ou seja rejeitada entretanto cancela a sua publicação, como sempre.

## 1. Criar o canal público

- [ ] Na app do Telegram (telemóvel ou PC): **Nova mensagem** (ícone do lápis) → **Novo canal**.
- [ ] Nome: o provisório (por exemplo "Ponto Nómada · Promoções de voos"); a descrição pode
      dizer que as mensagens têm links de afiliado.
- [ ] Tipo de canal: **Público**. Escolhe o link, por exemplo `t.me/pontonomada`: o que vem
      depois de `t.me/`, com um @ à frente, é o **@handle** do canal (aqui `@pontonomada`).
      Aponta-o: é ele que vai no `TELEGRAM_CHANNEL` (passo 4).
- [ ] Não precisas de adicionar ninguém.

## 2. Criar o bot no @BotFather

- [ ] No Telegram procura **@BotFather** (tem o visto azul de conta verificada) e abre a
      conversa.
- [ ] Escreve `/newbot`.
- [ ] Nome do bot: por exemplo "Ponto Nómada".
- [ ] Nome de utilizador do bot: tem de acabar em `bot`, por exemplo `pontonomada_promos_bot`.
- [ ] O @BotFather responde com o **token** (algo como `1234567890:AAH…`). Copia-o: é o
      `TELEGRAM_BOT_TOKEN`. Quem tiver este token publica em nome do bot: nunca o colas em
      lado nenhum a não ser no `.env` e no secret do GitHub (passo 4). Se escapar, no @BotFather
      `/revoke` gera outro.

## 3. Pôr o bot como administrador do canal

- [ ] Abre o canal → toca no nome do canal → **Administradores** → **Adicionar administrador**.
- [ ] Procura o bot pelo nome de utilizador (`@pontonomada_promos_bot`) e escolhe-o.
- [ ] Nas permissões, deixa ligada **Publicar mensagens** (é a única de que precisa); podes
      desligar as outras. Guarda.

## 4. Onde pôr os dois valores

- [ ] No `.env` do PC (nunca no Git):

  ```
  TELEGRAM_BOT_TOKEN=1234567890:AAH...
  TELEGRAM_CHANNEL=@pontonomada
  ```

- [ ] No GitHub: repositório → **Settings** → **Secrets and variables** → **Actions** → **New
      repository secret**, um para cada: `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHANNEL` (o workflow
      já os passa ao pipeline).
- [ ] O `config.yaml` já tem `posting.publishers.telegram: telegram`. (Com `dry-run` o pipeline
      só escreve no registo o que publicaria e dá a publicação como feita: essa promoção já não
      sai no Telegram. Para pausar, é melhor tirar os secrets: as publicações esperam.)

## 5. Primeira mensagem real (teste)

- [ ] Escolhe uma promoção verdadeira que queiras mesmo publicar e aprova-a (página de revisão
      no telemóvel ou `uv run escapadinha deal approve <id>`).
- [ ] A execução seguinte aplica a aprovação e põe o Telegram na fila logo a seguir. Nessa
      execução a imagem ainda não está no site, por isso o `uv run escapadinha queue list`
      (depois de `uv run escapadinha store pull`) mostra a publicação do Telegram como
      *agendada: As imagens ainda não estão no site (…): espera pelo próximo deploy.* É normal.
- [ ] Na execução seguinte, o registo do passo **Run** no GitHub Actions mostra `publicação
      Telegram deal <id>: publicada (telegram)`.
- [ ] Confirma no canal: a imagem de capa, o texto com o link de reserva e o aviso
      "Publicidade · Este post contém links de afiliado…".
- [ ] `uv run escapadinha queue list --all` mostra a linha do Telegram como *publicada
      (telegram) · https://t.me/pontonomada/<número>*: abre o link e confirma que vai dar à
      mensagem. O mesmo link aparece no `queue list` ao lado da publicação do Instagram dessa
      promoção (enquanto não sai) e no `uv run escapadinha deal check <id>`.
- [ ] Diz-me se correu bem (fecho a issue #21) ou cola-me a linha do erro.

## Se algo correr mal

- *"À espera do bot: faltam …"*: falta um dos dois secrets (passo 4).
- *"TELEGRAM_CHANNEL tem de ser o @handle do canal público …"* (no topo do `queue list` e no
  registo da execução): o `TELEGRAM_CHANNEL` tem de ser o @handle do passo 1, com o @
  (`@pontonomada`), ou o id numérico do canal; nem o link `t.me/…` nem o nome sem @. O resto do
  pipeline continua (recolha, site, Instagram); só as publicações do Telegram esperam, sem
  contar como falhas. Corrige o `.env` e o secret: a execução seguinte publica-as.
- *"O Telegram recusou o canal (…): confirma que o canal … existe e que o bot é administrador
  com permissão para publicar"*: o canal não existe com esse @handle, ou o bot não é
  administrador com **Publicar mensagens** (passo 3). **Nada se perde:** as publicações ficam à
  espera (não contam como falhas) e o aviso aparece no topo do `queue list`. Corrige; a
  execução seguinte publica as que estiverem à espera e o aviso desaparece.
- *"O Telegram recusou o token do bot"*: o `TELEGRAM_BOT_TOKEN` está errado ou foi revogado.
  As publicações esperam (não contam como falhas); gera outro no @BotFather (`/token` ou
  `/revoke`) e atualiza o `.env` e o secret.
- *"O Telegram não respondeu ao envio (…): a mensagem pode ter saído"* ou *"Uma tentativa
  anterior (…) enviou a mensagem ao Telegram sem guardar a resposta"*: o pedido chegou ao
  Telegram mas a resposta perdeu-se. O Telegram não deixa o bot ver o que está no canal, por
  isso o pipeline **não volta a enviar sozinho** (era pior sair repetida); a publicação fica
  cancelada e o topo do `queue list` diz *"Envio ao Telegram por confirmar: deal <id> …"*.
  - [ ] Vai ao canal e procura essa promoção.
  - [ ] Se lá está: não há nada a fazer (o aviso fica; é só informativo).
  - [ ] Se não está: `uv run escapadinha queue retry <id> telegram`. Sem R2 a publicação volta
        logo à fila; com R2, a próxima execução põe-na de novo na fila. Sai uma vez, na
        execução seguinte. O comando recusa-se (com o motivo) se a mensagem saiu mesmo ou se
        não há envio nenhum por confirmar.
- *"Limite de mensagens do Telegram"*: o Telegram pediu para esperar; a execução seguinte envia.
- *"As imagens ainda não estão no site"*: normal logo a seguir a uma aprovação (o deploy vem a
  seguir). Se ao fim de 24 horas (`telegram.images_wait_hours`) continuarem sem aparecer, cada
  execução conta uma falha e ao fim de 5 a publicação é cancelada com o motivo: vê se o deploy
  do site está a falhar.
- *"O Telegram não conseguiu ir buscar a imagem"*: o Telegram não conseguiu descarregar a capa
  nesse momento; é tentada outra vez nas execuções seguintes (ao fim de 5 falhas, cancelada).
- *"O Telegram recusou esta mensagem: …"* (dimensões ou formato da imagem, texto demasiado
  longo) ou *"O texto tem … caracteres e o Telegram aceita 1024 numa foto"*: essa publicação é
  cancelada (o texto nunca é cortado: podia perder o link ou o aviso de publicidade); diz-me, é
  um problema das imagens ou do modelo de texto. Se a quiseres no canal, publica-a à mão
  (abaixo).
- Outro erro da API: a publicação fica na fila e é tentada nas execuções seguintes; ao fim de 5
  falhas é cancelada com o motivo (`queue list --all`).

**Publicar à mão:** na página de revisão (telemóvel ou `uv run escapadinha review`), separador
das aprovadas, copia o **texto do WhatsApp** dessa promoção; no canal, envia a imagem de capa
(`https://pontonomada.pt/img/promos/<id>/slide_01.jpg`) com esse texto como legenda.
