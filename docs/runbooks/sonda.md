# A sonda no teu PC: Google Flights e Kayak como comparação (DECISIONS D48, D49)

A sonda é um comando do próprio projeto (`escapadinha probe`) que abre o Chrome **no teu PC**,
pesquisa as viagens que o pipeline lhe pede no Google Flights e depois no Kayak (D49: dois
**motores**, no mesmo browser, uma pesquisa de cada vez, nunca em paralelo) e grava o que viu
(preço mais barato sem escalas e, no Google Flights, quem o vende: companhia, eDreams, Kiwi…) no
armazenamento R2. Na corrida seguinte, o pipeline importa esses preços como **fontes de
comparação** (`google_flights`, `kayak`): aparecem como "Também visto · Google Flights via eDreams
· 55 €" e "Kayak · 44 €" ao lado de cada promoção, nas páginas de revisão e na página pública.
Nunca fazem uma promoção sozinhos nem levam um botão de reserva.

**Porquê no teu PC e não no GitHub:** com o teu IP de casa e um perfil real do Chrome, uma pesquisa
de cada vez a ritmo humano é o que o Google espera de uma pessoa a comparar preços. A sonda não
se esconde: sem plugins de disfarce, sem proxies, sem resolver captchas. Se o Google mostrar um
muro (pedido de consentimento, "unusual traffic", captcha), a sonda pára ali e fica em pausa 24 h.

## O que precisas

- [ ] O Google Chrome instalado (está: `C:\Program Files\Google\Chrome\Application\chrome.exe`).
- [ ] O repositório em `C:\Users\DESKTOP\Downloads\escapadinha` com o `uv` (o mesmo que usas para
  `store pull`); o `.env` com as chaves R2 já lá está. Nada mais a instalar: o Playwright já é
  uma dependência do projeto e usa o teu Chrome, não descarrega outro browser.
- [ ] O PC ligado e com sessão iniciada nas horas em que a sonda deve correr (a janela do Chrome
  precisa de um ambiente de trabalho; pode estar bloqueado).

## Passo 1: o perfil do Chrome da sonda (uma vez)

```bash
cd C:/Users/DESKTOP/Downloads/escapadinha && uv run escapadinha probe setup
```

Abre o Chrome com um perfil só da sonda (`%USERPROFILE%\.pontonomada\probe-chrome`, não o teu
perfil pessoal) na página do Google Flights e depois na do Kayak e, em cada uma, se aparecer o
pedido de consentimento, escolhe **Rejeitar tudo** / **Recusar tudo** (a opção que menos dados
guarda) e fecha. Se uma página de consentimento não tiver esse botão, o comando diz-to: responde
tu na janela e fecha-a. Não inicies sessão em nenhuma conta nesse perfil. Se já tinhas o perfil
do D48, basta correr o `setup` outra vez para recusar o consentimento do Kayak.

## Passo 2: uma corrida de teste

Só depois de o pipeline ter escrito a lista (a primeira corrida depois do D48 fá-lo; `probe status`
mostra "Lista a pesquisar: N viagens"):

```bash
cd C:/Users/DESKTOP/Downloads/escapadinha && uv run escapadinha probe run --limit 2
```

Vais ver o Chrome abrir, pesquisar duas viagens, cada uma primeiro no Google Flights (três
páginas: ida, regresso, opções de reserva) e depois no Kayak (uma página: a lista de resultados
diretos, do mais barato), com pausas de 20 a 45 segundos entre viagens (metade entre os dois
motores), e fechar. No fim imprime, por exemplo, `probe: ok, 2 of 2 trips searched, 2 with
booking options; google_flights: 2 searched, 2 priced; kayak: 2 searched, 2 priced`. O estado
fica em:

```bash
cd C:/Users/DESKTOP/Downloads/escapadinha && uv run escapadinha probe status
```

Na corrida seguinte do pipeline (de 30 em 30 minutos) o resumo da execução no GitHub traz a linha
`Probe results: 1 files, 4 of 4 searches with booking options, …` (cada viagem conta uma pesquisa
por motor) e as páginas de revisão passam a mostrar "Também visto · Google Flights via …" e
"Kayak …" nas promoções pesquisadas.

## Passo 3: agendar no Windows (de 30 em 30 minutos, às :05 e :35)

Entre os tiques do Worker (:17 e :47), para que cada corrida da sonda seja importada pela corrida
seguinte do pipeline. Numa janela do PowerShell ou do cmd, **com a tua sessão** (a tarefa fica
"Executar apenas quando o utilizador tiver sessão iniciada", que é o que a janela do Chrome
precisa):

```bash
mkdir -p "$USERPROFILE/.pontonomada" && schtasks /Create /TN "Pontonomada sonda" /SC MINUTE /MO 30 /ST 00:05 /TR "cmd /c cd /d C:\Users\DESKTOP\Downloads\escapadinha && uv run escapadinha probe run >> %USERPROFILE%\.pontonomada\sonda.log 2>&1" /F
```

- [ ] Confirma com `schtasks /Query /TN "Pontonomada sonda" /V /FO LIST` que o "Modo de início de
  sessão" é interativo e que a próxima execução está marcada.
- [ ] Depois da primeira execução agendada, lê `%USERPROFILE%\.pontonomada\sonda.log`.

Cada corrida demora cerca de 12 a 15 minutos para 10 viagens (`probe.max_trips`) nos dois
motores. Se preferires menos tempo de janela aberta, baixa `max_trips` no `config.yaml`, alonga
as pausas, ou deixa só um motor em `probe.engines` (`[google_flights]` ou `[kayak]`; a ordem da
lista é a ordem em que cada viagem é pesquisada).

## Parar, pausar, retomar

- **Parar de vez:** `schtasks /Delete /TN "Pontonomada sonda" /F`.
- **Pausar:** `schtasks /Change /TN "Pontonomada sonda" /DISABLE` (e `/ENABLE` para retomar), ou
  `probe.enabled: false` no `config.yaml` (a tarefa corre mas não faz nada).
- **Pausa automática, por motor:** depois de um muro **esse motor** não pesquisa durante
  `probe.paused_hours` (24) e o outro continua; `probe status` mostra, por motor, `paused until …
  (reason)` (`consent`: repete o passo 1; `unusual_traffic`, `captcha` ou, no Kayak,
  `press_and_hold`: espera; se voltar a acontecer, baixa `max_trips` e alonga as pausas, nunca o
  contrário). Com os dois motores em pausa a sonda não abre o browser. Para retomar antes do
  prazo apaga a entrada do motor em `engines` no `probe/state.json` do bucket (ou o ficheiro).
- **PC desligado:** não acontece nada; o pipeline continua sem a comparação e retoma quando a
  sonda voltar a correr.

## O que a sonda nunca faz

Não inicia sessão, não guarda cookies além da recusa do consentimento, não muda de identidade
(user-agent, IP), não resolve captchas nem carrega no "press and hold" do Kayak, não pesquisa em
paralelo (um browser, um motor de cada vez) e não decide o que pesquisar: lê
`probe/wanted.json`, que o pipeline escreve em cada corrida (as promoções abertas primeiro, depois
a oferta mais barata de cada rota, em rotação). Os preços que grava são os que a página mostrou,
com a hora em que os leu; nunca viram uma promoção por si (D47: uma promoção liga a, e é verificada
em, uma fonte que o pipeline consegue perguntar sozinho).
