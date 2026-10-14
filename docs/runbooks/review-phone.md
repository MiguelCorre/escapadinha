# Fila de revisão no telemóvel: primeiro teste de ponta a ponta

Guia passo a passo para o Miguel (issue #9, decisão D29). Serve para confirmar, do telemóvel, que
a fila em https://pontonomada.pt/review funciona: entrar pelo Cloudflare Access, ver as
candidatas, verificar um preço, decidir, e ver o pipeline aplicar a decisão. Marca cada caixa
quando terminares.

**O que já está feito por ti** (não repetir): a aplicação do Access em `pontonomada.pt/review`
só com o teu e-mail; no projeto Pages `ondestaanocas` (Production) as variáveis
`ACCESS_TEAM_DOMAIN` e `ACCESS_AUD`, os segredos `GITHUB_DISPATCH_TOKEN` e `TRAVELPAYOUTS_TOKEN`, e
o binding R2 `STORE`.

## 0. Antes de começar

- [ ] O código do #9 está no ramo principal (o pipeline corre sempre a partir dele).
- [ ] Tens o telemóvel com o e-mail `miguelahpc@hotmail.com` à mão (o código do Access chega lá).
- [ ] Tempo: uns 15 minutos, mais a espera de uma execução do pipeline (2 a 5 minutos).

## 1. Publicar a Function

A Function vai para o ar com o site, no caminho completo do pipeline.

- [ ] GitHub → **Actions** → **Pipeline** → **Run workflow** → marca **Full path** → **Run
      workflow**. (No terminal: `gh workflow run pipeline.yml -f full=true`.)
- [ ] Espera que acabe a verde. No log do passo **Run** procura a linha do deploy com
      `https://….ondestaanocas.pages.dev`: é a publicação nova. (A primeira depois do #9 publica
      sempre, mesmo sem mudanças no site.)
- [ ] Cloudflare → **Workers & Pages** → `ondestaanocas` → **Deployments** → a mais recente →
      separador **Functions**: tem de listar as rotas `/review` e `/review/*`.

## 2. Confirmar que ninguém entra sem o Access

- [ ] Numa janela anónima do computador abre `https://ondestaanocas.pages.dev/review`. Tem de ir
      parar ao `pontonomada.pt` e pedir o e-mail do Access, nunca mostrar a fila.
- [ ] No terminal: `curl -s -o /dev/null -w "%{http_code}\n" https://pontonomada.pt/review -H "Cf-Access-Jwt-Assertion: x"`
      responde **302** (o Access manda para o login) e nunca **200**. Um token falso que chegue à
      Function recebe **403** "Acesso negado: …" (os testes automáticos cobrem esse caso). Se
      alguma vez vires a fila sem teres entrado, para aqui e avisa-me.

## 3. Entrar no telemóvel

- [ ] No telemóvel abre **https://pontonomada.pt/review**.
- [ ] Escreve o teu e-mail → **Send me a code** → copia o código do e-mail → entra.
- [ ] Vês "Fila de aprovação", a hora da fila ("Fila de dd/mm/aaaa às hh:mm") e "entraste como
      miguelahpc@hotmail.com". A página cabe no ecrã sem deslizar para os lados.
- [ ] Se aparecer "Ainda não há snapshot da fila", espera pela próxima execução (de 2 em 2 horas)
      ou repete o passo 1.
- [ ] Se a fila estiver vazia ("Nenhum deal por rever"), espera por uma candidata real: não se
      inventam promoções. Continua quando houver pelo menos uma em **Por rever**.

## 4. Ver uma candidata e verificar o preço

- [ ] Numa candidata: desliza os slides, confirma preço, datas e noites, companhia, desconto,
      "encontrado a …" e "verificado a …" (hora de Lisboa).
- [ ] Carrega em **Verificar preço**. Em poucos segundos aparece "Preço confirmado agora:
      continua a … €" (verde) ou "O preço mudou: …" (vermelho). Nada fica guardado.
- [ ] Abre **Legenda do Instagram** → **Copiar legenda** e cola numa nota: o texto chega
      completo. (O texto do WhatsApp só aparece quando o pipeline o gerar, num ticket seguinte.)

## 5. Decidir

Escolhe uma candidata que **queres mesmo publicar**: aprovar põe-na no site. Se nenhuma serve,
faz o teste com **Rejeitar** numa que rejeitarias de qualquer forma.

- [ ] (Opcional) escreve uma nota.
- [ ] Carrega em **Aprovar** (o botão diz "A verificar preço…"). Resultados possíveis:
  - verde: "Preço confirmado (continua a … €) e aprovação registada. O pipeline aplica-a dentro
    de minutos." → segue para o passo 6;
  - vermelho: "O preço mudou (…): não aprovado." → está certo, nada foi guardado; experimenta
    outra candidata ou rejeita esta;
  - amarelo: "… a decisão ficou guardada; aplica-se no próximo run" → o aviso ao GitHub falhou
    (vê o passo 7), mas a decisão não se perdeu.
- [ ] Recarrega a página: a candidata mostra "Decisão pendente: aprovar (o teu e-mail, hora)" e já
      não tem botões de decisão.

## 6. Ver o pipeline aplicar a decisão

- [ ] GitHub → **Actions** → aparece uma execução do **Pipeline** iniciada por
      **repository_dispatch** segundos depois da tua decisão.
- [ ] Quando acabar a verde, recarrega a fila: a promoção passou para **Aprovados** e em
      **Decisões recentes** aparece "aprovar o deal N (o teu e-mail): aplicada".
- [ ] A promoção aparece no site público (`https://pontonomada.pt/`).
- [ ] (Opcional) Em **Aprovados**, depois de publicares no Instagram, cola o link do post e
      carrega em **Marcar como publicado**.

## 7. Se algo falhar

- **403 depois de entrares no Access:** confirma no projeto Pages que `ACCESS_AUD` é o
  *Application Audience (AUD) Tag* da aplicação do Access (Zero Trust → Access → Applications →
  a aplicação → **Overview**) e que `ACCESS_TEAM_DOMAIN` é `pontonomada.cloudflareaccess.com`
  (sem `https://`). Depois de mudar variáveis, repete o passo 1 (só valem numa publicação nova).
- **"O aviso ao GitHub falhou (HTTP 401/403/404)":** o `GITHUB_DISPATCH_TOKEN` expirou ou não tem
  *Contents: Read and write* no repositório `escapadinha`. Cria outro, atualiza o segredo e
  repete o passo 1. A decisão já guardada é aplicada na próxima execução agendada.
- **"Não foi possível verificar o preço agora: HTTP 401":** o `TRAVELPAYOUTS_TOKEN` do Pages está
  errado. **HTTP 429:** limite da API; tenta daqui a um minuto.
- **"Ainda não há snapshot"** ou slides em falta: o binding `STORE` não aponta para o bucket do
  pipeline.
- **"A fila tem mais de 3 h":** o pipeline está parado; vê o separador **Actions**.

Quando tudo acima estiver marcado, diz-me e eu fecho a última caixa do #9.
