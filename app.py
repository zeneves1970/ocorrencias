from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import dropbox

# --- Configurações ---
DB_FILE = "ocorrencias_aveiro.db"
DB_PATH_DROPBOX = "/ocorrencias_aveiro.db"

app = FastAPI()

# --- Função para baixar DB do Dropbox ---
def baixar_db():
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        raise RuntimeError("DROPBOX_TOKEN não definido")

    dbx = dropbox.Dropbox(token)

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
                meios_terrestres INTEGER,
                meios_aereos INTEGER,
                operacionais INTEGER,
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

        # Seleciona apenas uma ocorrência por objectid
        rows = c.execute("""
            SELECT natureza, concelho, estado,
                   operacionais, meios_terrestres, meios_aereos
            FROM ocorrencias
            GROUP BY objectid
            ORDER BY concelho
        """).fetchall()

        conn.close()

        # --- Monta a tabela HTML com auto-refresh ---
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
            html += f"""
            <tr>
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

