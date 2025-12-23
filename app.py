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

        # Seleciona ocorrências com data_atualizacao para destaque
        rows = c.execute("""
            SELECT natureza, concelho, estado,
                   operacionais, meios_terrestres, meios_aereos, data_atualizacao
            FROM ocorrencias
            GROUP BY objectid
            ORDER BY data_atualizacao DESC
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
                .resolucao { background-color: #ffd6d6; } /* vermelho claro */
                .conclusao { background-color: #d6ffd6; } /* verde claro */
            </style>
        </head>
        <body>
            <h2>Ocorrências – Distrito de Aveiro</h2>
            <table>
                <tr>
                    <th>Natureza</th>
                    <th>Concelho</th>
                    <th>Estado</th>
                    <th>Operacionais</th>
                    <th>Meios T.</th>
                    <th>Meios A.</th>
                </tr>
        """

        for r in rows:
            # r[6] = data_atualizacao
            data_up = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S")
            classe = ""

            # Destacar recentes
            if data_up >= destaque_limite:
                classe = "recente"

            # Destacar por estado
            if r[2] == "Em Resolução":
                classe = "resolucao"
            elif r[2] == "Em Conclusão":
                classe = "conclusao"

            html += f"""
            <tr class="{classe}">
                <td>{r[0]}</td>
                <td>{r[1]}</td>
                <td>{r[2]}</td>
                <td>{r[3]}</td>  <!-- Operacionais -->
                <td>{r[4]}</td>  <!-- Meios T. -->
                <td>{r[5]}</td>  <!-- Meios A. -->
            </tr>
            """

        html += "</table></body></html>"
        return html

    except Exception as e:
        return HTMLResponse(f"<h2>Erro ao ler DB: {e}</h2>", status_code=500)
