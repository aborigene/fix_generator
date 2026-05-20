# FIX Message Generator — B3 EntryPoint

Gerador de mensagens **FIX 4.4** compatíveis com o protocolo **B3 EntryPoint** (PUMA Trading System), conforme a especificação oficial *EntryPoint Message Specification v2.40* (27/11/2025).

Foi construído para alimentar **Blueprints no BindPlane** com fluxos realistas de sessões de negociação de **Equities**, **Derivatives** e **FX** da B3, exercitando o parse binário do protocolo (separador SOH) e os principais cenários do ciclo de vida de uma ordem.

---

## Sumário

- [Visão geral](#visão-geral)
- [Instalação](#instalação)
- [Uso](#uso)
- [Fluxos disponíveis](#fluxos-disponíveis)
- [Saída — SOH vs. readable](#saída--soh-vs-readable)
- [Envio TCP para GIGAMON / tap](#envio-tcp-para-gigamon--tap)
- [Detalhes do protocolo](#detalhes-do-protocolo)
- [Ativos de referência](#ativos-de-referência)
- [Validação](#validação)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Referências](#referências)

---

## Visão geral

- **FIX 4.4** com header padrão B3 (8/9/35/49/56/34/52/...10)
- **BodyLength (tag 9)** e **Checksum (tag 10)** calculados corretamente conforme regra FIX
- Separador **SOH (`\x01`)** por padrão — pronto para BindPlane
- Flag `--readable` substitui SOH por `|` para inspeção visual
- Sequências (`MsgSeqNum`) independentes por direção (cliente/servidor)
- Timestamps em janela plausível de pregão (13:00–20:55 UTC = 10:00–17:55 BRT)
- Grupo `NoPartyIDs` (453/448/447/452) incluído nas mensagens de ordem
- 5 fluxos pré-construídos cobrindo ciclo de vida completo
- Modo `--send host:port` faz stream TCP direto (raw SOH) para alimentar tap/packet broker

---

## Instalação

Requer apenas **Python 3.10+**. Sem dependências externas.

```bash
git clone <repo> fix_generator
cd fix_generator
python3 fix_generator.py --list-flows
```

---

## Uso

```bash
# Lista os fluxos disponíveis
python3 fix_generator.py --list-flows

# Gera um fluxo com SOH real (uso em BindPlane)
python3 fix_generator.py --flow 1

# Saída legível com pipe e comentários de direção
python3 fix_generator.py --flow 1 --readable --annotate

# Stress test com 100 mensagens, salvando em arquivo binário
python3 fix_generator.py --flow 5 --volume 100 --output stress.fix

# Versão legível em arquivo
python3 fix_generator.py --flow 5 --volume 100 -r -o stress.txt

# Envio TCP direto para um tap/packet broker (ver seção "Envio TCP")
python3 fix_generator.py --flow 5 --volume 200 --send 10.0.0.5:9876 --delay-ms 100
```

### Flags

| Flag | Descrição |
|------|-----------|
| `--flow N` | Número do fluxo (1–5) |
| `-r`, `--readable` | Usa `\|` no lugar de SOH (debug; ignorado com `--send`) |
| `--annotate` | Prefixa cada mensagem com `# CLIENT->B3` / `# B3->CLIENT` (ignorado com `--send`) |
| `--volume N` | Apenas fluxo 5: total mínimo de mensagens (default 50) |
| `-o`, `--output FILE` | Escreve em arquivo em vez de stdout |
| `--send HOST:PORT` | Faz stream TCP raw (SOH) para o endpoint informado |
| `--delay-ms N` | Intervalo entre mensagens em modo `--send` (default 50ms) |
| `--loop` | Em `--send`, repete o fluxo indefinidamente até Ctrl-C |
| `--client-only` | Em `--send`, envia apenas mensagens `CLIENT->B3` |
| `--list-flows` | Lista fluxos e sai |

---

## Fluxos disponíveis

| # | Cenário | Mensagens |
|---|---------|-----------|
| 1 | Sessão básica com fill parcial → fill total | Logon, Heartbeat, NewOrder, ExecReport(New/Trade/Fill), Logout |
| 2 | Ordem aceita e cancelada | Logon, NewOrder, ExecReport(New), CancelRequest, ExecReport(Canceled), Logout |
| 3 | Ordem rejeitada pelo motor | Logon, NewOrder, ExecReport(Rejected, `OrderID=NONE`), Logout |
| 4 | Ordem modificada (replace de preço) | Logon, NewOrder, ExecReport(New), CancelReplace, ExecReport(Replaced), Logout |
| 5 | Stress test misto | ~50 msgs (configurável) com 3 cancelamentos, 2 rejeições, heartbeats a cada 10 |

### Exemplo — fluxo 1 (legível)

```
# CLIENT->B3
8=FIX.4.4|9=108|35=A|49=BROKER01|56=B3ENTRYPOINT|34=1|52=20260519-13:00:00.050|98=0|108=30|141=Y|553=CAUUSER01|554=PASS1234|10=054|
# B3->CLIENT
8=FIX.4.4|9=108|35=A|49=B3ENTRYPOINT|56=BROKER01|34=1|52=20260519-13:00:00.100|...
# CLIENT->B3
8=FIX.4.4|9=206|35=D|...|11=ORD-20260519-001|55=PETR4|54=1|38=100|40=2|44=38.50|...
# B3->CLIENT
8=FIX.4.4|9=206|35=8|...|150=0|39=0|14=0|151=100|...      ← New
# B3->CLIENT
8=FIX.4.4|9=223|35=8|...|150=F|39=1|14=40|151=60|31=38.50|32=40|...   ← Partial fill
# B3->CLIENT
8=FIX.4.4|9=223|35=8|...|150=2|39=2|14=100|151=0|31=38.50|32=60|...   ← Full fill
# CLIENT->B3
8=FIX.4.4|9=85|35=5|...|58=End of day session|10=194|
```

---

## Saída — SOH vs. readable

**Modo padrão (SOH binário)** — sem newlines, mensagens concatenadas:

```
8=FIX.4.4\x019=108\x0135=A\x01...\x0110=054\x018=FIX.4.4\x019=108\x0135=A\x01...
```

Este é o formato esperado pelo BindPlane. Quando `--output` é usado sem `--readable`/`--annotate`, o arquivo é escrito em modo binário (`wb`), preservando os bytes SOH exatos.

**Modo readable (`-r`)** — uma mensagem por linha, SOH substituído por `|`:

```
8=FIX.4.4|9=108|35=A|49=BROKER01|...|10=054|
8=FIX.4.4|9=108|35=A|49=B3ENTRYPOINT|...|10=050|
```

`--annotate` força saída por linha (com ou sem `-r`) e adiciona o comentário de direção.

---

## Envio TCP para GIGAMON / tap

O modo `--send HOST:PORT` abre uma conexão TCP e faz stream das mensagens **sempre em SOH binário** (a flag `--readable` é ignorada nesse modo — o que vai na rede é o que um peer FIX real veria). É a forma recomendada de gerar tráfego para um **GIGAMON tap**, um **packet broker** ou um agente que escuta numa porta TCP.

### Cenários

**Tap passivo / GIGAMON** — quer ver os dois lados da sessão (cliente + servidor) atravessando a interface monitorada:

```bash
python3 fix_generator.py --flow 5 --volume 200 \
    --send 10.0.0.5:9876 --delay-ms 100
```

**Replay infinito** — útil para deixar tráfego constante rodando enquanto você ajusta o Blueprint:

```bash
python3 fix_generator.py --flow 5 --send 10.0.0.5:9876 --loop --delay-ms 50
```

**FIX acceptor real** — quando o destino é um motor FIX que vai responder, não um tap passivo:

```bash
python3 fix_generator.py --flow 1 --send <fix-engine>:<port> \
    --client-only --delay-ms 200
```

`--client-only` filtra apenas mensagens `CLIENT->B3`; as respostas `B3->CLIENT` ficam de fora porque o motor real é quem vai gerá-las.

### Comportamento de rede

- `TCP_NODELAY` ativado — cada mensagem vai imediatamente, sem buffering Nagle. Importante para que o tap enxergue a cadência configurada por `--delay-ms`.
- Suporta IPv6 via `[::1]:9876`.
- Trata `BrokenPipeError` / `ConnectionResetError` se o peer fechar a conexão no meio do stream.
- Logs de progresso vão para **stderr** (stdout fica livre para pipes).
- `Ctrl-C` interrompe imediatamente; em `--loop` é a única forma de parar.

### Validação rápida (loopback)

Sobe um listener Python local, manda um fluxo e confere os bytes que chegaram:

```bash
# Terminal 1 — listener
python3 -c "
import socket
srv = socket.socket(); srv.bind(('127.0.0.1', 19876)); srv.listen(1)
conn, _ = srv.accept(); buf = b''
while True:
    chunk = conn.recv(4096)
    if not chunk: break
    buf += chunk
print(f'{len(buf)} bytes, {buf.count(chr(1).encode() + b\"10=\")} msgs')
"

# Terminal 2 — sender
python3 fix_generator.py --flow 1 --send 127.0.0.1:19876 --delay-ms 10
```

### Alternativas

Se você não precisa de timing controlado, dá para usar `netcat` consumindo a saída padrão (o script já emite SOH binário em modo default):

```bash
python3 fix_generator.py --flow 5 | nc 10.0.0.5 9876
```

Para fidelidade a nível de pacote (timing exato, MAC/IP source customizados), gere um PCAP e use `tcpreplay` — fora do escopo deste script.

---

## Detalhes do protocolo

### Header obrigatório

| Tag | Campo | Valor |
|-----|-------|-------|
| 8 | BeginString | `FIX.4.4` |
| 9 | BodyLength | Bytes entre o SOH após `9=...` e o SOH antes de `10=` |
| 35 | MsgType | Ver tabela abaixo |
| 49 | SenderCompID | `BROKER01` (cliente) ou `B3ENTRYPOINT` (B3) |
| 56 | TargetCompID | Inverso de 49 |
| 34 | MsgSeqNum | Sequencial **por direção** |
| 52 | SendingTime | `YYYYMMDD-HH:MM:SS.mmm` UTC |
| 10 | CheckSum | `sum(bytes) mod 256`, 3 dígitos |

### MsgTypes suportados

| MsgType | Mensagem | Builder |
|---------|----------|---------|
| `A` | Logon | `logon_body()` |
| `0` | Heartbeat | `heartbeat_body()` |
| `5` | Logout | `logout_body()` |
| `D` | NewOrderSingle | `new_order_single_body()` |
| `F` | OrderCancelRequest | `cancel_request_body()` |
| `G` | OrderCancelReplaceRequest | `cancel_replace_body()` |
| `8` | ExecutionReport | `execution_report_body()` |

### Cálculo do BodyLength e Checksum

- **BodyLength**: contagem em bytes ASCII do segmento iniciando logo após o SOH que segue `9=<N>` e terminando no SOH imediatamente antes de `10=`.
- **Checksum**: soma de **todos os bytes** desde `8=FIX.4.4...` até (inclusive) o SOH que precede `10=`, módulo 256, formatado em 3 dígitos.

A função `build_message()` em [fix_generator.py](fix_generator.py) implementa as duas regras e é usada uniformemente em todas as mensagens.

### ExecType / OrdStatus

| Cenário | `150` (ExecType) | `39` (OrdStatus) |
|---------|------------------|------------------|
| Aceita | `0` (New) | `0` (New) |
| Fill parcial | `F` (Trade) | `1` (PartiallyFilled) |
| Fill total | `2` (Fill) | `2` (Filled) |
| Cancelada | `4` (Canceled) | `4` (Canceled) |
| Modificada | `5` (Replaced) | `5` (Replaced) |
| Rejeitada | `8` (Rejected) | `8` (Rejected) |

---

## Ativos de referência

| Segmento | Ticker | Tipo | Preço ref. |
|----------|--------|------|------------|
| Equities | PETR4 | Ação ON | 38,50 BRL |
| Equities | VALE3 | Ação ON | 62,10 BRL |
| Equities | ITUB4 | Ação PN | 31,80 BRL |
| Derivatives | WINQ25 | Futuro Mini Índice | 135.000 pts |
| Derivatives | DOLQ25 | Futuro Mini Dólar | 5.890 BRL |
| FX | USDBRL | Câmbio pronto | 5,895 BRL |

---

## Validação

Um parser independente foi usado para conferir, em cada mensagem gerada:

1. O valor declarado em `9=` bate com o tamanho real do corpo.
2. O valor declarado em `10=` bate com `sum(bytes) mod 256`.

Resultado dos 5 fluxos:

| Fluxo | Mensagens | Falhas |
|-------|-----------|--------|
| 1 | 8 | 0 |
| 2 | 7 | 0 |
| 3 | 5 | 0 |
| 4 | 7 | 0 |
| 5 | 54 | 0 |

Para repetir a validação:

```bash
python3 - <<'PY'
import subprocess
SOH = "\x01"

def verify(raw):
    after_8 = raw.index(SOH) + 1
    tag9_eq = raw.index("9=", after_8) + 2
    soh_after_9 = raw.index(SOH, tag9_eq)
    declared_len = int(raw[tag9_eq:soh_after_9])
    tag10_start = raw.rindex(SOH + "10=") + 1
    body_segment = raw[soh_after_9 + 1:tag10_start]
    assert len(body_segment.encode("ascii")) == declared_len, "BodyLength mismatch"
    expected = sum(raw[:tag10_start].encode("ascii")) % 256
    assert int(raw[tag10_start+3:tag10_start+6]) == expected, "Checksum mismatch"

for flow in (1, 2, 3, 4, 5):
    out = subprocess.check_output(["python3", "fix_generator.py", "--flow", str(flow)]).decode("ascii")
    i = 0
    count = 0
    while i < len(out):
        end = out.index(SOH + "10=", i) + 1 + 6 + 1
        verify(out[i:end])
        count += 1
        i = end
    print(f"flow {flow}: {count} mensagens OK")
PY
```

---

## Estrutura do projeto

```
fix_generator/
├── fix_generator.py    # Gerador principal (CLI + builders + fluxos)
└── README.md           # Este arquivo
```

Pontos de extensão em [fix_generator.py](fix_generator.py):

- **Novos MsgTypes**: adicione um `*_body()` que retorne `list[tuple[int, str]]` e use via `session.send_client(...)` / `session.send_server(...)`.
- **Novos fluxos**: implemente `flow_N(session: Session)` e registre no dicionário `FLOWS`.
- **Novos ativos**: acrescente ao dicionário `ASSETS` no topo do arquivo.
- **Configuração de sessão**: ajuste `SENDER`, `TARGET`, `CAU_USER`, `CAU_PASS`, `ACCOUNT` no topo do arquivo.

---

## Referências

- [B3 EntryPoint Message Specification v2.40 (27/11/2025)](https://www.b3.com.br/data/files/A7/77/7B/FE/5789491029BEEC39AC094EA8/EntryPointMessageSpecs.pdf)
- [B3 EntryPoint Messaging Guidelines v2.9.29](https://www.b3.com.br/data/files/FF/84/5F/93/DB81D8103152D4C8AC094EA8/EntryPointMessagingGuidelines.pdf)
- [B3 EntryPoint Error Codes v1.0.31](https://www.b3.com.br/data/files/08/02/8E/C1/1963D8103152D4C8AC094EA8/EntryPointErrorCodes.pdf)
- [FIX 4.4 — fixprotocol.org](https://www.fixtrading.org/standards/fix-4-4/)
