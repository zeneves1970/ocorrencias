import requests
import sqlite3
import os

# --- Configurações ---
DB_FILE = "ocorrencias_aveiro.db"
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"

BASE_PARAMS = {
    "where": "CSREPC='Região de Aveiro'",
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

# --- Obter feed atual ---
r = requests.get(URL, params=BASE_PARAMS)
r.raise_for_status()
data = r.json()

print("📡 ObjectIDs atuais no feed da Proteção Civil:")
for feature in data["features"]:
    attrs = feature["attributes"]
    print(f"{attrs['OBJECTID']} | {attrs.get('DataInicioOcorrencia')} | {attrs.get('EstadoAgrupado')}")

# --- Verificar DB ---
if not os.path.exists(DB_FILE):
    print("\n⚠️ Base de dados não encontrada:", DB_FILE)
else:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    print("\n💾 ObjectIDs guardados na tabela 'notificadas':")
    rows = c.execute("SELECT objectid FROM notificadas").fetchall()
    db_objectids = [r[0] for r in rows]
    print(db_objectids if db_objectids else "Nenhum objectid guardado ainda.")

    # --- Comparar feed vs DB ---
    feed_objectids = [feature["attributes"]["OBJECTID"] for feature in data["features"]]
    novos_alertas = [oid for oid in feed_objectids if oid not in db_objectids]

    print("\n🚨 ObjectIDs que seriam novos alertas:")
    print(novos_alertas if novos_alertas else "Nenhum novo alerta.")

    conn.close()

