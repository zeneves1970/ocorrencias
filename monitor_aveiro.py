import requests
import sqlite3
import time
import os
import dropbox

# --- Configurações ---
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE_PARAMS = {
    "where": """
        CSREPC='Região de Aveiro'
        OR Concelho='Oliveira de Azeméis'
        OR Concelho='Santa Maria da Feira'
        OR Concelho='Arouca'
        OR Concelho='Espinho'
    """,
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

DB_FILE = "ocorrencias_aveiro.db"
DROPBOX_PATH = "/ocorrencias_aveiro.db"

# --- Funções Dropbox ---
def baixar_db():
    token = os.environ.get("DROPBOX_REFRESH_TOKEN")
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    if not token or not app_key or not app_secret:
        raise RuntimeError("Variáveis DROPBOX_REFRESH_TOKEN, DROPBOX_APP_KEY ou DROPBOX_APP_SECRET não definidas")
    dbx = dropbox.Dropbox(oauth2_refresh_token=token, app_key=app_key, app_secret=app_secret)
    try:
        metadata, res = dbx.files_download(DROPBOX_PATH)
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

def enviar_db():
    token = os.environ.get("DROPBOX_REFRESH_TOKEN")
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    dbx = dropbox.Dropbox(oauth2_refresh_token=token, app_key=app_key, app_secret=app_secret)
    with open(DB_FILE, "rb") as f:
        dbx.files_upload(f.read(), DROPBOX_PATH, mode=dropbox.files.WriteMode.overwrite)
    print("📤 DB enviada para o Dropbox")

# --- Inicialização DB ---
baixar_db()
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()
c.execute("""
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
        (objectid, DataInicioOcorrencia, natureza, concelho, estado, operacionais, meios_terrestres, meios_aereos, data_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(objectid) DO UPDATE SET
            DataInicioOcorrencia=excluded.DataInicioOcorrencia,
            natureza=excluded.natureza,
            concelho=excluded.concelho,
            estado=excluded.estado,
            operacionais=excluded.operacionais,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos,
            data_atualizacao=CURRENT_TIMESTAMP
    """, (
        attrs['OBJECTID'],
        attrs.get('DataInicioOcorrencia', None),  # <--- NOVO campo
        attrs.get('Natureza', ''),
        attrs.get('Concelho', ''),
        attrs.get('EstadoAgrupado', ''),
        attrs.get('Operacionais', 0),
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
        attrs.get('NumeroMeiosAereosEnvolvidos', 0)
    ))
    conn.commit()

def apagar_antigas():
    c.execute("""
        DELETE FROM ocorrencias
        WHERE data_atualizacao < datetime('now', '-10 days')
    """)
    conn.commit()

def monitorizar():
    ocorrencias = obter_ocorrencias()
    for o in ocorrencias:
        attrs = o["attributes"]
        guardar_ocorrencia_sqlite(attrs)

    apagar_antigas()
    enviar_db()
    print(f"✔️ {len(ocorrencias)} ocorrências atualizadas e antigas removidas.")

# --- Executar monitorização ---
if __name__ == "__main__":
    monitorizar()
    conn.close()
