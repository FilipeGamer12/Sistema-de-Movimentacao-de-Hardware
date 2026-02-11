# Controle de Hardware — Servidor Python (HTTP)

Este repositório contém um **sistema leve de registro e controle de movimentações de hardware** (entradas, saídas e empréstimos) implementado com **Python nativo** usando `http.server`. A interface web é gerada dinamicamente pelo servidor e os dados são guardados em `dados.json`.

---

## 🚀 Principais alterações / estado atual

* Adicionado o campo **`origem`** no formulário e no JSON (campo de texto livre, **máximo 10 caracteres**) — local: entre `workflow` e `data_inicio` no formulário.
* Autenticação baseada em arquivos: `users.json` para usuários e `sessions.json` para sessões. Senhas são armazenadas com PBKDF2-SHA256 (salts hex) e o servidor gera sessões via token.
* Fluxo de primeiro login: se um usuário existe mas não tem senha (`password_hash` ausente), o primeiro login grava a nova senha (mínimo 6 caracteres).
* Sessões: TTL de **4 horas** por padrão (cookie HttpOnly; opção "Manter conectado" persiste com `Max-Age`).
* Painel Admin (apenas `admin`): adicionar usuário, forçar redefinição de senha e excluir usuário (rotas: `/admin_add_user`, `/admin_reset_password`, `/admin_delete_user`).
* Novo comportamento do botão **"Retornar máquina"** (rota `/retornar`):

  * Para `emprestimo`: marca o registro como `devolvido = true` (comportamento clássico).
  * Para `entrada` ou `saida`: cria automaticamente o registro inverso (entrada → saída ou saída → entrada) preservando metadados relevantes (origem, workflow, patr., responsavel) e registrando `oculto_meta` com o usuário que executou a ação. Isto facilita marcar uma entrada como saída sem editar manualmente.
* Mantém também rota/ação `/devolver` (marca `devolvido = true`) para compatibilidade/fluxos legados.
* Controle de edição de registros: `admin` pode editar qualquer registro; criador do registro pode editar por até 24h se não houver observações.
* Observações: cada registro possui `observacoes` (lista de objetos com `registrado_em` e `text`) — adicionar via `/adicionar_observacao`. Adicionar observação recente remove a pendência de entrada (lógica no servidor).
* Exportação CSV: inclui agora o campo `origem` e colunas como `id, tipo, responsavel, emprestado_para, origem, patrimonio, workflow, motivo, hardware, marca, modelo, data_inicio, data_retorno, devolvido, estoque, status, client_ip, registrado_em`.
* Painel de Pendências: retorna HTML via `/atrasos` e é atualizado por AJAX a cada 20s no frontend. Calcula atrasos (empréstimos vencidos) e entradas sem atualização há >= 7 dias (regras descritas abaixo).
* Frontend: usa Flatpickr (CDN) para seletores de data/hora, modais para edição/observações/exportação e botões de ação com estilo moderno (cores: devolver = verde, estender = azul, editar = laranja, restaurar = verde escuro, etc.).
* Armazenamento simples em `dados.json` (formato JSON legível). O servidor opera em modo multithread (`ThreadingHTTPServer`) e, por padrão, escuta em `http://localhost:8000`.

---

## 🗂 Estrutura principal do projeto

```
.
├── sistema_.py        # Servidor HTTP (backend + frontend embutidos)
├── dados.json         # Banco de dados simples (gerado automaticamente)
├── users.json         # Usuários (admin criado por padrão)
└── sessions.json      # Sessões ativas (tokens)
```

---

## 📦 Instalação e execução

Requisitos:

* Python 3.8 ou superior
* Sem dependências externas (o frontend usa CDNs para flatpickr)

Executar:

```bash
python3 sistema_.py
```

Por padrão o servidor serve em `http://localhost:8000`.

> Para executar como serviço (systemd) veja o exemplo de unit (atualize caminhos para o seu sistema).

---

## 🔗 Endpoints (principais / atualizados)

| Método | Rota                    | Descrição                                                                                         |
| ------ | ----------------------- | ------------------------------------------------------------------------------------------------- |
| GET    | `/`                     | Formulário principal (Registrar Movimentação)                                                     |
| GET    | `/lista`                | Página com tabela de registros e exportação CSV                                                   |
| GET    | `/export_csv`           | Gera/baixa CSV aplicando filtros informados                                                       |
| GET    | `/atrasos`              | HTML do mini painel de pendências (usado por AJAX)                                                |
| GET    | `/login`                | Tela de login (pública)                                                                           |
| POST   | `/login`                | Processo de login / primeiro acesso salva senha                                                   |
| GET    | `/logout`               | Logout (remove sessão e cookie)                                                                   |
| POST   | `/registrar`            | Salvar novo registro (entrada/saída/emprestimo)                                                   |
| POST   | `/retornar`             | **Retornar máquina**: se `emprestimo` marca devolvido; se `entrada`/`saida` cria registro inverso |
| POST   | `/devolver`             | Marca `devolvido = true` (compatibilidade)                                                        |
| POST   | `/estender`             | Atualizar `data_retorno` (estender empréstimo)                                                    |
| POST   | `/ocultar`              | Ocultar registro (exclusão não-destrutiva)                                                        |
| POST   | `/restaurar`            | Restaurar registro oculto (admin somente)                                                         |
| POST   | `/alternar_estoque`     | Alternar flag `estoque` para entradas                                                             |
| POST   | `/adicionar_observacao` | Adicionar observação a um registro                                                                |
| POST   | `/editar_registro`      | Editar registro (restrições: admin ou autor em 24h sem observações)                               |
| POST   | `/admin_add_user`       | Adicionar usuário (admin)                                                                         |
| POST   | `/admin_reset_password` | Forçar redefinição (remove hash) (admin)                                                          |
| POST   | `/admin_delete_user`    | Excluir usuário (admin)                                                                           |

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
  "origem": "CPCTBA",
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
  "oculto_meta": { "client_ip": "192.168.0.10", "registrado_em": "28/11/2025 14:31", "registrado_por": "admin" }
}
```

Observações:

* O campo `observacoes` é *lista* de objetos com `registrado_em` e `text` (ou `texto`).
* Metadados do registro (IP, timestamp, usuário que registrou) ficam em `oculto_meta` — usados em exportações e regras de permissão.
* O CSV exportado inclui colunas descritas na seção acima; o campo `status` é calculado pelo servidor (ex.: "Devolvido", "Atrasado (DD/MM/YYYY)", "Em estoque", "Ativo").

---

## 🔍 Regras de negócio (resumido)

* **Pendência de entrada:** um registro do tipo `entrada` (com `motivo` diferente de "outros") é considerado pendente se:

  * Está a **7 dias ou mais** desde `data_inicio` **E**
  * **Não** existe uma saída com o mesmo `workflow` **E**
  * **A última observação** (se existir) está há 7 dias ou mais. Se existir observação recente, a pendência não aparece.

* **Empréstimos:** se `data_retorno` <= agora e `devolvido == false`, o empréstimo aparece como **Atrasado**.

* **Edição:** `admin` pode editar qualquer registro; o criador pode editar seu registro nas primeiras 24 horas (desde `oculto_meta.registrado_em`) **somente** se não houver observações.

---

## 🖥️ Frontend / UX — pontos importantes

* Flatpickr (CDN) é usado para seleção de datas/hora no formulário principal, modal de exportação e modais de edição/estender.
* Painel de pendências foi movido para um card separado e atualiza automaticamente (AJAX a cada 20s) via rota `/atrasos`.
* Modal de exportação suporta filtros avançados (tipo, responsável, workflow, origem, periodo, IDs manuais, etc.).
* Botões de ação: design e cores atualizados — destaque ao botão **Editar** (laranja), **Retornar/Devolver** (verde), **Restaurar** (verde escuro), **Estender** (azul) e **Observações** (amarelo). Essas cores e textos estão definidos no CSS/HTML gerado por `sistema_.py`.

---

## 💡 Dicas de operação

* Para editar a lista de responsáveis, edite a constante `RESPONSAVEIS` no topo de `sistema_.py`.
* Para adaptar porta/host, modifique `server_address` na parte final de `sistema_.py`.
* Para rodar como serviço, adapte o exemplo de unit systemd informando o caminho correto para `sistema_.py`.

---
