import requests
import sqlite3
import time
import os
import dropbox
import json
from datetime import datetime

# ==================================================
# CONFIGURAÇÕES
# ==================================================
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

BASE_PARAMS = {
    "where": """
        CSREPC='Região de Aveiro'
        OR Concelho='Oliveira de Azeméis'
        OR Concelho='Santa Maria da Feira'
        OR Concelho='Arouca'
        OR Concelho='Espinho'
        OR Concelho='Castelo de Paiva'
        OR Concelho='São João da Madeira'
        OR Concelho='Vale de Cambra'
    """,
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

DB_FILE = "ocorrencias_aveiro.db"
DROPBOX_DB_PATH = "/ocorrencias_aveiro.db"
DROPBOX_JSON_PATH = "/ocorrencias.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

INTERVALO = 300  # 5 minutos

# ==================================================
# TELEGRAM
# ==================================================
def enviar_telegram(mensagem: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("📨 Alerta enviado")
        else:
            print(f"❌ Erro Telegram: {r.text}")
    except Exception as e:
        print(f"⚠️ Falha Telegram: {e}")

# ==================================================
# DROPBOX
# ==================================================
def dropbox_client():
    return dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )

def baixar_db():
    try:
        dbx = dropbox_client()
        metadata, res = dbx.files_download(DROPBOX_DB_PATH)
        with open(DB_FILE, "wb") as f:
            f.write(res.content)
        print("📥 DB descarregada do Dropbox")
    except:
        print("ℹ️ DB ainda não existe no Dropbox")

def enviar_db():
    dbx = dropbox_client()
    with open(DB_FILE, "rb") as f:
        dbx.files_upload(
            f.read(),
            DROPBOX_DB_PATH,
            mode=dropbox.files.WriteMode.overwrite
        )
    print("📤 DB enviada para o Dropbox")

def enviar_json():
    dbx = dropbox_client()
    with open("ocorrencias.json", "rb") as f:
        dbx.files_upload(
            f.read(),
            DROPBOX_JSON_PATH,
            mode=dropbox.files.WriteMode.overwrite
        )
    print("📤 JSON enviado para o Dropbox")

# ==================================================
# BASE DE DADOS
# ==================================================
baixar_db()

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
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

c.execute("""
CREATE TABLE IF NOT EXISTS notificadas (
    fingerprint TEXT PRIMARY KEY
)
""")

conn.commit()

# ==================================================
# API PROCIV
# ==================================================
def obter_ocorrencias():
    ocorrencias = []
    offset = 0

    while True:
        params = BASE_PARAMS.copy()
        params["resultOffset"] = offset

        r = requests.get(URL, params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()

        data = r.json()
        features = data.get("features", [])

        if not features:
            break

        ocorrencias.extend(features)
        offset += len(features)
        time.sleep(0.5)

    return ocorrencias

# ==================================================
# PROCESSAMENTO
# ==================================================
def guardar_ocorrencia(attrs):
    objectid = attrs["OBJECTID"]
    data_inicio = attrs.get("DataInicioOcorrencia", "")
    concelho = attrs.get("Concelho", "")
    natureza = attrs.get("Natureza", "")

    fingerprint = f"{data_inicio}|{concelho}|{natureza}"

    ja_notificada = c.execute(
        "SELECT 1 FROM notificadas WHERE fingerprint=?",
        (fingerprint,)
    ).fetchone()

    c.execute("""
        INSERT INTO ocorrencias
        (objectid, DataInicioOcorrencia, natureza, concelho, estado,
         operacionais, meios_terrestres, meios_aereos, data_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(objectid) DO UPDATE SET
            estado=excluded.estado,
            operacionais=excluded.operacionais,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos,
            data_atualizacao=CURRENT_TIMESTAMP
    """, (
        objectid,
        data_inicio,
        natureza,
        concelho,
        attrs.get("EstadoAgrupado", ""),
        attrs.get("Operacionais", 0),
        attrs.get("NumeroMeiosTerrestresEnvolvidos", 0),
        attrs.get("NumeroMeiosAereosEnvolvidos", 0),
    ))

    if not ja_notificada:
        mensagem = (
            "🚨 <b>Nova ocorrência</b>\n\n"
            f"🕒 {data_inicio.replace('T',' ')}\n"
            f"📍 {concelho}\n"
            f"🔥 {natureza}\n"
            f"📊 Estado: {attrs.get('EstadoAgrupado','')}\n"
            f"👨‍🚒 Operacionais: {attrs.get('Operacionais',0)}\n"
            f"🚒 Meios T.: {attrs.get('NumeroMeiosTerrestresEnvolvidos',0)}\n"
            f"🚁 Meios A.: {attrs.get('NumeroMeiosAereosEnvolvidos',0)}"
        )
        enviar_telegram(mensagem)
        c.execute(
            "INSERT INTO notificadas (fingerprint) VALUES (?)",
            (fingerprint,)
        )

    conn.commit()

def apagar_antigas():
    c.execute("""
        DELETE FROM ocorrencias
        WHERE data_atualizacao < datetime('now', '-10 days')
    """)
    conn.commit()

# ==================================================
# GERAR JSON PARA O SITE
# ==================================================
def gerar_json():
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
                       PARTITION BY DataInicioOcorrencia, natureza, concelho
                       ORDER BY data_atualizacao DESC
                   ) AS rn
            FROM ocorrencias
        )
        WHERE rn = 1
        ORDER BY datetime(DataInicioOcorrencia) DESC
    """).fetchall()

    data = []
    for r in rows:
        data.append({
            "data_inicio": r[0],
            "natureza": r[1],
            "concelho": r[2],
            "estado": r[3],
            "operacionais": r[4],
            "meios_terrestres": r[5],
            "meios_aereos": r[6],
            "atualizado": r[7]
        })

    with open("ocorrencias.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    enviar_json()

# ==================================================
# LOOP PRINCIPAL
# ==================================================
def monitorizar():
    ocorrencias = obter_ocorrencias()

    for o in ocorrencias:
        guardar_ocorrencia(o["attributes"])

    apagar_antigas()
    enviar_db()
    gerar_json()

    print(f"✔️ {len(ocorrencias)} ocorrências processadas")

if __name__ == "__main__":
    print("🚀 Monitor Aveiro iniciado")

    while True:
        try:
            monitorizar()
        except Exception as e:
            print(f"❌ Erro crítico: {e}")

        time.sleep(INTERVALO)
