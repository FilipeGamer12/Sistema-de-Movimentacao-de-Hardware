# Controle de Hardware -- Servidor Python (HTTP)

Este projeto implementa um **sistema completo de registro e controle de
movimentações de hardware**, incluindo entradas, saídas e empréstimos,
utilizando apenas **Python nativo** (`http.server`).\
Ele fornece uma interface web moderna e responsiva, grava dados em JSON
e suporta operações de empréstimo com notificação automática de atrasos.

------------------------------------------------------------------------

## 🚀 **Recursos Principais**

-   Interface web em HTML/CSS/JS embutida no próprio servidor.
-   Registro de:
    -   **Entradas**
    -   **Saídas**
    -   **Empréstimos**
-   Controle de empréstimos com:
    -   Notificação automática de **atrasos**
    -   Botão para **devolver**
    -   Botão para **estender devolução**
-   Pesquisa e ordenação no frontend.
-   Exportação completa para **CSV**.
-   Armazenamento simples em `dados.json`.
-   Sistema de "exclusão" não destrutiva (registros são apenas
    ocultados).
-   Coleta de metadados invisíveis:
    -   IP do cliente
    -   Data/hora do registro
-   Servidor multithread via `ThreadingHTTPServer`.

------------------------------------------------------------------------

## 🗂 **Estrutura do Projeto**

    .
    ├── sistema_.py        # Servidor HTTP com backend + frontend embutido
    └── dados.json        # Banco de dados simples (gerado automaticamente)

------------------------------------------------------------------------

## 📦 **Instalação**

Requisitos:

-   Python 3.8 ou superior
-   Nenhuma lib externa é necessária

Clone o repositório e execute:

``` bash
python3 sistema_.py
```

O servidor iniciará em:

    http://localhost:8000

------------------------------------------------------------------------

## 🖥 **Funcionalidades do Sistema**

### 📌 **Página principal (/)**

Contém o formulário para registrar movimentações.\
Campos variam conforme o tipo selecionado (entrada, saída ou
empréstimo).

### 📌 **Lista de registros (/lista)**

Inclui:

-   Tabela completa com filtros
-   Indicação de atrasados
-   Ordenação dinâmica por ID
-   Botões:
    -   **Devolver**
    -   **Estender**
    -   **Excluir (ocultar)**

### 📌 **Exportação CSV (/export_csv)**

Baixa um arquivo CSV contendo todos os registros (inclusive campos
ocultos de metadados).

### 📌 **Notificações de atraso (/atrasos)**

Endpoint usado via AJAX para atualizar alertas de empréstimos vencidos.

------------------------------------------------------------------------

## 🧩 **Formato do JSON (dados.json)**

Cada registro contém informações como:

``` json
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
  "oculto_meta": {
    "client_ip": "192.168.0.10",
    "registrado_em": "28/11/2025 14:31"
  }
}
```

------------------------------------------------------------------------

## 🔧 **Endpoints Disponíveis**

  Método   Rota            Descrição
  -------- --------------- ----------------------------------
  GET      `/`             Formulário principal
  GET      `/lista`        Tabela de registros
  GET      `/export_csv`   Geração de CSV
  GET      `/atrasos`      HTML de notificações de atraso
  POST     `/registrar`    Salvar novo registro
  POST     `/devolver`     Marcar empréstimo como devolvido
  POST     `/estender`     Alterar data de devolução
  POST     `/ocultar`      Ocultar registro

------------------------------------------------------------------------

## 🏗 **Arquitetura Interna**

O sistema não utiliza frameworks --- todo o backend é implementado com:

-   `BaseHTTPRequestHandler`
-   `ThreadingHTTPServer`
-   `json`
-   `csv`
-   `datetime`

Front-end utiliza:

-   Flatpickr para escolha de datas
-   HTML gerado dinamicamente no próprio Python
-   CSS customizado em modo dark

------------------------------------------------------------------------

## 🛡 **Validações Importantes**

-   Patrimônio com mínimo de 7 dígitos
-   Workflow nos formatos:
    -   `P-1234567`
    -   `P-12345-00`
-   Campos adicionais obrigatórios caso "outros" seja selecionado
-   Verificação de atraso baseada na data/hora do servidor

------------------------------------------------------------------------

## 🔄 **Executar como Serviço (Linux)**

Exemplo de unit (systemd):

``` ini
[Unit]
Description=Sistema de Controle de Hardware
After=network.target

[Service]
WorkingDirectory=/caminho/para/pasta
ExecStart=/usr/bin/python3 /caminho/para/sistema_.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

------------------------------------------------------------------------

## 📝 **Licença**

Este projeto pode ser usado, modificado e distribuído livremente ---
ajuste conforme necessário.
