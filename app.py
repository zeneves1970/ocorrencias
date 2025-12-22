from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import dropbox

# --- Dropbox ---
DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")
DB_PATH_LOCAL = "ocorrencias_aveiro.db"
DB_PATH_DROPBOX = "/Apps/monitor-aveiro-db/ocorrencias_aveiro.db"

def baixar_db():
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    with open(DB_PATH_LOCAL, "wb") as f:
        metadata, res = dbx.files_download(DB_PATH_DROPBOX)
        f.write(res.content)

# --- FastAPI ---
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def mostrar_tabela():
    baixar_db()

    conn = sqlite3.connect(DB_PATH_LOCAL)
    c = conn.cursor()

    rows = c.execute("""
        SELECT natureza, concelho, estado,
               meios_terrestres, meios_aereos, operacionais
        FROM ocorrencias
        ORDER BY concelho
    """).fetchall()

    conn.close()

    html = """
    <html>
    <head>
        <title>Ocorrências – Aveiro</title>
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
                <th>Meios T.</th>
                <th>Meios A.</th>
                <th>Operacionais</th>
            </tr>
    """

    for r in rows:
        html += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td>{r[5]}</td>
        </tr>
        """

    html += "</table></body></html>"
    return html
