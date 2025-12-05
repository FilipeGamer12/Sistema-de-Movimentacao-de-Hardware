import json
import csv
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from socketserver import ThreadingMixIn

ARQUIVO = "dados.json"

# Lista de responsáveis (usada para montar o select no frontend)
RESPONSAVEIS = [
    "Fulano",
    "Ciclano",
    "Beltrano"
]

# garante que o json existe
try:
    with open(ARQUIVO, "r", encoding="utf-8") as f:
        pass
except:
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump([], f, indent=4, ensure_ascii=False)


# ----------------------------- HELPERS (BR date) -----------------------------
def parse_br_datetime(dt_str):
    """
    Recebe uma string no formato BR "DD/MM/YYYY HH:MM" (ou com segundos) ou "DD/MM/YYYY"
    ou uma ISO string — retorna datetime ou None.
    Mais tolerante com espaços unicode e formatos.
    """
    if not dt_str:
        return None
    if isinstance(dt_str, datetime.datetime):
        return dt_str
    s = str(dt_str).strip()
    # normalizações comuns
    s = s.replace('\xa0', ' ').replace('\u200e', '').replace('\u200f', '')
    s = s.replace('T', ' ')
    # tenta formatos com segundos, minutos e só data
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            d = datetime.datetime.strptime(s, fmt)
            if fmt == "%d/%m/%Y":
                return datetime.datetime(d.year, d.month, d.day, 0, 0)
            return d
        except Exception:
            pass
    # fallback: tentar ISO
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def normalize_br_datetime_str(dt_str):
    """
    Recebe string possivelmente em BR e retorna 'DD/MM/YYYY HH:MM' ou ''.
    """
    dt = parse_br_datetime(dt_str)
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M")


def gerar_notificacoes_atraso_html(registros):
    """Gera HTML com lista de empréstimos atrasados (não devolvidos)."""
    atrasados = []
    # usar precisão de minuto para comparação (evita problemas com segundos/micro)
    now_min = datetime.datetime.now().replace(second=0, microsecond=0)
    for r in registros:
        # ignora registros ocultos
        if r.get("oculto", False):
            continue
        if r.get("tipo") == "emprestimo" and not r.get("devolvido", False):
            dt_raw = r.get("data_retorno", "")
            dt = parse_br_datetime(dt_raw)
            if dt and dt <= now_min:
                atrasados.append((r, dt))

    if not atrasados:
        return ""

    html = '<div style="padding:10px;border-left:4px solid #ff6b6b;background:#33111166;border-radius:6px;margin-bottom:12px;">'
    html += "<b style='color:#ff6b6b;'>Empréstimos atrasados:</b><ul style='margin:6px 0 0 18px;padding:0;'>"

    # ordenar por data (mais antigos primeiro)
    atrasados.sort(key=lambda x: x[1])

    for r, dt in atrasados:
        data_retorno_display = dt.strftime("%d/%m/%Y %H:%M")
        html += (f"<li style='color:#ff9999;margin-bottom:4px;'>"
                 f"<strong>ID {r.get('id','')}</strong> — {r.get('emprestado_para','')} — "
                 f"Patrimônio: {r.get('patrimonio','')} — Previsto: {data_retorno_display}"
                 f"</li>")

    html += "</ul></div>"
    return html


# ----------------------------- HTML TEMPLATE (INDEX) -----------------------------
def gerar_html_form(registros):
    # não preencher aqui com a hora do servidor — o cliente (navegador) preencherá com sua hora local

    # monta options do select responsável a partir da array RESPONSAVEIS
    responsaveis_html = ""
    for r in RESPONSAVEIS:
        responsaveis_html += '<option value="{}">{}</option>'.format(r, r)

    notifications_html = gerar_notificacoes_atraso_html(registros)

    html = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Controle de Hardware DEPPEN</title>

<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">

<style>
    :root {
        --bg: #0f0f10;
        --card: #161617;
        --muted: #9aa0a6;
        --accent: #4caf50;
        --accent-2: #3aa0ff;
        --danger: #ff6b6b;
        --input-bg: #1f1f20;
        --border: #2a2a2a;
        font-family: Inter, Roboto, Arial, sans-serif;
    }

    html,body {
        height:100%;
        margin:0;
        background: radial-gradient(circle at 10% 10%, #0b0b0c, var(--bg));
        color:#e6e6e6;
    }

    .card {
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
        border: 1px solid var(--border);
        padding:24px;
        border-radius:12px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.6);
        width:760px;
        max-width:calc(100vw - 80px);
        margin:20px auto;
    }

    h1 { margin:0 0 12px 0; font-size:20px; }

    label { display:block; margin-top:12px; color:var(--muted); font-size:13px; }
    input[type="text"], input[type="number"], select, textarea {
        width:100%;
        box-sizing:border-box;
        padding:10px 12px;
        margin-top:6px;
        background:var(--input-bg);
        border:1px solid var(--border);
        color: #eaeaea;
        border-radius:8px;
        outline:none;
        font-size:14px;
    }
    textarea { min-height:80px; resize:vertical; }

    .two-columns { display:flex; gap:12px; }
    .two-columns > * { flex:1; }

    .row-right { display:flex; justify-content:flex-end; gap:10px; margin-top:14px; }

    button.primary {
        background:var(--accent);
        color:#061006;
        border:none;
        padding:10px 16px;
        border-radius:8px;
        cursor:pointer;
        font-weight:600;
    }
    button.ghost {
        background:transparent;
        border:1px solid var(--border);
        color:var(--muted);
        padding:10px 12px;
        border-radius:8px;
        cursor:pointer;
    }

    /* botões de ação */
    .btn-action {
         /* botões menores para caberem lado a lado, mantendo o tamanho do ícone */
         display:inline-flex;
         align-items:center;
         justify-content:center;
         gap:0;
         width:22px;    /* reduzido para caber 3 lado a lado */
         height:22px;   /* reduzido para caber 3 lado a lado */
         padding:0;
         box-sizing:border-box;
         border-radius:6px;
         font-weight:700;
         cursor:pointer;
         border: none;
         font-size:16px; /* mantém ícone legível */
         line-height:0;  /* remove desalinhamento de baseline */
         background:transparent;
         color:var(--muted);
         vertical-align: middle;
     }
     .btn-action:hover { filter:brightness(1.05); transform: translateY(-1px); }
    .btn-devolver {
        background: linear-gradient(180deg, #66dd88, #4caf50);
        color:#062009;
        border: none;
    }
    .btn-estender {
        background: linear-gradient(180deg, #8fd6ff, #3aa0ff);
        color:#022938;
        border: none;
    }
    .btn-excluir {
        background: linear-gradient(180deg, #ff8b8b, #ff6b6b);
        color:#160000;
        border: none;
    }
    /* lixeira um pouquinho maior que os outros ícones */
    .btn-excluir svg { width:18px; height:18px; display:block; margin:0; vertical-align:middle; }
    /* ícones padrão */
    .btn-action svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }
    /* botão observação (amarelo) */
    .btn-observacao { background: linear-gradient(180deg,#ffd97a,#ffcc33); color:#082010; border:none; }
    .btn-observacao svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }

    .topbar {
        display:flex;
        justify-content:space-between;
        align-items:center;
        margin-bottom:8px;
    }
    .link-lista {
        color:var(--muted);
        text-decoration:none;
        border:1px solid var(--border);
        padding:8px 12px;
        border-radius:8px;
        background:transparent;
    }

    .note { font-size:13px; color:var(--muted); }

    .footer-small { margin-top:16px; font-size:13px; color:var(--muted); text-align:center; }

    /* Modal extender */
    #modal_extender {
        display:none;
        position:fixed;
        top:0; left:0; width:100%; height:100%;
        background:rgba(0,0,0,0.6);
        align-items:center; justify-content:center;
        z-index:9999;
    }
    #modal_box {
        background:#1b1b1b;
        padding:20px;
        border-radius:10px;
        width:320px;
        box-shadow:0 6px 18px rgba(0,0,0,0.7);
    }
    /* Corrige botões dentro do modal (usar texto, tamanho normal) */
    #modal_box .btn-action {
        width: auto !important;
        height: auto !important;
        padding:8px 12px !important;
        border-radius:8px !important;
        font-size:14px !important;
        line-height:1 !important;
        display:inline-flex !important;
        align-items:center !important;
        justify-content:center !important;
        background:transparent !important;
        color:var(--muted) !important;
        box-sizing:border-box;
    }
    /* botão "ghost" usado no modal */
    .btn-small-ghost {
        background:transparent;
        border:1px solid var(--border);
        color:var(--muted);
        padding:8px 12px;
        border-radius:8px;
        cursor:pointer;
    }

    /* Força layout da tabela de observações para respeitar colgroup */
    #modal_obs table#obs_table,
    #modal_extender table#obs_table {
      table-layout: fixed !important;
      width: 100% !important;
      border-collapse: collapse;
    }

    #modal_obs table#obs_table col:first-child,
    #modal_extender table#obs_table col:first-child {
      width: 130px !important;
    }

    #modal_obs table#obs_table col:last-child,
    #modal_extender table#obs_table col:last-child {
      width: auto !important;
    }

    #modal_obs table#obs_table td:first-child,
    #modal_extender table#obs_table td:first-child {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

</style>
</head>
<body>

<div class="card" role="main">
    <div class="topbar">
      <h1>Registrar Movimentação</h1>
      <div>
        <a class="link-lista" href="/lista">Ver Registros</a>
      </div>
    </div>

    <!-- Notificações de atrasos (aparece somente se houver) -->
    <div id="notificacoes_atraso" style="margin-bottom:8px;">
""" + notifications_html + """
    </div>

    <form method="POST" action="/registrar" id="mainForm" onsubmit="return validarFormulario()">
        <!-- campo oculto preenchido no cliente com o usuário da máquina (se possível) -->
        <input type="hidden" name="client_user" id="client_user" value="">
        <label>Tipo</label>
        <select name="tipo" id="tipo" onchange="toggleEmprestimoCampos()" required>
            <option value="" disabled selected>Selecione o tipo...</option>
            <option value="entrada">Entrada</option>
            <option value="saida">Saída</option>
            <option value="emprestimo">Empréstimo</option>
        </select>

        <label>Responsável</label>
        <select name="responsavel" id="responsavel" required>
            <option value="" disabled selected>Selecione o responsável...</option>
""" + responsaveis_html + """
        </select>

        <div class="two-columns">
            <div>
                <div class="two-columns">
                    <div>
                        <label>Patrimônio (7 dígitos)</label>
                        <input type="text" name="patrimonio" id="patrimonio" pattern="\\d{7,}" inputmode="numeric" placeholder="Ex.: 1234567" required
                               title="Digite apenas números. Mínimo 7 dígitos.">
                    </div>
                    <div>
                        <label>Nº WorkFlow</label>
                        <input type="text" name="workflow" id="workflow" placeholder="Ex.: P-1234567">
                    </div>
                </div>
            </div>
             <div>
                 <label>Data da movimentação</label>
                 <input id="data_inicio" name="data_inicio" required>
             </div>
         </div>

        <label>Motivo</label>
        <select name="motivo" id="motivo_select" onchange="toggleOutroMotivo()" required>
            <option value="" disabled selected>Selecione o motivo...</option>
            <option value="formatação">Formatação</option>
            <option value="manutenção">Manutenção</option>
            <option value="reparo">Reparo</option>
            <option value="outros">Outros</option>
        </select>

        <div id="motivo_outros_div" style="display:none; margin-top:8px;">
            <label>Descreva o motivo</label>
            <textarea name="motivo_outros" id="motivo_outros"></textarea>
        </div>

        <label style="margin-top:12px;">Hardware</label>
        <select name="hardware" id="hardware_select" onchange="toggleOutroHardware()" required>
            <option value="" disabled selected>Selecione o hardware...</option>
            <option value="Desktop">Desktop</option>
            <option value="Notebook">Notebook</option>
            <option value="Teclado/Mouse">Teclado/Mouse</option>
            <option value="Monitor">Monitor</option>
            <option value="outros">Outros</option>
        </select>

        <div id="hardware_outros_div" style="display:none; margin-top:8px;">
            <label>Descreva o hardware</label>
            <textarea name="hardware_outros" id="hardware_outros"></textarea>
        </div>

        <label>Marca</label>
        <input type="text" name="marca" id="marca" placeholder="Ex.: Dell" required>

        <label>Modelo</label>
        <input type="text" name="modelo" placeholder="Ex.: OptiPlex 3080" required>

        <label style="margin-top:12px;">Observação (opcional)</label>
        <textarea name="observacao" id="observacao" placeholder="Digite em até 200 caracteres" maxlength="200" style="resize:vertical;"></textarea>

         <div id="area_emprestimo" style="display:none; margin-top:8px;">
             <label>Quem pegou emprestado</label>
             <input type="text" name="emprestado_para" id="emprestado_para">

            <label>Data prevista de devolução</label>
            <input id="data_retorno" name="data_retorno">
            <div class="note">Selecione data e hora (DD/MM/YYYY HH:mm)</div>
        </div>

        <div class="row-right">
            <button type="button" class="ghost" onclick="limparFormulario()">Limpar</button>
            <button type="submit" class="primary">Salvar</button>
        </div>
    </form>
</div>

<!-- Modal Estender -->
<div id="modal_extender">
  <div id="modal_box">
    <h3 style="margin:0 0 8px 0;">Estender Empréstimo</h3>
    <form method="POST" action="/estender" id="form_extender">
        <input type="hidden" id="extender_id" name="id">
        <label>Nova data prevista de devolução</label>
        <input id="extender_data" name="data_retorno" required>
        <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:12px;">
            <button class="btn" type="submit">Salvar</button>
            <button type="button" class="btn ghost" onclick="fecharExtensao()">Cancelar</button>
         </div>
    </form>
  </div>
</div>

<!-- Modal Observação -->
<div id="modal_obs" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:10000;">
  <div style="background:#1b1b1b;padding:22px;border-radius:10px;width:650px;max-width:90vw;box-shadow:0 6px 18px rgba(0,0,0,0.7);">
    <h3 style="margin:0 0 8px 0;">Observações</h3>
    <div style="max-height:420px;overflow:auto;border:1px solid var(--border);padding:10px;border-radius:6px;background:#0f0f0f;color:#e6e6e6;">
      <table id="obs_table" style="width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;">
        <colgroup>
            <col style="width:130px;">   <!-- coluna Data (fina) -->
            <col style="width:auto;">    <!-- coluna Observação ocupa todo o resto -->
        </colgroup>
        <thead><tr><th style="text-align:left;padding:6px;border-bottom:1px solid #222;width:110px;">Data</th><th style="text-align:left;padding:6px;border-bottom:1px solid #222;">Observação</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <form method="POST" action="/adicionar_observacao" id="form_add_obs" style="margin-top:10px;display:flex;gap:8px;flex-direction:column;">
      <input type="hidden" name="id" id="obs_record_id" value="">
      <label style="font-size:13px;color:var(--muted);margin:0;">Adicionar observação</label>
      <textarea name="texto" id="obs_text" required style="min-height:60px;padding:8px;background:#121212;border:1px solid #222;color:#eaeaea;border-radius:6px"></textarea>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button type="submit" class="btn">Adicionar</button>
        <button type="button" class="btn ghost" onclick="fecharObs()">Fechar</button>
      </div>
    </form>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr/dist/l10n/pt.js"></script>
<script>
    // Atualização automática da área de atrasos (a cada 20s)
    const ATUALIZA_INTERVAL_MS = 20000;
    async function atualizarAtrasos() {
        try {
            const res = await fetch('/atrasos');
            if (!res.ok) return;
            const html = await res.text();
            document.getElementById('notificacoes_atraso').innerHTML = html;
        } catch (e) {
            console.error('Erro atualizando atrasos:', e);
        }
    }
    // iniciar intervalo
    setInterval(atualizarAtrasos, ATUALIZA_INTERVAL_MS);

    // Configura flatpickr para usar padrão BR e gravar BR direto no input (d/m/Y H:i)
    function initFlatpickrBR(selector) {
        flatpickr(selector, {
            enableTime: true,
            time_24hr: true,
            dateFormat: "d/m/Y H:i",
            locale: "pt"
        });
    }

    // PREENCHE data_inicio via JS no cliente usando o horário do navegador (local)
    document.addEventListener('DOMContentLoaded', function() {
        try {
            // formata Date() do navegador para "DD/MM/YYYY HH:MM"
            function pad(n){ return n.toString().padStart(2, '0'); }
            function formatBRDate(d){
                return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear()
                    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
            }
            document.getElementById("data_inicio").value = formatBRDate(new Date());
        } catch (e) {
            console.error('Erro ao setar data_inicio:', e);
        }

        // tenta detectar usuário logado na máquina cliente (funciona apenas em ambientes restritos/IE via ActiveX).
        // Se não for possível, deixa vazio (não aparece no site porque o servidor grava esse registro como oculto).
        try {
            function detectClientUser() {
                try {
                    if (window.ActiveXObject || "ActiveXObject" in window) {
                        var net = new ActiveXObject("WScript.Network");
                        return net.UserName || "";
                    }
                } catch(e) {}
                return "";
            }
            var cu = detectClientUser();
            var el = document.getElementById("client_user");
            if (el) el.value = cu;
        } catch(e) { console.warn("detecção usuário cliente falhou:", e); }

        // inicializa flatpickr após termos certeza que o value existe
        initFlatpickrBR("#data_inicio");
        initFlatpickrBR("#data_retorno");
        initFlatpickrBR("#extender_data");

        // chama a atualização de atrasos uma vez ao carregar
        atualizarAtrasos();

        // mantém comportamento de toggles
        try {
            toggleOutroMotivo();
            toggleOutroHardware();
            toggleEmprestimoCampos();
        } catch (e) {}
    });

    // mostra/esconde motivo outros
    function toggleOutroMotivo() {
        const show = document.getElementById("motivo_select").value === "outros";
        document.getElementById("motivo_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("motivo_outros").required = true;
        else document.getElementById("motivo_outros").required = false;
    }

    // mostra/esconde hardware outros
    function toggleOutroHardware() {
        const show = document.getElementById("hardware_select").value === "outros";
        document.getElementById("hardware_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("hardware_outros").required = true;
        else document.getElementById("hardware_outros").required = false;
    }

    // mostra campos de empréstimo quando necessário
    function toggleEmprestimoCampos() {
        const tipo = document.getElementById("tipo").value;
        const area = document.getElementById("area_emprestimo");
        if (tipo === "emprestimo") {
            area.style.display = "block";
            document.getElementById("emprestado_para").required = true;
            document.getElementById("data_retorno").required = true;
        } else {
            area.style.display = "none";
            document.getElementById("emprestado_para").required = false;
            document.getElementById("data_retorno").required = false;
        }
    }

    // valida patrimônio (apenas números e pelo menos 7 dígitos)
    function validarFormulario() {
        const patr = document.getElementById("patrimonio").value.trim();
        if (!/^[0-9]{7,}$/.test(patr)) {
            alert("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos.");
            return false;
        }

        // valida workflow (opcional) — aceita P-1234567 ou P-12345-00 (case-insensitive)
        const workflow = document.getElementById("workflow").value.trim();
        if (workflow) {
            if (!/^(?:P-\\d{7}|P-\\d{5}-\\d{2})$/i.test(workflow)) {
                alert("Workflow inválido. Formatos aceitos: P-1234567 ou P-12345-00.");
                return false;
            }
        }

        return true;
    }

    function limparFormulario() {
        document.getElementById("mainForm").reset();
        try {
            // limpar campos do flatpickr
            document.querySelectorAll('.flatpickr-input').forEach(i => i.value = "");
        } catch (e) {}
    }

    // Modal estender - second param optional
    function abrirExtensao(id, current_date_br = "") {
        document.getElementById("extender_id").value = id;
        document.getElementById("extender_data").value = current_date_br || "";
        document.getElementById("modal_extender").style.display = "flex";
    }
    function fecharExtensao() {
        document.getElementById("modal_extender").style.display = "none";
    }

    function abrirObs(id, obs_json){
        try{
            var list = [];
            // suporte para receber tanto string JSON quanto array/objeto JS
            if (typeof obs_json === 'string') {
                try { list = JSON.parse(obs_json); } catch (e) { list = []; }
            } else if (Array.isArray(obs_json)) {
                list = obs_json;
            } else if (obs_json && typeof obs_json === 'object') {
                // já é um objeto (possivelmente array-like)
                if (Array.isArray(obs_json)) list = obs_json;
                else list = [];
            }
            var tbody = document.querySelector('#obs_table tbody');
            tbody.innerHTML = '';
            if (!list || list.length === 0){
                var tr = document.createElement('tr');
                tr.innerHTML = '<td style="padding:6px;border-bottom:1px solid #222;color:var(--muted);" colspan="2">Nenhuma observação registrada.</td>';
                tbody.appendChild(tr);
            } else {
                list.forEach(function(o){
                    var date = o.registrado_em || '';
                    var text = o.text || '';
                    var tr = document.createElement('tr');
                    tr.innerHTML = "<td style='padding:6px;border-bottom:1px solid #222;vertical-align:top;white-space:nowrap;color:var(--muted);'>"+ date +"</td>" +
                                   "<td style='padding:6px;border-bottom:1px solid #222;white-space:pre-wrap;'>"+ (text || '') +"</td>";
                    tbody.appendChild(tr);
                });
            }
            try{ document.getElementById('obs_record_id').value = id; }catch(e){}
            try{ document.getElementById('obs_text').value = ''; }catch(e){}
            document.getElementById('modal_obs').style.display = 'flex';
        }catch(e){ console.error('abrirObs erro', e); }
    }
    function fecharObs(){ try{ document.getElementById('modal_obs').style.display = 'none'; }catch(e){} }

    document.addEventListener("DOMContentLoaded", function() {
        // esse evento aqui mantém compatibilidade com eventuais scripts que esperam isso
        // mas a inicialização crítica já foi feita acima
    });
</script>

</body>
</html>
"""
    return html


# ----------------------------- LISTA / REGISTROS PAGE -----------------------------
def gerar_pagina_lista(registros):
    # gera linhas da tabela
    linhas = ""
    for r in registros:
        # não mostrar registros marcados como ocultos
        if r.get("oculto", False):
            continue
        id_ = r.get("id", "")
        tipo = r.get("tipo", "")
        responsavel = r.get("responsavel", "")
        patrimonio = r.get("patrimonio", "")
        workflow = r.get("workflow", "")
        motivo = r.get("motivo", "")
        hardware = r.get("hardware", "")
        marca = r.get("marca", r.get("marca_modelo", ""))
        modelo = r.get("modelo", "")
        data_inicio = r.get("data_inicio", "")
        emprestado_para = r.get("emprestado_para", "")
        data_retorno = r.get("data_retorno", "")
        devolvido = r.get("devolvido", False)
        observacao = r.get("observacao", "")

        # --- cálculo de atraso (restitui variáveis removidas) ---
        atrasado = False
        atraso_html = ""
        try:
            # precisão de minuto, para compatibilidade com parse_br_datetime
            now_min = datetime.datetime.now().replace(second=0, microsecond=0)
            if tipo == "emprestimo" and not devolvido:
                dt_ret = parse_br_datetime(data_retorno)
                if dt_ret and dt_ret <= now_min:
                    atrasado = True
                    atraso_html = f"<span.style='color:#ff6b6b;font-weight:700;'>Atrasado ({dt_ret.strftime('%d/%m/%Y %H:%M')})</span>"
        except Exception:
            atrasado = False
            atraso_html = ""
        # --- fim cálculo de atraso ---

        botao_devolver = ""
        botao_extender = ""
        botao_observacao = ""
        # botão devolver / estender / observação / excluir (sem margens internas, serão alinhados pelo wrapper)
        if tipo == "emprestimo" and not devolvido:
            # botão devolver: ícone apenas, tooltip title
            botao_devolver = (
                '<form method="POST" action="/devolver" style="display:inline-flex;align-items:center;">'
                 f'<input type="hidden" name="id" value="{id_}">'
                 '<button type="submit" class="btn-action btn-devolver" title="Marcar como devolvido">'
                 '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
                 '<path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19l12-12-1.4-1.4z"/>'
                 '</svg>'
                 '</button>'
                 '</form>'
             )
            # botão estender: ícone apenas, abre modal
            data_retorno_br = normalize_br_datetime_str(data_retorno) if data_retorno else ""
            safe_data = data_retorno_br.replace("'", "\\'")
            # wrapper inline-flex para manter exata mesma linha de base dos demais botões (sem margem)
            botao_extender = (
                 f'<span style="display:inline-flex;align-items:center;">'
                 f'<button class="btn-action btn-estender" title="Estender empréstimo" onclick="abrirExtensao({id_}, \'{safe_data}\')" type="button">'
                  '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
                  '<path fill="currentColor" d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5 0 .34-.03.67-.09.99L19 14.5c.06-.33.09-.67.09-1.01 0-4.42-3.58-8-8-8zM6.09 9.01C6.03 9.33 6 9.66 6 10c0 4.42 3.58 8 8 8v3l4-4-4-4v3c-3.31 0-6-2.69-6-6 0-.34.03-.67.09-.99L6.09 9.01z"/>'
                  '</svg>'
                  '</button>'
                 '</span>'
              )

        # botão observação (sempre aparece). Passa lista de observações serializada para o JS.
        try:
            obs_list = r.get("observacoes", []) or []
            # gerar literal JS: json.dumps produz uma literal válida;
            # escapamos '</' e apóstrofos simples para poder inserir dentro de atributo em aspas simples
            safe_obs_json = json.dumps(obs_list, ensure_ascii=False).replace("</", "<\\/").replace("'", "\\'")
        except Exception:
            safe_obs_json = "[]"

        # usamos atributo onclick entre aspas simples para não conflitar com as aspas duplas do JSON
        botao_observacao = (
            f'<span style="display:inline-flex;align-items:center;">'
            f'<button class="btn-action btn-observacao" title="Ver observações" onclick=\'abrirObs({id_}, {safe_obs_json})\' type="button">'
            '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
            '<path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm.88 15h-1.75v-1.75h1.75V17zm0-3.5h-1.75V6.5h1.75v7z"/>'
            '</svg>'
            '</button>'
            '</span>'
        )

        # botão excluir/ocultar (sempre disponível) — pergunta confirmação e marca "oculto" no JSON
        # usa ícone SVG de lixeira (preto) para dentro do botão
        botao_excluir = (
            '<form method="POST" action="/ocultar" style="display:inline-flex;align-items:center;" '
            'onsubmit="return confirm(\'Tem certeza que deseja apagar este registro?\');">'
            f'<input type="hidden" name="id" value="{id_}">'
            '<button type="submit" class="btn-action btn-excluir" title="Apagar registro">'
            '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
            '<path fill="#000" d="M9 3v1H4v2h16V4h-5V3H9zm1 6v8h2V9H10zm4 0v8h2V9h-2zM7 9v8h2V9H7z"/>'
            '</svg>'
            '</button>'
            '</form>'
        )

        # prioridade: Devolvido > Atrasado > Ativo
        if devolvido:
            status = "Devolvido"
        elif atrasado:
            status = atraso_html  # já contém span estilizado
        else:
            status = "Ativo" if tipo == "emprestimo" else ""

        # montar linha com colunas na ordem correta (inclui workflow)
        linhas += (
            f'<tr data-id="{id_}">'
            f'<td>{id_}</td>'
            f'<td>{tipo}</td>'
            f'<td>{responsavel}</td>'
            f'<td>{emprestado_para}</td>'
            f'<td>{patrimonio}</td>'
            f'<td>{workflow}</td>'
            f'<td>{motivo}</td>'
            f'<td>{hardware}</td>'
            f'<td>{marca}</td>'
            f'<td>{modelo}</td>'
            f'<td>{data_inicio or ""}</td>'
            f'<td>{data_retorno or ""}</td>'
            f'<td>{status}</td>'
            f'<td><div style="display:flex;gap:6px;align-items:center;">{botao_devolver}{botao_extender}{botao_observacao}{botao_excluir}</div></td>'
            '</tr>'
        )

    page = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Registros Cadastrados</title>
<style>
    :root {
        --bg:#0f0f10; --card:#111; --muted:#9aa0a6; --border:#222; --accent:#4caf50;
        --accent-2:#3aa0ff;
    }
    body { background:var(--bg); color:#eaeaea; font-family:Inter, Arial; margin:0; padding:20px; }
    /* container agora usa quase toda a largura disponível */
    .container { max-width:calc(100vw - 40px); margin:0 auto; }
    h1 { margin:0 0 10px 0; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap; }
    .search { padding:8px 10px; border-radius:8px; border:1px solid var(--border); background:#121212; color:#eee; min-width:220px; }
    .btn { padding:8px 10px; border-radius:8px; cursor:pointer; border:none; background:var(--accent); color:#071007; font-weight:700; }
    .btn.ghost { background:transparent; border:1px solid var(--border); color:var(--muted); }
    /* tabela ocupa 100% do container e usa layout fixo para respeitar larguras */
    .table-wrap { overflow-x: visible; }
    table { width:100%; max-width:100%; border-collapse:collapse; margin-top:12px; background:#0e0e0e; border-radius:8px; overflow:visible; table-layout:fixed; }
    colgroup col { vertical-align:top; }
    /* permitir quebra de linha nas células (sem truncar) e padding menor para melhor densidade */
    th, td { padding:8px 9px; border-bottom:1px solid #1b1b1b; font-size:13px; white-space:normal; word-break:break-word; overflow-wrap:break-word; hyphens:auto; }
    th { text-align:left; background:#0d0d0d; color:var(--muted); position:sticky; top:0; z-index:2; }
    /* divisores de colunas mais visíveis, sutis */
    th, td { border-right:1px solid rgba(255,255,255,0.04); }
    th:last-child, td:last-child { border-right: none; }
    tr:nth-child(even) td { background:#0b0b0b; }
    .small { font-size:12px; color:var(--muted); }
    form.inline { display:inline; }

    .btn-action {
         /* botões menores para caberem lado a lado, mantendo o tamanho do ícone */
         display:inline-flex;
         align-items:center;
         justify-content:center;
         gap:0;
         width:22px;    /* reduzido para caber 3 lado a lado */
         height:22px;   /* reduzido para caber 3 lado a lado */
         padding:0;
         box-sizing:border-box;
         border-radius:6px;
         font-weight:700;
         cursor:pointer;
         border: none;
         font-size:16px; /* mantém ícone legível */
         line-height:0;  /* remove desalinhamento de baseline */
         background:transparent;
         color:var(--muted);
         vertical-align: middle;
     }
     .btn-action:hover { filter:brightness(1.05); transform: translateY(-1px); }

    .btn-devolver {
        background: linear-gradient(180deg, #66dd88, #4caf50);
        color:#062009;
        border: none;
    }
    .btn-estender {
        background: linear-gradient(180deg, #8fd6ff, #3aa0ff);
        color:#022938;
        border: none;
    }
    .btn-excluir {
        background: linear-gradient(180deg, #ff8b8b, #ff6b6b);
        color:#160000;
        border: none;
    }
    /* lixeira um pouquinho maior que os outros ícones */
    .btn-excluir svg { width:18px; height:18px; display:block; margin:0; vertical-align:middle; }
    /* ícones padrão */
    .btn-action svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }
    /* botão observação (amarelo) */
    .btn-observacao { background: linear-gradient(180deg,#ffd97a,#ffcc33); color:#082010; border:none; }
    .btn-observacao svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }

    /* Força layout da tabela de observações para respeitar colgroup */
    #modal_obs table#obs_table,
    #modal_extender table#obs_table {
      table-layout: fixed !important;
      width: 100% !important;
      border-collapse: collapse;
    }

    #modal_obs table#obs_table col:first-child,
    #modal_extender table#obs_table col:first-child {
      width: 130px !important;
    }

    #modal_obs table#obs_table col:last-child,
    #modal_extender table#obs_table col:last-child {
      width: auto !important;
    }

    #modal_obs table#obs_table td:first-child,
    #modal_extender table#obs_table td:first-child {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

</style>
</head>
<body>
<div class="container">
    <div class="top">
        <div>
            <h1>Registros Cadastrados</h1>
            <div class="small">Total: {total}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <input id="search" class="search" placeholder="Pesquisar (responsável, patrimônio, hardware, modelo...)">
            <button id="btnToggleOrder" class="btn ghost" type="button" title="Alternar ordem por ID">Ordem: Mais novo → antigo</button>
            <form method="GET" action="/export_csv" style="margin:0;">
                <button class="btn" type="submit">Exportar CSV</button>
            </form>
            <a class="btn ghost" href="/">Voltar</a>
        </div>
    </div>

    <div class="table-wrap">
    <table id="tabela" role="table" aria-label="Registros">
        <colgroup>
            <col style="width:2%;">   <!-- ID -->
            <col style="width:5%;">   <!-- Tipo -->
            <col style="width:15%;">  <!-- Responsável -->
            <col style="width:12%;">  <!-- Emprestado para -->
            <col style="width:4%;">   <!-- Patrimônio -->
            <col style="width:5%;">   <!-- Workflow -->
            <col style="width:13%;">  <!-- Motivo -->
            <col style="width:7%;">   <!-- Hardware -->
            <col style="width:7%;">   <!-- Marca -->
            <col style="width:8%;">   <!-- Modelo -->
            <col style="width:5%;">   <!-- Data início -->
            <col style="width:5%;">   <!-- Data retorno -->
            <col style="width:5%;">   <!-- Status -->
            <col style="width:7%;">   <!-- Ação -->
        </colgroup>
        <thead>
            <tr>
                <th>ID</th>
                <th>Tipo</th>
                <th>Responsável</th>
                <th>Emprestado para</th>
                <th>Patrimônio</th>
                <th>Workflow</th>
                <th>Motivo</th>
                <th>Hardware</th>
                <th>Marca</th>
                <th>Modelo</th>
                <th>Data início</th>
                <th>Data retorno</th>
                <th>Status</th>
                <th>Ação</th>
            </tr>
        </thead>
        <tbody>
""" + linhas + """
        </tbody>
    </table>
    </div>
</div>

<!-- Modal Estender (lista) -->
<div id="modal_extender" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:9999;">
  <div style="background:#1b1b1b;padding:20px;border-radius:10px;width:320px;box-shadow:0 6px 18px rgba(0,0,0,0.7);">
    <h3 style="margin:0 0 8px 0;">Estender Empréstimo</h3>
    <form method="POST" action="/estender" id="form_extender_lista">
        <input type="hidden" id="extender_id" name="id">
        <label>Nova data prevista de devolução</label>
        <input id="extender_data" name="data_retorno" required>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
            <button class="btn" type="submit">Salvar</button>
            <button type="button" class="btn ghost" onclick="fecharExtensao()">Cancelar</button>
        </div>
    </form>
  </div>
</div>

<!-- Modal Observação -->
<div id="modal_obs" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:10000;">
  <div style="background:#1b1b1b;padding:22px;border-radius:10px;width:650px;max-width:90vw;box-shadow:0 6px 18px rgba(0,0,0,0.7);">
    <h3 style="margin:0 0 8px 0;">Observações</h3>
    <div style="max-height:420px;overflow:auto;border:1px solid var(--border);padding:10px;border-radius:6px;background:#0f0f0f;color:#e6e6e6;">
      <table id="obs_table" style="width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;">
        <colgroup>
            <col style="width:130px;">   <!-- coluna Data (fina) -->
            <col style="width:auto;">    <!-- coluna Observação ocupa todo o resto -->
        </colgroup>
        <thead><tr><th style="text-align:left;padding:6px;border-bottom:1px solid #222;width:110px;">Data</th><th style="text-align:left;padding:6px;border-bottom:1px solid #222;">Observação</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <form method="POST" action="/adicionar_observacao" id="form_add_obs" style="margin-top:10px;display:flex;gap:8px;flex-direction:column;">
      <input type="hidden" name="id" id="obs_record_id" value="">
      <label style="font-size:13px;color:var(--muted);margin:0;">Adicionar observação</label>
      <textarea name="texto" id="obs_text" required style="min-height:60px;padding:8px;background:#121212;border:1px solid #222;color:#eaeaea;border-radius:6px"></textarea>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button type="submit" class="btn">Adicionar</button>
        <button type="button" class="btn ghost" onclick="fecharObs()">Fechar</button>
      </div>
    </form>
  </div>
</div>

<script>
function abrirExtensao(id, current_date_br){
    try{ document.getElementById('extender_id').value = id; }catch(e){}
    try{ document.getElementById('extender_data').value = current_date_br || ''; }catch(e){}
    try{ document.getElementById('modal_extender').style.display = 'flex'; }catch(e){}
}
function fecharExtensao(){ try{ document.getElementById('modal_extender').style.display = 'none'; }catch(e){} }

function abrirObs(id, obs_json){
    try{
        var list = [];
        if (typeof obs_json === 'string') {
            try { list = JSON.parse(obs_json); } catch(e){ list = []; }
        } else if (Array.isArray(obs_json)) {
            list = obs_json;
        } else if (obs_json && typeof obs_json === 'object') {
            if (Array.isArray(obs_json)) list = obs_json;
            else list = [];
        }
        var tbody = document.querySelector('#obs_table tbody');
        tbody.innerHTML = '';
        if (!list || list.length === 0){
            var tr = document.createElement('tr');
            tr.innerHTML = '<td style="padding:6px;border-bottom:1px solid #222;color:var(--muted);" colspan="2">Nenhuma observação registrada.</td>';
            tbody.appendChild(tr);
        } else {
            list.forEach(function(o){
                var date = o.registrado_em || '';
                var text = o.text || '';
                var tr = document.createElement('tr');
                tr.innerHTML = "<td style='padding:6px;border-bottom:1px solid #222;vertical-align:top;white-space:nowrap;color:var(--muted);'>"+ date +"</td>" +
                               "<td style='padding:6px;border-bottom:1px solid #222;white-space:pre-wrap;'>"+ (text || '') +"</td>";
                tbody.appendChild(tr);
            });
        }
        try{ document.getElementById('obs_record_id').value = id; }catch(e){}
        try{ document.getElementById('obs_text').value = ''; }catch(e){}
        document.getElementById('modal_obs').style.display = 'flex';
    }catch(e){ console.error('abrirObs erro', e); }
}
function fecharObs(){ try{ document.getElementById('modal_obs').style.display = 'none'; }catch(e){} }
</script>

<script>
    // filtro cliente + ordenação por ID (mais novo <-> mais antigo)
    document.getElementById("search").addEventListener("input", function() {
        const q = this.value.toLowerCase();
        const rows = document.querySelectorAll("#tabela tbody tr");
        rows.forEach(r => {
            const text = r.innerText.toLowerCase();
            r.style.display = text.includes(q) ? "" : "none";
        });
    });

    (function(){
        const btn = document.getElementById("btnToggleOrder");
        let desc = true; // true = mais novo -> antigo (desc by id)
        function sortTableById(descending) {
            const tbody = document.querySelector("#tabela tbody");
            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort((a,b) => {
                const ida = parseInt(a.dataset.id||a.getAttribute('data-id')||0,10);
                const idb = parseInt(b.dataset.id||b.getAttribute('data-id')||0,10);
                return descending ? idb - ida : ida - idb;
            });
            // re-append in sorted order
            rows.forEach(r => tbody.appendChild(r));
        }
        btn.addEventListener("click", function(){
            desc = !desc;
            btn.textContent = desc ? "Ordem: Mais novo → antigo" : "Ordem: Mais antigo → novo";
            sortTableById(desc);
        });
        // inicial: garantir que a tabela comece em ordem "mais novo -> antigo"
        try { sortTableById(true); } catch(e){}
    })();
</script>

</body>
</html>
"""

    # CORREÇÃO: evitar usar str.format no HTML inteiro (CSS tem chaves {})
    # Em vez de page.format(total=...), substituí por replace simples.
    page = page.replace("{total}", str(len(registros)))
    return page


# ----------------------------- SERVIDOR (HANDLERS) -----------------------------
class Servidor(BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            self.responder(gerar_html_form(registros))

        elif path == "/lista":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            self.responder(gerar_pagina_lista(registros))

        elif path == "/export_csv":
            # lê registros e gera CSV no response (download)
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            # campos do CSV (ordem) — inclui meta oculta anexada ao mesmo registro
            # nomes de colunas desejados no CSV (sem prefixo "oculto")
            campos = ["id", "tipo", "responsavel", "emprestado_para", "patrimonio", "workflow", "motivo",
                      "hardware", "marca", "modelo", "data_inicio", "data_retorno", "devolvido",
                      "client_ip", "registrado_em"]

            from io import StringIO
            csv_buffer = StringIO();
            writer = csv.DictWriter(csv_buffer, fieldnames=campos)
            writer.writeheader()
            for r in registros:
                # preenche campos básicos (exceto as colunas da meta oculta)
                row = {k: (r.get(k, "") if r.get(k, "") is not None else "") for k in campos if k not in ("client_ip", "registrado_em")}
                # se houver meta oculta, mapeia para as colunas finais sem prefixo
                oculto = r.get("oculto_meta", {}) or {}
                row["client_ip"] = oculto.get("client_ip", "")
                row["registrado_em"] = oculto.get("registrado_em", "")
                writer.writerow(row)

            csv_data = csv_buffer.getvalue();
            csv_buffer.close();

            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=registros_hardware.csv")
            self.end_headers()
            self.wfile.write(csv_data.encode("utf-8"))
            return

        elif path == "/atrasos":
            # retorna apenas o HTML das notificações de atraso (usado pelo AJAX)
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            html = gerar_notificacoes_atraso_html(registros)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        else:
            self.send_error(404, "Página não encontrada")

    def do_POST(self):
        # lê body
        tamanho = int(self.headers.get("Content-Length", 0))
        dados = self.rfile.read(tamanho).decode("utf-8")
        campos = parse_qs(dados)

        path = self.path
        if path == "/registrar":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            # gera novo id (max existente + 1)
            maxid = 0
            for r in registros:
                try:
                    if int(r.get("id", 0)) > maxid:
                        maxid = int(r.get("id", 0))
                except:
                    pass
            novo_id = maxid + 1

            tipo = campos.get("tipo", [""])[0].strip()
            responsavel = campos.get("responsavel", [""])[0].strip()
            patrimonio = campos.get("patrimonio", [""])[0].strip()
            data_inicio_raw = campos.get("data_inicio", [""])[0]
            data_inicio = normalize_br_datetime_str(data_inicio_raw)

            # Validação de campos obrigatórios (servidor)
            if not tipo:
                return self.responder_error("Campo 'Tipo' é obrigatório.")
            if not responsavel:
                return self.responder_error("Campo 'Responsável' é obrigatório.")

            motivo = campos.get("motivo", [""])[0].strip()
            if not motivo:
                return self.responder_error("Campo 'Motivo' é obrigatório.")
            if motivo == "outros":
                motivo_outros = campos.get("motivo_outros", [""])[0].strip()
                if not motivo_outros:
                    return self.responder_error("Descreva o motivo (campo obrigatório quando selecionar 'Outros').")
                motivo = motivo_outros

            hardware = campos.get("hardware", [""])[0].strip()
            if not hardware:
                return self.responder_error("Campo 'Hardware' é obrigatório.")
            if hardware == "outros":
                hardware_outros = campos.get("hardware_outros", [""])[0].strip()
                if not hardware_outros:
                    return self.responder_error("Descreva o hardware (campo obrigatório quando selecionar 'Outros').")
                hardware = hardware_outros

            workflow = campos.get("workflow", [""])[0]
            marca = campos.get("marca", [""])[0]
            modelo = campos.get("modelo", [""])[0]
            observacao = campos.get("observacao", [""])[0].strip()

            # validação servidor-side do tamanho da observação
            if observacao and len(observacao) > 200:
                return self.responder_error("Observação deve ter no máximo 200 caracteres.")

            novo = {
                "id": novo_id,
                "tipo": tipo,
                "responsavel": responsavel,
                "patrimonio": patrimonio,
                "workflow": workflow,
                "data_inicio": data_inicio,
                "motivo": motivo,
                "hardware": hardware,
                "marca": marca,
                "modelo": modelo,
                "devolvido": False,
                "observacao": observacao,
                # grava lista de observações (compatível com futuras adições)
                "observacoes": ([{
                    "text": observacao,
                    "registrado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                }] if observacao else [])
             }

            if tipo == "emprestimo":
                novo["emprestado_para"] = campos.get("emprestado_para", [""])[0]
                novo["data_retorno"] = normalize_br_datetime_str(campos.get("data_retorno", [""])[0])

            # anexa meta oculta diretamente no mesmo registro (não cria outro id)
            try:
                client_ip = self.client_address[0] if hasattr(self, "client_address") else ""
            except:
                client_ip = ""
            if client_ip:
                novo["oculto_meta"] = {
                    "client_ip": client_ip,
                    "registrado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                }

            # grava o registro (visível) com a meta oculta anexa
            registros.append(novo)

            with open(ARQUIVO, "w", encoding="utf-8") as f:
                json.dump(registros, f, ensure_ascii=False, indent=4)

            # redireciona para lista
            self.redirect("/lista")

        elif path == "/devolver":
            id_reg = int(campos.get("id", ["0"])[0])
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        r["devolvido"] = True;
                        updated = True
                except:
                    pass

            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

            self.redirect("/lista")

        elif path == "/ocultar":
            # marca um registro como oculto (não apaga do JSON)
            id_reg = int(campos.get("id", ["0"])[0])
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        r["oculto"] = True
                        updated = True
                except:
                    pass

            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

            self.redirect("/lista")

        elif path == "/estender":
            # atualiza data_retorno de um registro de empréstimo (formato BR)
            id_reg = int(campos.get("id", ["0"])[0])
            nova_data_raw = campos.get("data_retorno", [""])[0]
            nova_data_br = normalize_br_datetime_str(nova_data_raw)

            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        r["data_retorno"] = nova_data_br;
                        updated = True
                except:
                    pass

            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

            # redireciona para lista
            self.redirect("/lista")

        elif path == "/adicionar_observacao":
            # adiciona uma observação a um registro (anexa em "observacoes")
            try:
                id_reg = int(campos.get("id", ["0"])[0])
            except:
                id_reg = 0
            texto = campos.get("texto", [""])[0].strip()

            if not texto:
                return self.responder_error("Observação vazia.")

            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        if "observacoes" not in r or not isinstance(r["observacoes"], list):
                            r["observacoes"] = []
                        novo = {
                            "text": texto,
                            "registrado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                        }
                        r["observacoes"].append(novo)
                        # manter último texto também em 'observacao' para compatibilidade
                        r["observacao"] = texto
                        updated = True
                except:
                    pass

            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

            # volta para a página de lista (tenta referer se disponível)
            referer = self.headers.get("Referer", "/lista")
            self.redirect(referer)

        else:
            self.send_error(404, "Ação desconhecida")

    # utilitários
    def responder(self, conteudo):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(conteudo.encode("utf-8"))

    def responder_error(self, mensagem):
        conteudo = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Erro</title></head>"
            "<body style='background:#0f0f10;color:#eaeaea;font-family:Inter,Arial;padding:20px;'>"
            "<h2>Erro</h2><p>{}</p>"
            "<p><a href='/' style='color:#3aa0ff'>Voltar</a></p></body></html>".format(mensagem)
        )
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(conteudo.encode("utf-8"))

    def redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    print("Servidor rodando em http://localhost:8000")

    ThreadingHTTPServer(("0.0.0.0", 8000), Servidor).serve_forever()
