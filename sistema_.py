import json
import csv
import datetime
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from socketserver import ThreadingMixIn
from zoneinfo import ZoneInfo

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


def sp_now_naive():
    """
    Retorna datetime naive (sem tzinfo) representando o horário atual em America/Sao_Paulo,
    com segundos/microseconds zerados. Em fallback, usa o horário do servidor.
    """
    try:
        tz = ZoneInfo("America/Sao_Paulo")
        now = datetime.datetime.now(tz).replace(second=0, microsecond=0)
        # retornar como naive (consistência com parse_br_datetime que cria naive datetimes)
        return datetime.datetime(now.year, now.month, now.day, now.hour, now.minute)
    except Exception:
        return datetime.datetime.now().replace(second=0, microsecond=0)


def sp_now_str():
    return sp_now_naive().strftime("%d/%m/%Y %H:%M")


def calcular_status(registro):
    """
    Calcula o status do registro para exportação CSV.
    Retorna uma string com o status.
    """
    tipo = registro.get("tipo", "")
    devolvido = registro.get("devolvido", False)
    estoque = registro.get("estoque", False)
    status_extra = registro.get("status_extra", "")
    
    if devolvido:
        if status_extra:
            return status_extra
        else:
            return "Devolvido"
    
    # Verificar se é empréstimo atrasado
    if tipo == "emprestimo" and not devolvido:
        dt_raw = registro.get("data_retorno", "")
        dt = parse_br_datetime(dt_raw)
        if dt and dt <= sp_now_naive():
            return f"Atrasado ({dt.strftime('%d/%m/%Y')})"
    
    if estoque and tipo == "entrada":
        return "Em estoque"
    
    if tipo == "emprestimo":
        return "Ativo"
    
    return ""  # Para entradas e saídas não devolvidas


def gerar_notificacoes_atraso_html(registros):
    """(Deprecated) Mantido para compatibilidade — usar gerar_pendencias_html no frontend.""" 
    atrasados = []
    now_min = sp_now_naive()
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False):
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

    atrasados.sort(key=lambda x: x[1])

    for r, dt in atrasados:
        data_retorno_display = dt.strftime("%d/%m/%Y %H:%M")
        html += (f"<li style='color:#ff9999;margin-bottom:4px;'>"
                 f"<strong>ID {r.get('id','')}</strong> — {r.get('emprestado_para','')} — "
                 f"Patrimônio: {r.get('patrimonio','')} — Previsto: {data_retorno_display}"
                 f"</li>")

    html += "</ul></div>"
    return html


def gerar_pendencias_html(registros):
    """
    Gera mini painel com:
    - atrasos (emprestimos vencidos) no topo
    - entradas com motivo != 'outros' sem atualização a mais de 7 dias (sem saida com mesmo workflow OU sem observação atualizada)
    """
    now = sp_now_naive()
    atrasos = []
    pendencias = []

    # map workflow -> list of registros (para busca rápida)
    workflow_map = {}
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            continue
        wf = (r.get("workflow") or "").strip()
        if wf:
            workflow_map.setdefault(wf, []).append(r)

    # achar atrasos (emprestimo com data_retorno passada)
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            continue
        if r.get("tipo") == "emprestimo" and not r.get("devolvido", False):
            dt_raw = r.get("data_retorno", "")
            dt = parse_br_datetime(dt_raw)
            if dt and dt <= now:
                atrasos.append((r, dt))

    # pendências de entrada (motivo != outros)
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            continue
        if r.get("tipo") != "entrada":
            continue
        motivo = (r.get("motivo") or "").strip().lower()
        if motivo == "outros" or motivo == "outro" or motivo == "other":
            continue
        data_inicio_raw = r.get("data_inicio", "")
        dt_inicio = parse_br_datetime(data_inicio_raw)
        if not dt_inicio:
            continue
        delta_days = (now - dt_inicio).days
        if delta_days < 7:
            continue

        wf = (r.get("workflow") or "").strip()
        tem_saida_com_wf = False
        if wf:
            others = workflow_map.get(wf, [])
            for o in others:
                if o is r:
                    continue
                if o.get("tipo") == "saida" and not o.get("oculto", False):
                    tem_saida_com_wf = True
                    break

        # última observação registrada no próprio registro (se houver)
        last_obs_date = None
        try:
            obs_list = r.get("observacoes", []) or []
            # pegar o mais recente
            for ob in obs_list:
                reg_em = ob.get("registrado_em") or ob.get("registered_at") or ""
                dt_obs = parse_br_datetime(reg_em)
                if dt_obs:
                    if (last_obs_date is None) or dt_obs > last_obs_date:
                        last_obs_date = dt_obs
        except Exception:
            last_obs_date = None

        obs_antiga = True
        if last_obs_date:
            # se última observação foi dentro dos últimos 7 dias, considera atualizada
            obs_antiga = (now - last_obs_date).days >= 7
        else:
            obs_antiga = True

        # mostrará se não existe saida com mesmo workflow OU se a última observação é antiga/ausente
        # CORREÇÃO: deve mostrar somente se NÃO existe saída com o mesmo workflow E a observação for antiga/ausente.
        # Ou seja: quando houver observação recente ou já existir saída com o workflow, não deve aparecer.
        if (not tem_saida_com_wf) and obs_antiga:
            pendencias.append((r, delta_days))

    # gerar HTML do painel
    html = '<div style="padding:10px;border-radius:8px;background:#111;border:1px solid rgba(255,255,255,0.03);max-width:320px;">'

    # atrasos no topo
    if atrasos:
        html += '<div style="padding:8px;border-radius:6px;background:#33111166;margin-bottom:8px;">'
        html += '<strong style="color:#ffcccb;">Atrasos</strong>'
        html += '<ul style="margin:6px 0 0 16px;padding:0;">'
        atrasos.sort(key=lambda x: x[1])
        for r, dt in atrasos:
            data_retorno_display = dt.strftime("%d/%m/%Y %H:%M")
            html += (f"<li style='color:#ff9999;margin-bottom:6px;'>"
                     f"Máquina de patrimônio <strong>{r.get('patrimonio','')}</strong> e Workflow <strong>{r.get('workflow','')}.</strong>"
                     f"<br> Previsto: <strong>{data_retorno_display}</strong> </br>"
                     "</li>"
                     )
        html += '</ul></div>'

    # pendencias de entradas
    if pendencias:
        html += '<div style="padding:8px;border-radius:6px;background:#3a2d00;margin-bottom:4px;">'
        html += '<strong style="color:#ffd966;">Entradas sem atualização (>=7 dias)</strong>'
        html += '<ul style="margin:6px 0 0 16px;padding:0;">'
        # ordenar por dias (mais antigo primeiro)
        pendencias.sort(key=lambda x: -x[1])
        for r, dias in pendencias:
            patrimonio = r.get('patrimonio','')
            wf = r.get('workflow','')
            html += (f"<li style='color:#fff5cc;margin-bottom:6px;'>"
                     f"Máquina de patrimônio <strong>{patrimonio}</strong> e Workflow <strong>{wf}</strong> sem atualização a mais de <strong>{dias}</strong> dias."
                     "</li>")
        html += '</ul></div>'

    if not atrasos and not pendencias:
        html += '<div style="padding:6px;border-radius:6px;background:#0f0f0f;color:var(--muted);">Sem pendências.</div>'

    html += '</div>'
    return html


# ----------------------------- HTML TEMPLATE (INDEX) -----------------------------
def gerar_html_form(registros):
    # não preencher aqui com a hora do servidor — o cliente (navegador) preencherá com sua hora local

    # monta options do select responsável a partir da array RESPONSAVEIS
    responsaveis_html = ""
    for r in RESPONSAVEIS:
        responsaveis_html += '<option value="{}">{}</option>'.format(r, r)

    # pendencias (inclui atrasos no topo)
    pendencias_html = gerar_pendencias_html(registros)

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
        width:960px;
        max-width:calc(100vw - 40px);
        margin:20px auto;
    }

    /* layout que coloca o painel de pendências como card separado à esquerda
       e o formulário principal como card centralizado ao lado direito (desktop).
       Em mobile empilha com o painel de pendências acima do formulário. */
    .dashboard {
        display:flex;
        gap:16px;
        justify-content:center;
        align-items:flex-start;
        max-width:calc(100vw - 40px);
        margin:20px auto;
        padding:0 10px;
        box-sizing:border-box;
    }
    .left-card {
        flex:0 0 320px;
        width:320px;
        max-width:320px;
        margin:0;
        padding:18px;
    }
    .dashboard .card {
        /* form card menor quando dentro do dashboard */
        width:720px;
        max-width: calc(100vw - 360px);
        margin:0;
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

    .layout { display:flex; gap:16px; align-items:flex-start; }
    .left-panel { width:320px; flex:0 0 320px; }
    .form-panel { flex:1; }

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
         display:inline-flex;
         align-items:center;
         justify-content:center;
         gap:0;
         width:22px;
         height:22px;
         padding:0;
         box-sizing:border-box;
         border-radius:6px;
         font-weight:700;
         cursor:pointer;
         border: none;
         font-size:16px;
         line-height:0;
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
    .btn-excluir svg { width:18px; height:18px; display:block; margin:0; vertical-align:middle; }
    .btn-action svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }
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

    /* responsividade: empilha em telas pequenas */
    @media (max-width: 920px) {
        .layout { flex-direction:column; }
        .left-panel { width:100%; flex-basis:auto; }

        /* empilhar dashboard em mobile: painel de pendências acima do formulário */
        .dashboard { flex-direction:column; align-items:stretch; padding:0 12px; }
        .left-card { order: -1; width:100%; max-width:100%; margin-bottom:12px; }
        .dashboard .card { width:100%; max-width:100%; }
    }

</style>
</head>
<body>

<!-- Painel de pendências separado (card próprio) -->
<div class="dashboard">
  <div class="card left-card" role="complementary" aria-label="Painel de Pendências">
    <div class="topbar">
      <h1>Painel de Pendências</h1>
    </div>
    <div id="mini_pendencias">
""" + pendencias_html + """
    </div>
  </div>

  <!-- Formulário principal em seu próprio card -->
  <div class="card" role="main" aria-label="Registrar Movimentação">
    <div class="topbar">
      <h1>Registrar Movimentação</h1>
      <div>
        <!-- link anterior mantido (pode ser removido se desejar) -->
        <a class="link-lista" href="/lista">Ver Registros</a>
      </div>
    </div>

    <div class="layout">
      <!-- Right: formulário principal -->
      <div class="form-panel">
    <form method="POST" action="/registrar" id="mainForm" onsubmit="return validarFormulario()">
        <!-- campo oculto preenchido no cliente com o usuário da máquina (se possível) -->
        <input type="hidden" name="client_user" id="client_user" value="">
        <input type="hidden" name="registrado_em" id="registrado_em_main" value="">
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
                        <!-- REMOVIDO: required -->
                        <input type="text" name="patrimonio" id="patrimonio" pattern="\\d{7,}" inputmode="numeric" placeholder="Ex.: 1234567"
                               title="Digite apenas números. Mínimo 7 dígitos. Opcional para Teclado/Mouse.">
                        <div class="note" style="margin-top:2px;font-size:12px;">Opcional para Teclado/Mouse</div>
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
    </div>
  </div>
</div>

<!-- Modal Extender / Observação ficam inalterados -->
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

<div id="modal_obs" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:10000;">
  <div style="background:#1b1b1b;padding:22px;border-radius:10px;width:650px;max-width:90vw;box-shadow:0 6px 18px rgba(0,0,0,0.7);">
    <h3 style="margin:0 0 8px 0;">Observações</h3>
    <div style="max-height:420px;overflow:auto;border:1px solid var(--border);padding:10px;border-radius:6px;background:#0f0f0f;color:#e6e6e6;">
      <table id="obs_table" style="width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;">
        <colgroup>
            <col style="width:130px;">
            <col style="width:auto;">
        </colgroup>
        <thead><tr><th style="text-align:left;padding:6px;border-bottom:1px solid #222;width:110px;">Data</th><th style="text-align:left;padding:6px;border-bottom:1px solid #222;">Observação</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <form method="POST" action="/adicionar_observacao" id="form_add_obs" style="margin-top:10px;display:flex;gap:8px;flex-direction:column;">
      <input type="hidden" name="id" id="obs_record_id" value="">
      <input type="hidden" name="registrado_em" id="registrado_em_obs" value="">
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
    // Atualização automática do painel de pendências (a cada 20s)
    const ATUALIZA_INTERVAL_MS = 20000;
    async function atualizarAtrasos() {
        try {
            const res = await fetch('/atrasos');
            if (!res.ok) return;
            const html = await res.text();
            const el = document.getElementById('mini_pendencias');
            if (el) el.innerHTML = html;
        } catch (e) {
            console.error('Erro atualizando pendências:', e);
        }
    }
    setInterval(atualizarAtrasos, ATUALIZA_INTERVAL_MS);

    function initFlatpickrBR(selector) {
        flatpickr(selector, {
            enableTime: true,
            time_24hr: true,
            dateFormat: "d/m/Y H:i",
            locale: "pt",
            theme: "light",  // Força tema claro
            // Desabilita a detecção automática de tema escuro
            onReady: function(selectedDates, dateStr, instance) {
                // Remove qualquer classe de tema escuro que possa ter sido adicionada
                instance.calendarContainer.classList.remove("flatpickr-dark");
                instance.calendarContainer.classList.add("flatpickr-light");
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        try {
            function pad(n){ return n.toString().padStart(2, '0'); }
            function formatBRDate(d){
                return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear()
                    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
            }
            document.getElementById("data_inicio").value = formatBRDate(new Date());
        } catch (e) {
            console.error('Erro ao setar data_inicio:', e);
        }
        // preencher registrado_em com data do cliente antes de enviar formulários
        try {
            var mainForm = document.getElementById('mainForm');
            if (mainForm) {
                mainForm.addEventListener('submit', function(){
                    try { document.getElementById('registrado_em_main').value = formatBRDate(new Date()); } catch(e){}
                });
            }
        } catch(e){}

        try {
            var formObs = document.getElementById('form_add_obs');
            if (formObs) {
                formObs.addEventListener('submit', function(){
                    try { document.getElementById('registrado_em_obs').value = formatBRDate(new Date()); } catch(e){}
                });
            }
        } catch(e){}

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

        initFlatpickrBR("#data_inicio");
        initFlatpickrBR("#data_retorno");
        initFlatpickrBR("#extender_data");

        atualizarAtrasos();

        try {
            toggleOutroMotivo();
            toggleOutroHardware();
            toggleEmprestimoCampos();
        } catch (e) {}
    });

    function toggleOutroMotivo() {
        const show = document.getElementById("motivo_select").value === "outros";
        document.getElementById("motivo_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("motivo_outros").required = true;
        else document.getElementById("motivo_outros").required = false;
    }

    function toggleOutroHardware() {
        const show = document.getElementById("hardware_select").value === "outros";
        document.getElementById("hardware_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("hardware_outros").required = true;
        else document.getElementById("hardware_outros").required = false;
    }

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

    function validarFormulario() {
        const patr = document.getElementById("patrimonio").value.trim();
        const hardware = document.getElementById("hardware_select").value;
        
        // Se não for Teclado/Mouse e o patrimônio foi preenchido, valida
        if (hardware !== "Teclado/Mouse" && patr !== "") {
            if (!/^[0-9]{7,}$/.test(patr)) {
                alert("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos.");
                return false;
            }
        }
        // Se for Teclado/Mouse, o patrimônio é opcional, mas se preenchido deve ser válido
        else if (hardware === "Teclado/Mouse" && patr !== "") {
            if (!/^[0-9]{7,}$/.test(patr)) {
                alert("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos, ou deixe em branco para Teclado/Mouse.");
                return false;
            }
        }

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
            document.querySelectorAll('.flatpickr-input').forEach(i => i.value = "");
        } catch (e) {}
    }

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
            if (typeof obs_json === 'string') {
                try { list = JSON.parse(obs_json); } catch (e) { list = []; }
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

    document.addEventListener("DOMContentLoaded", function() {
    });
</script>

</body>
</html>
"""
    return html


# ----------------------------- LISTA / REGISTROS PAGE -----------------------------
def gerar_pagina_lista(registros):
    # --- CORREÇÃO: gerar responsaveis_html localmente (evita NameError) ---
    responsaveis_html = ""
    for r in RESPONSAVEIS:
        responsaveis_html += '<option value="{}">{}</option>'.format(r, r)

    # --- calcular pendências/atrasos similar a gerar_pendencias_html ---
    now = sp_now_naive()
    workflow_map = {}
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            # ainda adicionamos ao mapa para checagem de workflow, mesmo se oculto
            wf = (r.get("workflow") or "").strip()
            if wf:
                workflow_map.setdefault(wf, []).append(r)
        else:
            wf = (r.get("workflow") or "").strip()
            if wf:
                workflow_map.setdefault(wf, []).append(r)

    atrasos_ids = set()
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            # pendências/atrasos normalmente não consideram ocultos/estoque/devolvidos,
            # mas seguimos a lógica do painel (ignora ocultos/estoque/devolvido)
            pass
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            continue
        if r.get("tipo") == "emprestimo" and not r.get("devolvido", False):
            dt_raw = r.get("data_retorno", "")
            dt = parse_br_datetime(dt_raw)
            if dt and dt <= now:
                atrasos_ids.add(str(r.get("id", "")))

    pendencias_ids = set()
    for r in registros:
        if r.get("oculto", False) or r.get("estoque", False) or r.get("devolvido", False):
            continue
        if r.get("tipo") != "entrada":
            continue
        motivo = (r.get("motivo") or "").strip().lower()
        if motivo == "outros" or motivo == "outro" or motivo == "other":
            continue
        data_inicio_raw = r.get("data_inicio", "")
        dt_inicio = parse_br_datetime(data_inicio_raw)
        if not dt_inicio:
            continue
        delta_days = (now - dt_inicio).days
        if delta_days < 7:
            continue

        wf = (r.get("workflow") or "").strip()
        tem_saida_com_wf = False
        if wf:
            others = workflow_map.get(wf, [])
            for o in others:
                if o is r:
                    continue
                if o.get("tipo") == "saida" and not o.get("oculto", False):
                    tem_saida_com_wf = True
                    break

        # última observação registrada no próprio registro (se houver)
        last_obs_date = None
        try:
            obs_list = r.get("observacoes", []) or []
            for ob in obs_list:
                reg_em = ob.get("registrado_em") or ob.get("registered_at") or ""
                dt_obs = parse_br_datetime(reg_em)
                if dt_obs:
                    if (last_obs_date is None) or dt_obs > last_obs_date:
                        last_obs_date = dt_obs
        except Exception:
            last_obs_date = None

        obs_antiga = True
        if last_obs_date:
            obs_antiga = (now - last_obs_date).days >= 7
        else:
            obs_antiga = True

        if (not tem_saida_com_wf) and obs_antiga:
            pendencias_ids.add(str(r.get("id", "")))

    # gera linhas da tabela (não removendo os ocultos; marcamos com data-atributos)
    linhas = ""
    for r in registros:
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
        devolvido = bool(r.get("devolvido", False))
        observacao = r.get("observacao", "")
        estoque = bool(r.get("estoque", False))
        oculto = bool(r.get("oculto", False))

        id_str = str(id_)

        # --- cálculo de atraso (mantém) ---
        atrasado = False
        atraso_html = ""
        try:
            now_min = sp_now_naive()
            if tipo == "emprestimo" and not devolvido:
                dt_ret = parse_br_datetime(data_retorno)
                if dt_ret and dt_ret <= now_min:
                    atrasado = True
                    atraso_html = f"<span style='color:#ff6b6b;font-weight:700;'>Atrasado ({dt_ret.strftime('%d/%m/%Y')})</span>"
        except Exception:
            atrasado = False
            atraso_html = ""

        # botão observação (sempre aparece). Passa lista de observações serializada para o JS.
        try:
            obs_list = r.get("observacoes", []) or []
            safe_obs_json = json.dumps(obs_list, ensure_ascii=False).replace("</", "<\\/").replace("'", "\\'")
        except Exception:
            safe_obs_json = "[]"

        botao_observacao = (
            f'<span style="display:inline-flex;align-items:center;">'
            f'<button class="btn-action btn-observacao" title="Ver observações" onclick=\'abrirObs({id_}, {safe_obs_json})\' type="button">'
            '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
            '<path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm.88 15h-1.75v-1.75h1.75V17zm0-3.5h-1.75V6.5h1.75v7z"/>'
            '</svg>'
            '</button>'
            '</span>'
        )

        # botões padrões (devolver/extender/estoque/excluir) - simplificados; mantemos os existentes quando necessário
        botao_devolver = ""
        botao_extender = ""
        botao_estoque = ""
        if not devolvido:
            botao_devolver = (
                '<form method="POST" action="/retornar" style="display:inline-flex;align-items:center;margin:0;">'
                 f'<input type="hidden" name="id" value="{id_}">'
                 '<button type="submit" class="btn-action btn-devolver" title="Retornar máquina">'
                 '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
                 '<path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19l12-12-1.4-1.4z"/>'
                 '</svg>'
                 '</button>'
                 '</form>'
             )
            if tipo == "emprestimo":
                data_retorno_br = normalize_br_datetime_str(data_retorno) if data_retorno else ""
                safe_data = data_retorno_br.replace("'", "\\'")
                botao_extender = (
                     f'<span style="display:inline-flex;align-items:center;">'
                     f'<button class="btn-action btn-estender" title="Estender empréstimo" onclick="abrirExtensao({id_}, \'{safe_data}\')" type="button">'
                      '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
                      '<path fill="currentColor" d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5 0 .34-.03.67-.09.99L19 14.5c.06-.33.09-.67.09-1.01 0-4.42-3.58-8-8-8zM6.09 9.01C6.03 9.33 6 9.66 6 10c0 4.42 3.58 8 8 8v3l4-4-4-4v3c-3.31 0-6-2.69-6-6 0-.34.03-.67.09-.99L6.09 9.01z"/>'
                      '</svg>'
                      '</button>'
                     '</span>'
                  )
        if tipo == "entrada" and not devolvido:
            estoque_status = "Remover do estoque" if estoque else "Colocar em estoque"
            botao_estoque = (
                f'<form method="POST" action="/alternar_estoque" style="display:inline-flex;align-items:center;margin:0;">'
                f'<input type="hidden" name="id" value="{id_}">'
                f'<button type="submit" class="btn-action btn-estoque" title="{estoque_status}">'
                '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
                '<path fill="currentColor" d="M21 16.5c0 .38-.21.71-.53.88l-7.9 4.44c-.16.12-.36.18-.57.18-.21 0-.41-.06-.57-.18l-7.9-4.44A.991.991 0 0 1 3 16.5v-9c0-.38.21-.71.53-.88l7.9-4.44c.16-.12.36-.18.57-.18.21 0 .41.06.57.18l7.9 4.44c.32.17.53.5.53.88v9zM12 4.15L6.04 7.5 12 10.85l5.96-3.35L12 4.15zM5 15.91l6 3.38v-6.71L5 9.21v6.7zm14 0v-6.7l-6 3.37v6.71l6-3.38z"/>'
                '</svg>'
                '</button>'
                '</form>'
            )

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

        # prioridade: Excluído (oculto) > Devolvido > Atrasado > Em estoque > Ativo
        if oculto:
            status = "<span style='color:#ff5050;font-weight:700;'>Excluído</span>"
        else:
            if devolvido:
                if r.get("status_extra"):
                    status = r.get("status_extra")
                else:
                    status = "Devolvido"
            elif atrasado:
                status = atraso_html
            elif estoque and tipo == "entrada":
                status = "Em estoque"
            else:
                status = "Ativo" if tipo == "emprestimo" else ""

        # marcar pendencia/atraso
        is_pendencia = id_str in pendencias_ids or id_str in atrasos_ids
        is_atraso = id_str in atrasos_ids

        # adicionar data-atributos para filtragem client-side e classe para ocultos
        tr_class = "oculto-row" if oculto else ""
        linhas += (
            f'<tr class="{tr_class}" data-id="{id_}" data-devolvido="{str(devolvido).lower()}" '
            f'data-estoque="{str(estoque).lower()}" data-oculto="{str(oculto).lower()}" '
            f'data-pendencia="{str(is_pendencia).lower()}" data-atraso="{str(is_atraso).lower()}">'
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
            f'<td><div style="display:flex;gap:6px;align-items:center;">{botao_devolver}{botao_extender}{botao_observacao}{botao_estoque}{botao_excluir}</div></td>'
            '</tr>'
        )

    # inserir o select de visão entre a pesquisa e o botão de ordem e JS para controlar as views
    page = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Registros Cadastrados</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<style>
    :root {
        --bg:#0f0f10; --card:#111; --muted:#9aa0a6; --border:#222; --accent:#4caf50;
        --accent-2:#3aa0ff;
    }
    body { background:var(--bg); color:#eaeaea; font-family:Inter, Arial; margin:0; padding:20px; }
    .container { max-width:calc(100vw - 40px); margin:0 auto; }
    h1 { margin:0 0 10px 0; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap; }
    .search { padding:8px 10px; border-radius:8px; border:1px solid var(--border); background:#121212; color:#eee; min-width:220px; }
    .btn { padding:8px 10px; border-radius:8px; cursor:pointer; border:none; background:var(--accent); color:#071007; font-weight:700; }
    .btn.ghost { background:transparent; border:1px solid var(--border); color:var(--muted); }
    .table-wrap { overflow-x: visible; }
    table { width:100%; max-width:100%; border-collapse:collapse; margin-top:12px; background:#0e0e0e; border-radius:8px; overflow:visible; table-layout:fixed; }
    colgroup col { vertical-align:top; }
    th, td { padding:8px 9px; border-bottom:1px solid #1b1b1b; font-size:13px; white-space:normal; word-break:break-word; overflow-wrap:break-word; hyphens:auto; }
    th { text-align:left; background:#0d0d0d; color:var(--muted); position:sticky; top:0; z-index:2; }
    th, td { border-right:1px solid rgba(255,255,255,0.04); }
    th:last-child, td:last-child { border-right: none; }
    tr:nth-child(even) td { background:#0b0b0b; }
    .small { font-size:12px; color:var(--muted); }
    form.inline { display:inline; }

    /* estilo específico para o seletor de visão */
    #view_selector {
        padding:8px 10px;
        border-radius:8px;
        border:1px solid var(--border);
        background:#121212;
        color:#eee;
        font-size:14px;
        -webkit-appearance: none;
        appearance: none;
    }

    /* linhas ocultas (excluídas) aparecem em vermelho */
    tr.oculto-row td { color: #ff6b6b; }

    .btn-action {
         display:inline-flex;
         align-items:center;
         justify-content:center;
         gap:0;
         width:22px;
         height:22px;
         padding:0;
         box-sizing:border-box;
         border-radius:6px;
         font-weight:700;
         cursor:pointer;
         border: none;
         font-size:16px;
         line-height:0;
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
    .btn-estoque {
        background: linear-gradient(180deg, #3a6ea5, #1e3a5f);
        color:#ffffff;
        border: none;
    }
    .btn-excluir svg { width:18px; height:18px; display:block; margin:0; vertical-align:middle; }
    .btn-action svg { width:16px; height:16px; display:block; margin:0; vertical-align:middle; }
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

    /* Modal Export CSS: deixa visual igual ao formulário */
    #modal_export {
        display:none;
        position:fixed;
        top:0; left:0; width:100%; height:100%;
        background:rgba(0,0,0,0.6);
        align-items:center; justify-content:center;
        z-index:11000;
    }
    #modal_export .modal-inner {
        background:#1b1b1b;
        padding:18px;
        border-radius:10px;
        width:560px;
        max-width:94vw;
        box-shadow:0 6px 18px rgba(0,0,0,0.7);
    }
    #modal_export h3 { margin:0 0 10px 0; }

    /* grid de filtros: checkbox (esq) | controle (dir) */
    #modal_export .export-grid {
        display:grid;
        grid-template-columns: 220px 1fr;
        gap:10px 12px;
        align-items:center;
    }
    #modal_export .export-left { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:14px; }
    #modal_export .export-left input[type="checkbox"] { width:16px; height:16px; }
    /* usar mesmo estilo dos inputs do formulário */
    #modal_export .export-right input[type="text"],
    #modal_export .export-right select {
        width:100%;
        box-sizing:border-box;
        padding:8px 10px;
        margin-top:0;
        background:var(--input-bg);
        border:1px solid var(--border);
        color: #eaeaea;
        border-radius:8px;
        outline:none;
        font-size:14px;
        -webkit-appearance: none;
        appearance: none;
    }
    /* força opções com tema escuro (alguns navegadores usam default claro) */
    #modal_export .export-right select option {
        color: #eaeaea;
        background: #1b1b1b;
    }
    #modal_export .export-right .two-inline { display:flex; gap:8px; }
    #modal_export .export-right .two-inline input { flex:1; }

    /* responsivo: empilha em telas pequenas */
    @media (max-width:640px) {
        #modal_export .export-grid {
            grid-template-columns: 1fr;
        }
        #modal_export .export-left { padding:8px 0; }
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
            <!-- Seletor de visão adicionado aqui -->
            <select id="view_selector" title="Selecionar vista">
                <option value="ativos" selected>Listar: Ativos</option>
                <option value="inativos">Listar: Inativos</option>
                <option value="estoque">Listar: Estoque</option>
                <option value="pendentes">Listar: Pendentes</option>
                <option value="legado">Lista: Legado</option>
                <option value="tudo">Listar: Tudo</option>
            </select>
            <button id="btnToggleOrder" class="btn ghost" type="button" title="Alternar ordem por ID">Ordem: Mais novo → antigo</button>
            <!-- Agora abre modal com filtros -->
            <button id="btnExportCsv" class="btn" type="button">Exportar CSV</button>
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
            <col style="width:5%;">   <!-- Patrimônio -->
            <col style="width:5%;">   <!-- Workflow -->
            <col style="width:11%;">  <!-- Motivo -->
            <col style="width:7%;">   <!-- Hardware -->
            <col style="width:7%;">   <!-- Marca -->
            <col style="width:8%;">   <!-- Modelo -->
            <col style="width:5%;">   <!-- Data início -->
            <col style="width:5%;">   <!-- Data retorno -->
            <col style="width:5%;">   <!-- Status -->
            <col style="width:8%;">   <!-- Ação -->
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
                <th>Data registro</th>
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

<!-- Modal de Export CSV (reorganizado em grid: checkbox left | control right) -->
<div id="modal_export">
  <div class="modal-inner">
    <h3>Exportar CSV — Filtros</h3>
    <form id="form_export" method="GET" action="/export_csv" style="display:flex;flex-direction:column;gap:12px;">
      <div class="export-grid">
        <div class="export-left"><label><input type="checkbox" name="f_all" id="f_all"> <span>Todos (exporta tudo)</span></label></div>
        <div class="export-right"><div class="note">Selecionar para exportar todos os registros</div></div>

        <div class="export-left"><label><input type="checkbox" name="f_manual" id="f_manual"> <span>Manual (exporta o que estou vendo)</span></label></div>
        <div class="export-right"><div class="note">Exporta apenas os IDs visíveis na tabela</div></div>

        <div class="export-left"><label><input type="checkbox" name="f_tipo" id="f_tipo"> <span>Tipo</span></label></div>
        <div class="export-right">
          <select name="tipo_value" id="tipo_value">
            <option value="">-- selecione --</option>
            <option value="entrada">Entrada</option>
            <option value="saida">Saída</option>
            <option value="emprestimo">Empréstimo</option>
          </select>
        </div>

        <div class="export-left"><label><input type="checkbox" name="f_responsavel" id="f_responsavel"> <span>Responsável</span></label></div>
        <div class="export-right">
          <select name="responsavel_value" id="responsavel_value">
            <option value="">-- selecione --</option>
""" + responsaveis_html + """
          </select>
        </div>

        <div class="export-left"><label><input type="checkbox" name="f_emprestado_para" id="f_emprestado_para"> <span>Emprestado para</span></label></div>
        <div class="export-right"><input type="text" name="emprestado_para_value" id="emprestado_para_value" placeholder="Texto a buscar"></div>

        <div class="export-left"><label><input type="checkbox" name="f_patrimonio" id="f_patrimonio"> <span>Patrimônio</span></label></div>
        <div class="export-right"><input type="text" name="patrimonio_value" id="patrimonio_value" placeholder="Ex.: 1234567"></div>

        <div class="export-left"><label><input type="checkbox" name="f_workflow" id="f_workflow"> <span>Workflow</span></label></div>
        <div class="export-right"><input type="text" name="workflow_value" id="workflow_value" placeholder="Ex.: P-1234567"></div>

        <div class="export-left"><label><input type="checkbox" name="f_motivo" id="f_motivo"> <span>Motivo</span></label></div>
        <div class="export-right">
          <select name="motivo_value" id="motivo_value">
            <option value="">-- selecione --</option>
            <option value="formatação">Formatação</option>
            <option value="manutenção">Manutenção</option>
            <option value="reparo">Reparo</option>
            <option value="outros">Outros</option>
          </select>
        </div>

        <div class="export-left"><label><input type="checkbox" name="f_hardware" id="f_hardware"> <span>Hardware</span></label></div>
        <div class="export-right">
          <select name="hardware_value" id="hardware_value">
            <option value="">-- selecione --</option>
            <option value="Desktop">Desktop</option>
            <option value="Notebook">Notebook</option>
            <option value="Teclado/Mouse">Teclado/Mouse</option>
            <option value="Monitor">Monitor</option>
            <option value="outros">Outros</option>
          </select>
        </div>

        <div class="export-left"><label><input type="checkbox" name="f_marca" id="f_marca"> <span>Marca</span></label></div>
        <div class="export-right"><input type="text" name="marca_value" id="marca_value" placeholder="Ex.: Dell"></div>

        <div class="export-left"><label><input type="checkbox" name="f_modelo" id="f_modelo"> <span>Modelo</span></label></div>
        <div class="export-right"><input type="text" name="modelo_value" id="modelo_value" placeholder="Ex.: OptiPlex"></div>

        <div class="export-left"><label><input type="checkbox" name="f_data" id="f_data"> <span>Data (intervalo)</span></label></div>
        <div class="export-right">
          <div class="two-inline">
            <input type="text" name="date_from" id="date_from" placeholder="De (DD/MM/AAAA HH:mm)">
            <input type="text" name="date_to" id="date_to" placeholder="Até (DD/MM/AAAA HH:mm)">
          </div>
        </div>

        <!-- campo oculto que receberá os ids quando Manual for usado -->
        <div class="export-left"></div>
        <div class="export-right"><input type="hidden" name="manual_ids" id="manual_ids" value=""></div>

      </div>

      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px;">
        <button type="submit" class="btn">Exportar</button>
        <button type="button" class="btn ghost" id="btnCancelExport">Cancelar</button>
      </div>
    </form>
  </div>
</div>

<!-- Modals (lista) -->
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

<div id="modal_obs" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:10000;">
  <div style="background:#1b1b1b;padding:22px;border-radius:10px;width:650px;max-width:90vw;box-shadow:0 6px 18px rgba(0,0,0,0.7);">
    <h3 style="margin:0 0 8px 0;">Observações</h3>
    <div style="max-height:420px;overflow:auto;border:1px solid var(--border);padding:10px;border-radius:6px;background:#0f0f0f;color:#e6e6e6;">
      <table id="obs_table" style="width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;">
        <colgroup>
            <col style="width:130px;">
            <col style="width:auto;">
        </colgroup>
        <thead><tr><th style="text-align:left;padding:6px;border-bottom:1px solid #222;width:110px;">Data</th><th style="text-align:left;padding:6px;border-bottom:1px solid #222;">Observação</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <form method="POST" action="/adicionar_observacao" id="form_add_obs" style="margin-top:10px;display:flex;gap:8px;flex-direction:column;">
      <input type="hidden" name="id" id="obs_record_id" value="">
      <input type="hidden" name="registrado_em" id="registrado_em_obs" value="">
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
    // Atualização automática do painel de pendências (a cada 20s)
    const ATUALIZA_INTERVAL_MS = 20000;
    async function atualizarAtrasos() {
        try {
            const res = await fetch('/atrasos');
            if (!res.ok) return;
            const html = await res.text();
            const el = document.getElementById('mini_pendencias');
            if (el) el.innerHTML = html;
        } catch (e) {
            console.error('Erro atualizando pendências:', e);
        }
    }
    setInterval(atualizarAtrasos, ATUALIZA_INTERVAL_MS);

    function initFlatpickrBR(selector) {
        flatpickr(selector, {
            enableTime: true,
            time_24hr: true,
            dateFormat: "d/m/Y H:i",
            locale: "pt",
            theme: "light",  // Força tema claro
            // Desabilita a detecção automática de tema escuro
            onReady: function(selectedDates, dateStr, instance) {
                // Remove qualquer classe de tema escuro que possa ter sido adicionada
                instance.calendarContainer.classList.remove("flatpickr-dark");
                instance.calendarContainer.classList.add("flatpickr-light");
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        try {
            function pad(n){ return n.toString().padStart(2, '0'); }
            function formatBRDate(d){
                return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear()
                    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
            }
            document.getElementById("data_inicio").value = formatBRDate(new Date());
        } catch (e) {
            console.error('Erro ao setar data_inicio:', e);
        }
        // preencher registrado_em com data do cliente antes de enviar formulários
        try {
            var mainForm = document.getElementById('mainForm');
            if (mainForm) {
                mainForm.addEventListener('submit', function(){
                    try { document.getElementById('registrado_em_main').value = formatBRDate(new Date()); } catch(e){}
                });
            }
        } catch(e){}

        try {
            var formObs = document.getElementById('form_add_obs');
            if (formObs) {
                formObs.addEventListener('submit', function(){
                    try { document.getElementById('registrado_em_obs').value = formatBRDate(new Date()); } catch(e){}
                });
            }
        } catch(e){}

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

        initFlatpickrBR("#data_inicio");
        initFlatpickrBR("#data_retorno");
        initFlatpickrBR("#extender_data");

        atualizarAtrasos();

        try {
            toggleOutroMotivo();
            toggleOutroHardware();
            toggleEmprestimoCampos();
        } catch (e) {}
    });

    function toggleOutroMotivo() {
        const show = document.getElementById("motivo_select").value === "outros";
        document.getElementById("motivo_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("motivo_outros").required = true;
        else document.getElementById("motivo_outros").required = false;
    }

    function toggleOutroHardware() {
        const show = document.getElementById("hardware_select").value === "outros";
        document.getElementById("hardware_outros_div").style.display = show ? "block" : "none";
        if (show) document.getElementById("hardware_outros").required = true;
        else document.getElementById("hardware_outros").required = false;
    }

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

    function validarFormulario() {
        const patr = document.getElementById("patrimonio").value.trim();
        const hardware = document.getElementById("hardware_select").value;
        
        // Se não for Teclado/Mouse e o patrimônio foi preenchido, valida
        if (hardware !== "Teclado/Mouse" && patr !== "") {
            if (!/^[0-9]{7,}$/.test(patr)) {
                alert("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos.");
                return false;
            }
        }
        // Se for Teclado/Mouse, o patrimônio é opcional, mas se preenchido deve ser válido
        else if (hardware === "Teclado/Mouse" && patr !== "") {
            if (!/^[0-9]{7,}$/.test(patr)) {
                alert("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos, ou deixe em branco para Teclado/Mouse.");
                return false;
            }
        }

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
            document.querySelectorAll('.flatpickr-input').forEach(i => i.value = "");
        } catch (e) {}
    }

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
            if (typeof obs_json === 'string') {
                try { list = JSON.parse(obs_json); } catch (e) { list = []; }
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

    document.addEventListener("DOMContentLoaded", function() {
    });
</script>

<script>
    // filtro cliente + ordenação por ID (mais novo <-> mais antigo)
    function updateVisibility() {
        const q = document.getElementById("search").value.toLowerCase();
        const view = document.getElementById("view_selector").value;
        const rows = document.querySelectorAll("#tabela tbody tr");
        rows.forEach(r => {
            // base: cada row decide se cumpre a view
            const devolvido = r.getAttribute('data-devolvido') === 'true';
            const estoque = r.getAttribute('data-estoque') === 'true';
            const oculto = r.getAttribute('data-oculto') === 'true';
            const pendencia = r.getAttribute('data-pendencia') === 'true';

            let view_ok = false;
            if (view === 'ativos') {
                view_ok = (devolvido === false) && (oculto === false);
            } else if (view === 'inativos') {
                view_ok = (devolvido === true) || (estoque === true);
            } else if (view === 'estoque') {
                view_ok = (estoque === true);
            } else if (view === 'pendentes') {
                view_ok = (pendencia === true);
            } else if (view === 'legado') {
                view_ok = (oculto === false);
            } else if (view === 'tudo') {
                view_ok = true;
            }

            // search filter: se a string não aparece no texto da linha, esconder
            const text = r.innerText.toLowerCase();
            const search_ok = q === "" || text.includes(q);

            r.style.display = (view_ok && search_ok) ? "" : "none";
        });
    }

    document.getElementById("search").addEventListener("input", updateVisibility);
    document.getElementById("view_selector").addEventListener("change", updateVisibility);
    document.addEventListener("DOMContentLoaded", function () {
        const seletor = document.getElementById("view_selector");
        if (seletor) {
            seletor.dispatchEvent(new Event("change"));
        }
    });

    (function(){
        const btn = document.getElementById("btnToggleOrder");
        let desc = true;
        function sortTableById(descending) {
            const tbody = document.querySelector("#tabela tbody");
            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort((a,b) => {
                const ida = parseInt(a.dataset.id||a.getAttribute('data-id')||0,10);
                const idb = parseInt(b.dataset.id||b.getAttribute('data-id')||0,10);
                return descending ? idb - ida : ida - idb;
            });
            rows.forEach(r => tbody.appendChild(r));
        }
        btn.addEventListener("click", function(){
            desc = !desc;
            btn.textContent = desc ? "Ordem: Mais novo → antigo" : "Ordem: Mais antigo → novo";
            sortTableById(desc);
        });
        try { sortTableById(true); } catch(e){}
    })();

    // Export CSV modal logic (flatpickr date_to predefinido com hora atual do cliente)
    (function(){
        const btnOpen = document.getElementById("btnExportCsv");
        const modal = document.getElementById("modal_export");
        const btnCancel = document.getElementById("btnCancelExport");
        const form = document.getElementById("form_export");

        // inicializar flatpickr para todos os campos de data na página de lista
        try {
            flatpickr("#date_from", {
                enableTime: true,
                time_24hr: true,
                dateFormat: "d/m/Y H:i",
                locale: "pt",
                theme: "light"  // Força tema claro na página de lista também
            });
            flatpickr("#date_to", {
                enableTime: true,
                time_24hr: true,
                dateFormat: "d/m/Y H:i",
                locale: "pt",
                theme: "light"  // Força tema claro na página de lista também
            });
            // Inicializar também para o campo de estender empréstimo
            flatpickr("#extender_data", {
                enableTime: true,
                time_24hr: true,
                dateFormat: "d/m/Y H:i",
                locale: "pt",
                theme: "light"  // Força tema claro na página de lista também
            });
        } catch(e) {
            console.warn("Erro ao inicializar flatpickr:", e);
        }

        btnOpen.addEventListener("click", function(){
            modal.style.display = "flex";
            // reset manual ids hidden
            document.getElementById("manual_ids").value = "";

            // definir a data final (date_to) com a hora atual do cliente por padrão
            try {
                // Usa flatpickr para setar a data atual
                const fp = document.querySelector("#date_to")._flatpickr;
                if (fp && typeof fp.setDate === 'function') {
                    fp.setDate(new Date(), true);
                } else {
                    // fallback: setar valor do input manualmente no mesmo formato usado no flatpickr
                    function pad(n){ return n.toString().padStart(2,'0'); }
                    const d = new Date();
                    const s = pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
                    const el = document.getElementById("date_to");
                    if (el) el.value = s;
                }
            } catch(e) {
                console.warn("Não foi possível predefinir date_to:", e);
            }
        });
        btnCancel.addEventListener("click", function(){
            modal.style.display = "none";
        });

        // quando enviar, se Manual está marcado coletar os ids das linhas visíveis
        form.addEventListener("submit", function(ev){
            const manualChecked = document.getElementById("f_manual").checked;
            if (manualChecked) {
                const rows = document.querySelectorAll("#tabela tbody tr");
                const ids = [];
                rows.forEach(r => {
                    if (r.style.display !== "none") {
                        const id = r.dataset.id || r.getAttribute("data-id");
                        if (id) ids.push(id);
                    }
                });
                document.getElementById("manual_ids").value = ids.join(",");
            }
            // se "Todos" estiver checado, não precisa fazer nada — o servidor terá f_all
            // modal será fechado pelo navegador quando redirecionar p/ download
        });
    })();
</script>

</body>
</html>
"""

    page = page.replace("{total}", str(len(registros)))
    return page


# ----------------------------- SERVIDOR (HANDLERS) -----------------------------
class Servidor(BaseHTTPRequestHandler):

    def do_GET(self):
        # manter raw_path para poder ler a querystring quando necessário
        raw_path = self.path
        path = raw_path.split("?", 1)[0]
        if path == "/":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            self.responder(gerar_html_form(registros))

        elif path == "/lista":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            self.responder(gerar_pagina_lista(registros))

        elif path == "/export_csv":
            # carregar registros e aplicar filtros vindos via querystring
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            # parse query
            qs = {}
            try:
                qs = parse_qs(urlparse(self.path).query)
            except Exception:
                qs = {}

            def has(key):
                return key in qs and qs.get(key)

            # START filtering
            filtered = list(registros)

            # if 'Todos' selected -> export all (não filtra)
            if has('f_all'):
                filtered = list(registros)
            else:
                # Manual: list of ids to keep (if provided)
                if has('f_manual') and qs.get('manual_ids'):
                    ids = []
                    try:
                        ids = [int(x) for x in qs.get('manual_ids', [''])[0].split(',') if x.strip()!='']
                    except:
                        ids = []
                    filtered = [r for r in filtered if (r.get('id') is not None and int(r.get('id')) in ids)]

                # tipo filter
                if has('f_tipo') and qs.get('tipo_value'):
                    tipo_v = qs.get('tipo_value', [''])[0].strip()
                    if tipo_v:
                        filtered = [r for r in filtered if (str(r.get('tipo','')) == tipo_v)]

                # responsavel
                if has('f_responsavel') and qs.get('responsavel_value'):
                    rv = qs.get('responsavel_value', [''])[0].strip().lower()
                    if rv:
                        filtered = [r for r in filtered if (str(r.get('responsavel','')).strip().lower() == rv)]

                # emprestado_para (substring case-insensitive)
                if has('f_emprestado_para') and qs.get('emprestado_para_value'):
                    qv = qs.get('emprestado_para_value', [''])[0].strip().lower()
                    if qv:
                        filtered = [r for r in filtered if qv in str(r.get('emprestado_para','')).lower()]

                # patrimonio (substring)
                if has('f_patrimonio') and qs.get('patrimonio_value'):
                    pv = qs.get('patrimonio_value', [''])[0].strip().lower()
                    if pv:
                        filtered = [r for r in filtered if pv in str(r.get('patrimonio','')).lower()]

                # workflow (substring)
                if has('f_workflow') and qs.get('workflow_value'):
                    wv = qs.get('workflow_value', [''])[0].strip().lower()
                    if wv:
                        filtered = [r for r in filtered if wv in str(r.get('workflow','')).lower()]

                # motivo (exact match)
                if has('f_motivo') and qs.get('motivo_value'):
                    mv = qs.get('motivo_value', [''])[0].strip().lower()
                    if mv:
                        filtered = [r for r in filtered if str(r.get('motivo','')).strip().lower() == mv]

                # hardware
                if has('f_hardware') and qs.get('hardware_value'):
                    hv = qs.get('hardware_value', [''])[0].strip().lower()
                    if hv:
                        filtered = [r for r in filtered if str(r.get('hardware','')).strip().lower() == hv]

                # marca (substring)
                if has('f_marca') and qs.get('marca_value'):
                    mvv = qs.get('marca_value', [''])[0].strip().lower()
                    if mvv:
                        filtered = [r for r in filtered if mvv in str(r.get('marca','')).lower()]

                # modelo (substring)
                if has('f_modelo') and qs.get('modelo_value'):
                    modv = qs.get('modelo_value', [''])[0].strip().lower()
                    if modv:
                        filtered = [r for r in filtered if modv in str(r.get('modelo','')).lower()]

                # date range on data_inicio
                if has('f_data'):
                    from_s = qs.get('date_from', [''])[0].strip()
                    to_s = qs.get('date_to', [''])[0].strip()
                    dt_from = parse_br_datetime(from_s) if from_s else None
                    dt_to = parse_br_datetime(to_s) if to_s else None
                    if dt_from or dt_to:
                        def in_range(r):
                            di = parse_br_datetime(r.get('data_inicio',''))
                            if not di:
                                return False
                            if dt_from and di < dt_from:
                                return False
                            if dt_to and di > dt_to:
                                return False
                            return True
                        filtered = [r for r in filtered if in_range(r)]

            # campos do CSV (incluindo status)
            campos = ["id", "tipo", "responsavel", "emprestado_para", "patrimonio", "workflow", "motivo",
                      "hardware", "marca", "modelo", "data_inicio", "data_retorno", "devolvido", "estoque",
                      "status", "client_ip", "registrado_em"]

            from io import StringIO
            csv_buffer = StringIO();
            writer = csv.DictWriter(csv_buffer, fieldnames=campos)
            writer.writeheader()
            for r in filtered:
                row = {k: (r.get(k, "") if r.get(k, "") is not None else "") for k in campos 
                       if k not in ("client_ip", "registrado_em", "status")}
                oculto = r.get("oculto_meta", {}) or {}
                row["client_ip"] = oculto.get("client_ip", "")
                row["registrado_em"] = oculto.get("registrado_em", "")
                row["estoque"] = "Sim" if r.get("estoque") else "Não"
                row["devolvido"] = "Sim" if r.get("devolvido") else "Não"
                # Adiciona o status calculado
                row["status"] = calcular_status(r)
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
            # retorna o HTML do mini painel (inclui atrasos no topo)
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
            html = gerar_pendencias_html(registros)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        else:
            self.send_error(404, "Página não encontrada")

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        dados = self.rfile.read(tamanho).decode("utf-8")
        campos = parse_qs(dados)

        path = self.path
        if path == "/registrar":
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

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

            # Validação do patrimônio - obrigatório para todos EXCETO "Teclado/Mouse"
            if hardware != "Teclado/Mouse" and not patrimonio:
                return self.responder_error("Campo 'Patrimônio' é obrigatório para este hardware.")
            
            # Se for "Teclado/Mouse", o patrimônio pode ser vazio ou ter 7+ dígitos
            if patrimonio and not re.match(r'^\d{7,}$', patrimonio):
                return self.responder_error("Patrimônio inválido. Digite apenas números e no mínimo 7 dígitos.")

            workflow = campos.get("workflow", [""])[0]
            marca = campos.get("marca", [""])[0]
            modelo = campos.get("modelo", [""])[0]
            observacao = campos.get("observacao", [""])[0].strip()

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
                "estoque": False,
                "observacao": observacao,
                "observacoes": ([{
                    "text": observacao,
                    "registrado_em": (normalize_br_datetime_str(campos.get("registrado_em", [""])[0]) 
                                      or sp_now_str())
                }] if observacao else [])
             }

            if tipo == "emprestimo":
                novo["emprestado_para"] = campos.get("emprestado_para", [""])[0]
                novo["data_retorno"] = normalize_br_datetime_str(campos.get("data_retorno", [""])[0])

            try:
                client_ip = self.client_address[0] if hasattr(self, "client_address") else ""
            except:
                client_ip = ""
            if client_ip:
                novo["oculto_meta"] = {
                    "client_ip": client_ip,
                    "registrado_em": sp_now_str()
                }

            registros.append(novo)

            with open(ARQUIVO, "w", encoding="utf-8") as f:
                json.dump(registros, f, ensure_ascii=False, indent=4)

            self.redirect("/lista")

        elif path == "/retornar":
            # nova rota que implementa "Retornar máquina" com comportamento diferente conforme tipo
            try:
                id_reg = int(campos.get("id", ["0"])[0])
            except:
                id_reg = 0
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            # localizar registro original
            original = None
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        original = r
                        break
                except:
                    pass

            if not original:
                return self.responder_error("Registro não encontrado.")

            tipo_orig = original.get("tipo", "")
            # se emprestimo: mantém função antiga (marcar devolvido True)
            if tipo_orig == "emprestimo":
                updated = False
                for r in registros:
                    try:
                        if int(r.get("id", 0)) == id_reg:
                            r["devolvido"] = True
                            updated = True
                    except:
                        pass
                if updated:
                    with open(ARQUIVO, "w", encoding="utf-8") as f:
                        json.dump(registros, f, ensure_ascii=False, indent=4)
                self.redirect("/lista")
                return

            # para entrada => criar SAÍDA; para saída => criar ENTRADA
            now_str = sp_now_str()
            # gerar novo id
            maxid = 0
            for r in registros:
                try:
                    if int(r.get("id", 0)) > maxid:
                        maxid = int(r.get("id", 0))
                except:
                    pass
            novo_id = maxid + 1

            # copiar campos do original
            novo = {
                "id": novo_id,
                "tipo": "saida" if tipo_orig == "entrada" else "entrada",
                "responsavel": original.get("responsavel", ""),
                "patrimonio": original.get("patrimonio", ""),
                "workflow": original.get("workflow", ""),
                # data_inicio do novo registro = hora do clique
                "data_inicio": now_str,
                "motivo": original.get("motivo", ""),
                "hardware": original.get("hardware", ""),
                "marca": original.get("marca", ""),
                "modelo": original.get("modelo", ""),
                "devolvido": False,
                "estoque": False
            }
            # manter campos específicos de empréstimo se existirem (mas normalmente não)
            if original.get("emprestado_para"):
                novo["emprestado_para"] = original.get("emprestado_para", "")

            # se novo tipo for emprestimo (não é o caso aqui, mas mantido)
            if novo["tipo"] == "emprestimo":
                novo["data_retorno"] = original.get("data_retorno", "")

            # anexa meta oculta ao novo (client_ip/reg)
            novo["oculto_meta"] = {
                "client_ip": original.get("oculto_meta", {}).get("client_ip", ""),
                "registrado_em": sp_now_str()
            }

            # atualiza registro original: marca devolvido True, remove estoque e adiciona status_extra com novo id
            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        r["devolvido"] = True
                        r["estoque"] = False  # Removes from stock
                        r["status_extra"] = f"Devolvido (ID: {novo_id})"
                        updated = True
                        break
                except:
                    pass
            # adiciona novo registro
            registros.append(novo)

            with open(ARQUIVO, "w", encoding="utf-8") as f:
                json.dump(registros, f, ensure_ascii=False, indent=4)

            self.redirect("/lista")

        elif path == "/alternar_estoque":
            try:
                id_reg = int(campos.get("id", ["0"])[0])
            except:
                id_reg = 0
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)

            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        # Alterna o estado de estoque
                        r["estoque"] = not r.get("estoque", False)
                        updated = True
                except:
                    pass
            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

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

            self.redirect("/lista")

        elif path == "/adicionar_observacao":
            try:
                id_reg = int(campos.get("id", ["0"])[0])
            except:
                id_reg = 0
            texto = campos.get("texto", [""])[0].strip()
            # preferir data enviada pelo cliente (registrado_em); fallback para server time
            reg_raw = campos.get("registrado_em", [""])[0].strip()
            reg_norm = normalize_br_datetime_str(reg_raw) or sp_now_str()
#
            if not texto:
                return self.responder_error("Observação vazia.")
#
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                registros = json.load(f)
#
            updated = False
            for r in registros:
                try:
                    if int(r.get("id", 0)) == id_reg:
                        if "observacoes" not in r or not isinstance(r["observacoes"], list):
                            r["observacoes"] = []
                        novo = {
                            "text": texto,
                            "registrado_em": reg_norm
                        }
                        r["observacoes"].append(novo)
                        r["observacao"] = texto
                        updated = True
                except:
                    pass
            if updated:
                with open(ARQUIVO, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

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
        self.send_response(303)
        self.send_header("Location", url)
        self.end_headers()


if __name__ == "__main__":
    server_address = ('', 8000)
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    httpd = ThreadedHTTPServer(server_address, Servidor)
    print("Servidor rodando em http://localhost:8000")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()