from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import dropbox
from datetime import datetime, timedelta

# --- Configurações ---
DB_FILE = "ocorrencias_aveiro.db"
DB_PATH_DROPBOX = "/ocorrencias_aveiro.db"
HIGHLIGHT_DAYS = 1  # destacar ocorrências atualizadas nas últimas 24h

app = FastAPI()

# --- Função para baixar DB do Dropbox ---
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

        # Seleciona apenas a última atualização de cada objectid
        rows = c.execute("""
    SELECT
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
""").fetchall()

        """).fetchall()

        conn.close()

        agora = datetime.utcnow()
        destaque_limite = agora - timedelta(days=HIGHLIGHT_DAYS)

        # --- Monta tabela HTML ---
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
                .recente { background-color: #fffbcc; }   /* amarelo claro */
                .despacho { background-color: #ffff99; } /* Em Despacho – amarelo */
                .curso { background-color: #ff6666; }     /* Em Curso – vermelho */
                .resolucao { background-color: #6699ff; } /* Em Resolução – azul */
                .conclusao { background-color: #99ff99; } /* Em Conclusão – verde */
            </style>
        </head>
        <body>
            <h2>Ocorrências – Distrito de Aveiro</h2>
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
            # Formata hora de início
            data_inicio = datetime.strptime(r[0], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y %H:%M")
            data_up = datetime.strptime(r[7], "%Y-%m-%d %H:%M:%S")
            classe = ""

            # Destacar recentes
            if data_up >= destaque_limite:
                classe = "recente"

            # Destacar por estado
            if r[3] == "Em Despacho":
                classe = "despacho"
            elif r[3] == "Em Curso":
                classe = "curso"
            elif r[3] == "Em Resolução":
                classe = "resolucao"
            elif r[3] == "Em Conclusão":
                classe = "conclusao"

            html += f"""
            <tr class="{classe}">
                <td>{data_inicio}</td>
                <td>{r[1]}</td>
                <td>{r[2]}</td>
                <td>{r[3]}</td>
                <td>{r[4]}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
            </tr>
            """

        html += "</table></body></html>"
        return html

    except Exception as e:
        return HTMLResponse(f"<h2>Erro ao ler DB: {e}</h2>", status_code=500)
