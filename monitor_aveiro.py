import requests
import sqlite3
import time
import os
import dropbox
import json
import subprocess
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
DROPBOX_PATH = "/ocorrencias_aveiro.db"

# GitHub: diretório do repositório clonado localmente na VM
GITHUB_REPO_DIR = "/caminho/para/repositorio/ocorrencias-aveiro"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

INTERVALO = 300  # segundos (5 minutos)

# ==================================================
# FUNÇÕES AUXILIARES
# ==================================================
def enviar_telegram(mensagem: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("📨 Alerta enviado para o Telegram")
        else:
            print(f"❌ Erro Telegram: {r.text}")
    except Exception as e:
        print(f"⚠️ Falha Telegram: {e}")

def dropbox_client():
    return dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )

def baixar_db():
    for tentativa in range(3):
        try:
            dbx = dropbox_client()
            metadata, res = dbx.files_download(DROPBOX_PATH)
            with open(DB_FILE, "wb") as f:
                f.write(res.content)
            print("📥 DB descarregada do Dropbox")
            return
        except dropbox.exceptions.ApiError:
            print("⚠️ DB não existe no Dropbox — será criada localmente")
            return
        except Exception as e:
            print(f"⚠️ Dropbox download erro ({tentativa+1}/3): {e}")
            time.sleep(5)

def enviar_db():
    for tentativa in range(3):
        try:
            dbx = dropbox_client()
            with open(DB_FILE, "rb") as f:
                dbx.files_upload(f.read(), DROPBOX_PATH, mode=dropbox.files.WriteMode.overwrite)
            print("📤 DB enviada para o Dropbox")
            return
        except Exception as e:
            print(f"⚠️ Dropbox upload erro ({tentativa+1}/3): {e}")
            time.sleep(5)

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
    estado = attrs.get("EstadoAgrupado","")
    operacionais = attrs.get("Operacionais",0)
    meios_terrestres = attrs.get("NumeroMeiosTerrestresEnvolvidos",0)
    meios_aereos = attrs.get("NumeroMeiosAereosEnvolvidos",0)

    fingerprint = f"{data_inicio}|{concelho}|{natureza}"

    ja_notificada = c.execute(
        "SELECT 1 FROM notificadas WHERE fingerprint=?",
        (fingerprint,)
    ).fetchone()

    # 🔒 marca logo como notificada antes de enviar alerta
    if not ja_notificada:
        c.execute(
            "INSERT OR IGNORE INTO notificadas (fingerprint) VALUES (?)",
            (fingerprint,)
        )
        conn.commit()

        mensagem = (
            f"🚨 <b>Nova ocorrência</b>\n\n"
            f"🕒 {data_inicio.replace('T',' ')}\n"
            f"📍 {concelho}\n"
            f"🔥 {natureza}\n"
            f"📊 Estado: {estado}\n"
            f"👨‍🚒 Operacionais: {operacionais}\n"
            f"🚒 Meios T.: {meios_terrestres}\n"
            f"🚁 Meios A.: {meios_aereos}"
        )
        enviar_telegram(mensagem)

    # Atualiza tabela de ocorrências
    c.execute("""
        INSERT INTO ocorrencias (
            objectid, DataInicioOcorrencia, natureza, concelho, estado, operacionais, meios_terrestres, meios_aereos
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(objectid) DO UPDATE SET
            DataInicioOcorrencia=excluded.DataInicioOcorrencia,
            natureza=excluded.natureza,
            concelho=excluded.concelho,
            estado=excluded.estado,
            operacionais=excluded.operacionais,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos
    """, (objectid, data_inicio, natureza, concelho, estado, operacionais, meios_terrestres, meios_aereos))

    conn.commit()

# ==================================================
# GERAR JSON E PUSH PARA GITHUB
# ==================================================
def gerar_json_e_push():
    c.execute("SELECT * FROM ocorrencias ORDER BY DataInicioOcorrencia DESC")
    rows = c.fetchall()
    keys = ["objectid","data_inicio","natureza","concelho","estado","operacionais","meios","meios_a","data_atualizacao"]
    data = []
    for row in rows:
        # Mapear colunas corretamente
        data.append({
            "objectid": row[0],
            "data_inicio": row[1],
            "natureza": row[2],
            "concelho": row[3],
            "estado": row[4],
            "operacionais": row[5],
            "meios": row[6],
            "meios_a": row[7],
            "data_atualizacao": row[8]
        })

    # Guardar JSON local
    json_path = os.path.join(GITHUB_REPO_DIR, "ocorrencias.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Commit e push automático
    try:
        subprocess.run(["git", "-C", GITHUB_REPO_DIR, "add", "ocorrencias.json"], check=True)
        subprocess.run(["git", "-C", GITHUB_REPO_DIR, "commit", "-m", "Atualização automática de ocorrências"], check=True)
        subprocess.run(["git", "-C", GITHUB_REPO_DIR, "push"], check=True)
        print("📤 JSON enviado para GitHub Pages")
    except subprocess.CalledProcessError:
        print("⚠️ Sem alterações para commit ou erro no push")

# ==================================================
# MONITORIZAR
# ==================================================
def monitorizar():
    ocorrencias = obter_ocorrencias()
    for f in ocorrencias:
        guardar_ocorrencia(f["attributes"])
    enviar_db()              # Dropbox
    gerar_json_e_push()      # GitHub Pages

# ==================================================
# LOOP PRINCIPAL
# ==================================================
if __name__ == "__main__":
    print("🚀 Monitor Aveiro iniciado")
    while True:
        try:
            monitorizar()
        except Exception as e:
            print(f"❌ Erro crítico: {e}")
        time.sleep(INTERVALO)
