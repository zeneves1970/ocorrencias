import requests
import sqlite3
import time
import os
import dropbox

# --- Configurações ---
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE_PARAMS = {
    "where": "CSREPC='Região de Aveiro'",
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

DB_FILE = "ocorrencias_aveiro.db"
DROPBOX_PATH = "/ocorrencias_aveiro.db"

# --- Funções Dropbox ---
def baixar_db():
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        raise RuntimeError("DROPBOX_TOKEN não definido")
    dbx = dropbox.Dropbox(token)
    try:
        metadata, res = dbx.files_download(DROPBOX_PATH)
        with open(DB_FILE, "wb") as f:
            f.write(res.content)
        print("📥 DB descarregada do Dropbox")
    except dropbox.exceptions.ApiError:
        print("DB não encontrada no Dropbox, será criada localmente")
        conn = sqlite3.connect(DB_FILE)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ocorrencias (
                objectid INTEGER PRIMARY KEY,
                natureza TEXT,
                concelho TEXT,
                estado TEXT,
                meios_terrestres INTEGER,
                meios_aereos INTEGER,
                operacionais INTEGER
            )
        """)
        conn.commit()
        conn.close()

def enviar_db():
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        raise RuntimeError("DROPBOX_TOKEN não definido")
    dbx = dropbox.Dropbox(token)
    with open(DB_FILE, "rb") as f:
        dbx.files_upload(f.read(), DROPBOX_PATH, mode=dropbox.files.WriteMode.overwrite)
    print("📤 DB enviada para o Dropbox")

# --- SQLite ---
baixar_db()
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS ocorrencias (
    objectid INTEGER PRIMARY KEY,
    natureza TEXT,
    concelho TEXT,
    estado TEXT,
    meios_terrestres INTEGER,
    meios_aereos INTEGER,
    operacionais INTEGER
)
""")
conn.commit()

# --- Funções principais ---
def obter_ocorrencias():
    ocorrencias = []
    offset = 0
    while True:
        params = BASE_PARAMS.copy()
        params["resultOffset"] = offset
        r = requests.get(URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
        if not features:
            break
        ocorrencias.extend(features)
        offset += len(features)
        time.sleep(0.5)
    return ocorrencias

def guardar_ocorrencia_sqlite(attrs):
    c.execute("""
        INSERT INTO ocorrencias
        (objectid, natureza, concelho, estado, meios_terrestres, meios_aereos, operacionais)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(objectid) DO UPDATE SET
            natureza=excluded.natureza,
            concelho=excluded.concelho,
            estado=excluded.estado,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos,
            operacionais=excluded.operacionais
    """, (
        attrs['OBJECTID'],
        attrs.get('Natureza', ''),
        attrs.get('Concelho', ''),
        attrs.get('EstadoAgrupado', ''),
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
        attrs.get('NumeroMeiosAereosEnvolvidos', 0),
        attrs.get('Operacionais', 0)
    ))
    conn.commit()

def monitorizar():
    ocorrencias = obter_ocorrencias()
    for o in ocorrencias:
        attrs = o["attributes"]
        guardar_ocorrencia_sqlite(attrs)
    enviar_db()
    print(f"✔️ {len(ocorrencias)} ocorrências atualizadas.")

# --- Executar monitorização ---
if __name__ == "__main__":
    monitorizar()
    conn.close()
