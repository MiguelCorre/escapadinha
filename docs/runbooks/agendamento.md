# Agendamento: o pipeline de 30 em 30 minutos

Guia passo a passo para o Miguel (issue #43, decisão D41). O horário do próprio GitHub não é de
confiança: as execuções marcadas de 2 em 2 horas chegavam com 4,4 a 6,8 horas de intervalo
(mediana 5,5 h). Agora quem dá a hora é um **Worker da Cloudflare** (`workers/scheduler/`, plano
gratuito). De 30 em 30 minutos, aos :17 e aos :47 (hora UTC; de 2 em 2 horas até à D46), pede ao
GitHub uma execução do workflow
**Pipeline** (`pipeline.yml`), igual à do botão **Run workflow** sem *Full path*: o pipeline decide
sozinho se segue o caminho rápido ou o completo.

- **Sem execuções repetidas:** se uma execução começou há menos de 20 minutos (por exemplo a que
  uma decisão tua no telemóvel lançou), o Worker não pede outra nesse tique.
- **Minutos do GitHub (D46):** o repo é público e o GitHub não conta os minutos dos runners
  standard (`ubuntu-latest`, os únicos que usamos) em repositórios públicos: as 48 execuções por
  dia (cerca de 3 200 minutos por mês) não custam nada e não há quota a esgotar. Só se o repo
  passar a privado é que voltam os 2 000 minutos gratuitos do plano Free; nesse caso, antes de
  publicar o Worker, define um limite de despesa para o Actions (a tua fotografia → **Settings** →
  **Billing and licensing** → **Spending limits** → Actions, cerca de 10 USD/mês a 0,008 USD por
  minuto), ou o pipeline para quando a quota acabar.
- **Pausa:** com o workflow desligado (`gh workflow disable pipeline.yml`, como no restauro de
  uma cópia da base de dados), o Worker não faz nada.
- **Rede de segurança:** o workflow **Pipeline fallback** do GitHub corre de 6 em 6 horas (quando o
  GitHub se lembra). Só lança o pipeline se não houve nenhuma execução nas últimas 3 horas, ou seja,
  se o Worker falhou. Nesse caso a execução do fallback fica **vermelha de propósito**, para o
  GitHub te mandar um e-mail.
- **Aviso no registo:** quando a execução anterior começou há mais de 2 horas, o registo do
  pipeline (e o resumo da execução) diz *"Warning: the previous run (#N) started 5 h 07 min ago,
  more than 2 h: the half-hourly schedule missed runs."*

O Worker precisa de um token do GitHub que só sirva para lançar workflows deste repositório. Fica
guardado como **segredo do Worker** na Cloudflare: nunca no repositório, no `.env`, nos segredos do
GitHub ou no chat.

**Quando:** logo a seguir ao código do #43 entrar no `master`. A partir daí o `pipeline.yml` já não
tem horário próprio: até o Worker estar no ar só corre a rede de segurança (de 6 em 6 horas, com um
e-mail de cada vez).

## 0. Antes de começar

- [ ] O código do #43 está no `master` e no PC fizeste `git pull` (vais precisar da pasta
      `workers/scheduler`).
- [ ] Node.js 22 ou mais recente no PC (já o tens por causa do site): `node --version`.
- [ ] Tempo: uns 15 minutos, mais umas duas horas e meia de espera até à verificação (secção 4).

## 1. Criar o token no GitHub

- [ ] github.com → a tua fotografia (canto superior direito) → **Settings** → **Developer
      settings** (no fim do menu da esquerda) → **Personal access tokens** → **Fine-grained
      tokens** → **Generate new token**.
- [ ] **Token name:** `pontonomada-scheduler`. **Description:** "Worker da Cloudflare: lança o
      pipeline de 2 em 2 horas".
- [ ] **Resource owner:** a tua conta, `MiguelCorre`.
- [ ] **Expiration:** 1 ano (*Custom* com a data de daqui a um ano, se não houver a opção). Põe um
      lembrete no calendário uma semana antes: quando o token expira, o Worker deixa de conseguir
      lançar o pipeline (secção 6).
- [ ] **Repository access:** **Only select repositories** → escolhe só `MiguelCorre/escapadinha`.
- [ ] **Permissions** → **Repository permissions** → **Actions** → **Read and write**. Mais nada.
      (O GitHub acrescenta sozinho **Metadata: Read-only**, que é obrigatório.)
- [ ] **Generate token** → copia o token (começa por `github_pat_`). O GitHub só o mostra uma vez.
      Cola-o apenas no passo 3.

## 2. Publicar o Worker na Cloudflare

No terminal do PC (PowerShell), na pasta do projeto:

```powershell
cd workers\scheduler
npx --yes wrangler@4.149.0 login
```

- [ ] Abre-se o browser: entra na conta da Cloudflare (a do `pontonomada.pt`) e carrega em
      **Allow**. O terminal diz que a sessão ficou iniciada.

```powershell
npx --yes wrangler@4.149.0 deploy
```

- [ ] No fim aparece o Worker `pontonomada-scheduler` com `schedule: 17 */2 * * *`. Não tem endereço
      na web, de propósito: só corre pelo relógio.

## 3. Guardar o token como segredo do Worker

Ainda em `workers\scheduler`:

```powershell
npx --yes wrangler@4.149.0 secret put GITHUB_ACTIONS_TOKEN
```

- [ ] Quando o terminal pedir o valor (*Enter a secret value*), cola o token do passo 1 e carrega
      em Enter. Confirma que diz que o segredo `GITHUB_ACTIONS_TOKEN` foi carregado.
- [ ] Se o token ficou à vista no terminal, limpa-o (`cls`).

Sem terminal, pelo painel: Cloudflare → **Workers & Pages** → `pontonomada-scheduler` →
**Settings** → **Variables and Secrets** → **Add** → *Type* **Secret**, *Variable name*
`GITHUB_ACTIONS_TOKEN`, *Value* o token → **Deploy**.

- [ ] Confirma no painel (Cloudflare → **Workers & Pages** → `pontonomada-scheduler` →
      **Settings**):
  - em **Variables and Secrets**: `GITHUB_ACTIONS_TOKEN` como *Secret* (o valor não se vê) e as
    quatro variáveis `GITHUB_REPOSITORY`, `WORKFLOW`, `REF` e `SKIP_IF_RUN_WITHIN_MINUTES`;
  - em **Trigger Events** (cron): `17 */2 * * *`.
- [ ] (Opcional) `npx --yes wrangler@4.149.0 logout`: o PC deixa de ter acesso à conta da
      Cloudflare pelo wrangler. Para voltar a publicar o Worker, repete o `login`.

## 4. Verificar: duas execuções com 30 minutos de intervalo

O Worker corre aos :17 e aos :47 de cada hora (UTC; em Lisboa a mesma coisa no inverno, uma hora
mais tarde no verão).

- [ ] Passado o primeiro desses minutos depois do passo 3: Cloudflare → `pontonomada-scheduler` →
      separador **Logs** (ou **Observability**). Aparece uma linha *"Dispatched pipeline.yml on
      master: no run in the last 20 min."* Também pode ser *"… started N min ago, within 20 min:
      nothing dispatched."*, se outra execução tinha começado pouco antes: está certo, a
      verificação passa para a meia hora seguinte.
- [ ] Meia hora depois, outra linha *"Dispatched …"*.
- [ ] No terminal:

  ```bash
  gh run list --workflow pipeline.yml --event workflow_dispatch --limit 5
  ```

  As duas execuções mais recentes estão verdes e começaram com cerca de 30 minutos de diferença,
  pouco depois dos :17 e dos :47 (coluna **AGE**; as horas exatas com
  `gh run list --workflow pipeline.yml --event workflow_dispatch --limit 5 --json createdAt,conclusion`).
- [ ] No registo de cada uma (passo **Run**) **não** aparece *"Warning: the previous run …"*.
- [ ] (Opcional) A rede de segurança: `gh workflow run pipeline-fallback.yml`. Acaba **verde**,
      com *"pipeline.yml run N (…) started N min ago, within 180 min: nothing dispatched."* no
      registo.

Quando as duas execuções estiverem no `gh run list`, diz-me e eu fecho o #43.

## 5. No dia a dia

- Não há nada a fazer: as execuções aparecem em **Actions** → **Pipeline** como
  *workflow_dispatch*.
- **Parar tudo** (por exemplo para restaurar uma cópia da base de dados, README → *Restore from a
  backup*): `gh workflow disable pipeline.yml`. O Worker e a rede de segurança respeitam-no. Para
  voltar: `gh workflow enable pipeline.yml`.
- **Execução à mão:** como antes, `gh workflow run pipeline.yml` (ou com `-f full=true`). Conta como
  execução: o Worker não lança outra nos 45 minutos seguintes.
- **Mudar o Worker** (raro): depois de o código mudar em `workers/scheduler/`, na pasta,
  `npx --yes wrangler@4.149.0 deploy` (com `login` antes, se fizeste `logout`). O segredo mantém-se.
- **Minutos do GitHub Actions:** cada execução do pipeline conta cerca de 2 minutos e a recolha
  diária, uma vez por dia, cerca de 5 (o GitHub arredonda cada job ao minuto): cerca de 1000 por
  mês, mais o CI do site. O plano grátis dá 2000 por mês;
  se acabarem, o GitHub deixa de correr o pipeline até ao mês seguinte. Vê o consumo em github.com
  → **Settings** → **Billing and licensing** → **Usage** (filtra por *Actions*) e avisa-me se
  passar de 1500 antes do fim do mês (as opções estão na decisão D41).

## 6. Se alguma coisa falhar

- **E-mail do GitHub sobre o "Pipeline fallback"** (a execução falhou) com *"The fallback had to
  dispatch the pipeline, so the Cloudflare Worker missed its runs …"* no registo: durante 3 horas o
  Worker não lançou nada. Os dados continuam a chegar pela rede de segurança, mas de 6 em 6 horas.
  Vê os **Logs** do Worker:
  - *"Dispatch of pipeline.yml refused: HTTP 401: Bad credentials."*: o token expirou ou foi
    apagado. Cria outro (passo 1) e repete o passo 3.
  - *"HTTP 403: Resource not accessible by personal access token"*: o token não tem **Actions:
    Read and write** ou não inclui o repositório `escapadinha`. Corrige-o no GitHub (Fine-grained
    tokens → o token → **Edit**) ou cria outro e repete o passo 3.
  - *"HTTP 404"* ou *"HTTP 422 … Unexpected inputs"*: o repositório ou o `pipeline.yml` mudaram.
    Diz-me.
  - *"GITHUB_ACTIONS_TOKEN is not set"*: falta o segredo; repete o passo 3.
  - Nenhuma linha nos Logs: em **Settings** → **Trigger Events** confirma que o cron
    `17 */2 * * *` lá está; se não estiver, repete o passo 2.
- **E-mail do fallback com "Dispatch of pipeline.yml refused: …"**: foi o GitHub que recusou a
  execução à própria rede de segurança. Raro; diz-me.
- **Logo depois de `gh workflow enable pipeline.yml`** pode chegar um desses e-mails: enquanto o
  workflow esteve desligado não houve execuções. Se não se repetir, não é nada.
- **"Warning: the previous run … more than 3 h" no registo do pipeline** sem e-mail do fallback: a
  rede de segurança ainda não correu (o GitHub atrasa-se) ou um tick foi saltado e o seguinte
  atrasou-se. Se aparecer em várias execuções seguidas, vê os Logs do Worker como acima.
