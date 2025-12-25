from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import dropbox
from datetime import datetime

# --- Configurações ---
DB_FILE = "ocorrencias_aveiro.db"
DB_PATH_DROPBOX = "/ocorrencias_aveiro.db"

INCLUIR_CONCELHOS = [
    "Aveiro",
    "Albergaria-a-Velha",
    "Águeda",
    "Ílhavo",
    "Estarreja",
    "Murtosa",
    "Sever do Vouga",
    "Ovar",
    "Oliveira do Bairro",
    "Anadia",
    "São João da Madeira",
    "Castelo de Paiva",
    "Oliveira de Azeméis",
    "Santa Maria da Feira",
    "Arouca",
    "Vale de Cambra",
    "Espinho"
]

app = FastAPI()

# --- Download da DB ---
def baixar_db():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )

    metadata, res = dbx.files_download(DB_PATH_DROPBOX)
    with open(DB_FILE, "wb") as f:
        f.write(res.content)

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

        placeholders = ",".join("?" for _ in INCLUIR_CONCELHOS)

        rows = c.execute(f"""
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
                           PARTITION BY DataInicioOcorrencia, natureza, concelho
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
        """, INCLUIR_CONCELHOS).fetchall()

        conn.close()

        # --- HTML ---
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

                .despacho   { background-color: #ffff00; }
                .curso      { background-color: #ff0000; }
                .resolucao  { background-color: #1e90ff; }
                .conclusao  { background-color: #32cd32; }
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
            data_inicio = datetime.strptime(
                r[0], "%Y-%m-%dT%H:%M:%S"
            ).strftime("%d/%m/%Y %H:%M")

            estado = r[3]
            classe = {
                "Em Despacho": "despacho",
                "Em Curso": "curso",
                "Em Resolução": "resolucao",
                "Em Conclusão": "conclusao",
            }.get(estado, "")

            html += f"""
            <tr class="{classe}">
                <td>{data_inicio}</td>
                <td>{r[1]}</td>
                <td>{r[2]}</td>
                <td>{estado}</td>
                <td>{r[4]}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
            </tr>
            """

        html += "</table></body></html>"
        return html

    except Exception as e:
        return HTMLResponse(f"<h2>Erro ao ler DB: {e}</h2>", status_code=500)
