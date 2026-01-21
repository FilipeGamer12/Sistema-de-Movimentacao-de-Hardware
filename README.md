# Controle de Hardware — Servidor Python (HTTP)

Este repositório contém um **sistema leve de registro e controle de movimentações de hardware** (entradas, saídas e empréstimos) implementado com **Python nativo** usando `http.server`. A interface web é gerada dinamicamente pelo servidor e os dados são guardados em `dados.json`.

---

## 🚀 Recursos principais

- Interface web embutida (HTML/CSS/JS) servida por `sistema_.py`.
- Registro de movimentos: **Entrada**, **Saída** e **Empréstimo**.
- Controle de empréstimos com:
  - Notificação automática de **atrasos** (com endpoint dedicado).
  - Botão **"Retornar máquina"** (anteriormente "Marcar como devolvido") disponível para todos os registros não devolvidos.
  - Possibilidade de **estender** data prevista de devolução para registros do tipo `emprestimo`.
- **Painel de Pendências** separado da área de registro (card à parte). O painel mostra: atrasos (emprestimos vencidos) e entradas sem atualização há 7 dias ou mais.
  - Pendências são calculadas pela **data do registro (`data_inicio`) e/ou pela data da última observação** — o que for mais recente. Se a última observação for recente (menos de 7 dias) ou já existir uma saída com o mesmo workflow, a pendência não é exibida.
  - Quando não há pendências, o painel exibe uma mensagem clara: **"Sem pendências."**
- Modal de **Observações** por registro: permite ver histórico de observações e **adicionar observações** (rota `/adicionar_observacao`).
  - Ao adicionar uma observação recente a uma entrada, a pendência correspondente deixa de aparecer (lógica implementada no servidor).
- **Exportação CSV** com filtros avançados (modal de filtros): permite filtrar por tipo, responsável, workflow, período (`date_from` / `date_to`) e outros campos — agora com seletores de data (flatpickr) no modal para facilitar escolha de datas.
- Painel de pendências atualiza via AJAX a cada 20s (endpoint `/atrasos`).
- Armazenamento simples em `dados.json` (formato JSON legível).
- Operação multithreaded via `ThreadingHTTPServer`.

---

## 🗂 Estrutura principal do projeto

```
.
├── sistema_.py        # Servidor HTTP (backend + frontend embutidos)
└── dados.json        # Banco de dados simples (gerado automaticamente)
```

---

## 📦 Instalação e execução

Requisitos:

- Python 3.8 ou superior
- Sem dependências externas (o frontend usa CDNs para flatpickr)

Executar:

```bash
python3 sistema_.py
```

Por padrão o servidor serve em `http://localhost:8000`.

> Para executar como serviço (systemd) veja o exemplo de unit (atualize caminhos para o seu sistema).

---

## 🔗 Endpoints (principais)

| Método | Rota                  | Descrição |
|--------|-----------------------|-----------|
| GET    | `/`                   | Formulário principal (Registrar Movimentação) |
| GET    | `/lista`              | Página com tabela de registros e exportação CSV |
| GET    | `/export_csv`         | Gera/baixa CSV aplicando filtros informados |
| GET    | `/atrasos`            | HTML do mini painel de pendências (usado por AJAX) |
| POST   | `/registrar`          | Salvar novo registro (entrada/saída/emprestimo) |
| POST   | `/retornar`           | Marcar registro como retornado / "Retornar máquina" |
| POST   | `/estender`           | Atualizar `data_retorno` (estender empréstimo) |
| POST   | `/ocultar`            | Ocultar ("excluir" não destrutivo) um registro |
| POST   | `/alternar_estoque`   | Alternar flag de estoque para entradas |
| POST   | `/adicionar_observacao` | Adicionar observação a um registro |

(As rotas e nomes refletem a versão atual do `sistema_.py`.)

---

## 🧩 Formato do JSON (`dados.json`) — campos relevantes

Cada registro é um objeto com campos como:

```json
{
  "id": 1,
  "tipo": "emprestimo",
  "responsavel": "Fulano",
  "patrimonio": "1234567",
  "workflow": "P-1234567",
  "motivo": "manutenção",
  "hardware": "Notebook",
  "marca": "Dell",
  "modelo": "Latitude",
  "data_inicio": "28/11/2025 14:30",
  "data_retorno": "30/11/2025 14:30",
  "emprestado_para": "Usuário X",
  "devolvido": false,
  "oculto": false,
  "estoque": false,
  "observacoes": [
     { "registrado_em": "28/11/2025 15:00", "text": "Observação X" }
  ],
  "oculto_meta": { "client_ip": "192.168.0.10", "registrado_em": "28/11/2025 14:31" }
}
```

Observações:
- O campo `observacoes` é _lista_ de objetos com `registrado_em` e `text` (ou `texto`).
- Metadados do registro (IP, timestamp) ficam em `oculto_meta` (usado na exportação CSV).
- O CSV exportado inclui colunas como `id, tipo, responsavel, patrimonio, workflow, motivo, hardware, marca, modelo, data_inicio, data_retorno, devolvido, estoque, status, client_ip, registrado_em` — o campo `status` é calculado pelo servidor (ex.: "Devolvido", "Atrasado (DD/MM/YYYY)", "Em estoque", "Ativo").

---

## 🖥️ Frontend / UX — pontos importantes

- Flatpickr (CDN) é usado para seleção de datas em todo o app (formulário principal, modal de exportação, modal de estender data).
- O painel de pendências foi movido para um card separado ao lado do formulário na vista principal (desktop) e empilha acima em telas pequenas.
- Modal de exportação foi reorganizado em uma grade (checkboxes à esquerda / controles à direita) e possui seletores de data com flatpickr para `date_from` / `date_to`.
- Ao abrir o modal de exportação, o campo `date_to` é pré-definido com a hora atual do cliente.
- O botão para retornar um registro foi renomeado para **"Retornar máquina"** e é exibido para todos os registros que não estão marcados como devolvidos.

---

## 🔍 Regras de negócio relevantes (resumido)

- Pendência de entrada: um registro do tipo `entrada` (com `motivo` diferente de "outros") é considerado pendente se:
  - Está a **7 dias ou mais** desde `data_inicio` **e**
  - **Não** existe uma saída com o mesmo `workflow` **e**
  - A última observação (se existir) está há 7 dias ou mais. Caso haja uma observação mais recente, a pendência não aparece.
- Empréstimos: consideram `data_retorno`; se `data_retorno` <= agora e `devolvido` == false, aparece como **Atrasado**.

---

## 💡 Dicas de operação

- Para editar a lista de responsáveis, edite a constante `RESPONSAVEIS` no topo de `sistema_.py`.
- Para customizar porta/host, edite a rotina que inicia o servidor (arquivo `sistema_.py`).
- Para rodar como serviço, adapte o exemplo de unit systemd informando o caminho correto para `sistema_.py`.

---

## 📝 Licença

Este projeto pode ser usado, modificado e distribuído livremente.

