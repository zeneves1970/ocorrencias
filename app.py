from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import dropbox
from datetime import datetime, timedelta
from collections import defaultdict

# --- Configurações ---
DB_FILE = "ocorrencias_aveiro.db"
DB_PATH_DROPBOX = "/ocorrencias_aveiro.db"
HIGHLIGHT_DAYS = 1  # 24h
INCLUIR_CONCELHOS = ["Aveiro", "Oliveira de Azeméis", "Santa Maria da Feira", "Arouca", "Espinho"]

app = FastAPI()

# --- Download da DB ---
def baixar_db():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )

    try:
        metadata, res = dbx.files_download(DB_PATH_DROPBOX)
        with open(DB_FILE, "wb") as f:
            f.write(res.content)
        print("📥 DB descarregada do Dropbox")
    except dropbox.exceptions.ApiError:
        print("⚠️ DB não encontrada no Dropbox. Será criada localmente")
        conn = sqlite3.connect(DB_FILE)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ocorrencias (
                objectid INTEGER PRIMARY KEY,
                DataInicioOcorrencia TEXT,
                natureza TEXT,
                concelho TEXT,
                estado TEXT,
                operacionais INTEGER,
                meios_terrestres INTEGER,
                meios_aereos INTEGER,
                data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

# --- Rota principal ---
@app.get("/", response_class=HTMLResponse)
def mostrar_tabela():
    try:
        baixar_db()
    except Exception as e:
        return HTMLResponse(f"<h2>Erro ao baixar DB: {e}</h2>", status_code=500)

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        # 🔹 Estado mais recente por ocorrência (SEM DUPLICADOS) e apenas concelhos selecionados
        placeholders = ",".join("?" for _ in INCLUIR_CONCELHOS)
        query = f"""
            SELECT
                objectid,
                DataInicioOcorrencia,
                natureza,
                concelho,
                estado,
                operacionais,
                meios_terrestres,
                meios_aereos,
                data_atualizacao
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY objectid
                           ORDER BY data_atualizacao DESC
                       ) AS rn
                FROM ocorrencias
                WHERE concelho IN ({placeholders})
            )
            WHERE rn = 1
            ORDER BY
                CASE estado
                    WHEN 'Em Despacho' THEN 1
                    WHEN 'Em Curso' THEN 2
                    WHEN 'Em Resolução' THEN 3
                    WHEN 'Em Conclusão' THEN 4
                    ELSE 5
                END,
                data_atualizacao DESC
        """
        rows = c.execute(query, INCLUIR_CONCELHOS).fetchall()

        # 🔹 Histórico completo
        hist = c.execute(f"""
            SELECT objectid, estado, operacionais, meios_terrestres, meios_aereos, data_atualizacao
            FROM ocorrencias
            WHERE concelho IN ({placeholders})
            ORDER BY data_atualizacao DESC
        """, INCLUIR_CONCELHOS).fetchall()

        conn.close()

        hist_por_id = defaultdict(list)
        for h in hist:
            hist_por_id[h[0]].append(h)

        agora = datetime.utcnow()
        destaque_limite = agora - timedelta(days=HIGHLIGHT_DAYS)

        # --- Monta HTML ---
        html = """
        <html>
        <head>
            <title>Ocorrências – Aveiro</title>
            <meta http-equiv="refresh" content="60">
            <style>
                body { font-family: Arial; }
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #ccc; padding: 6px; }
                th { background: #f2f2f2; }
                tr { cursor: pointer; }
                .despacho   { background-color: #fff3b0; }  /* amarelo */
                .curso      { background-color: #ffd6d6; }  /* vermelho */
                .resolucao  { background-color: #d6e4ff; }  /* azul */
                .conclusao  { background-color: #d6ffd6; }  /* verde */
            </style>
            <script>
                function toggleHist(id) {
                    const rows = document.querySelectorAll(".hist-" + id);
                    rows.forEach(r => {
                        r.style.display = (r.style.display === "none") ? "table-row" : "none";
                    });
                }
            </script>
        </head>
        <body>
            <h2>Ocorrências – Distrito de Aveiro e Concelhos Selecionados</h2>
            <table>
                <tr>
                    <th>Hora Início</th>
                    <th>Natureza</th>
                    <th>Concelho</th>
                    <th>Estado</th>
                    <th>Operacionais</th>
                    <th>Meios T.</th>
                    <th>Meios A.</th>
                </tr>
        """

        for r in rows:
            objectid = r[0]
            data_inicio = datetime.strptime(r[1], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y %H:%M")
            data_up = datetime.strptime(r[8], "%Y-%m-%d %H:%M:%S")

            classe = ""
            if r[4] == "Em Despacho":
                classe = "despacho"
            elif r[4] == "Em Curso":
                classe = "curso"
            elif r[4] == "Em Resolução":
                classe = "resolucao"
            elif r[4] == "Em Conclusão":
                classe = "conclusao"

       
            html += f"""
            <tr class="{classe}" onclick="toggleHist('{objectid}')">
                <td>{data_inicio}</td>
                <td>{r[2]}</td>
                <td>{r[3]}</td>
                <td>{r[4]}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
                <td>{r[7]}</td>
            </tr>
            """

            # 🔹 Histórico de alterações
            if len(hist_por_id[objectid]) > 1:
                html += f"""
                <tr class="hist-{objectid}" style="display:none; background:#fafafa;">
                    <td colspan="7">
                        <b>Histórico:</b><br>
                """
                for h in hist_por_id[objectid][1:]:
                    dh = datetime.strptime(h[5], "%Y-%m-%d %H:%M:%S").strftime("%d/%m %H:%M")
                    html += f"{dh} — {h[1]} — {h[2]} op., {h[3]} T., {h[4]} A.<br>"
                html += "</td></tr>"

        html += "</table></body></html>"
        return html

    except Exception as e:
        return HTMLResponse(f"<h2>Erro ao ler DB: {e}</h2>", status_code=500)
