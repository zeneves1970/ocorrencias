import os
import requests

# --- Configurações ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- Função de envio ---
def enviar_telegram(mensagem):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Token ou chat_id do Telegram não definidos")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code == 200:
        print("📨 Mensagem de teste enviada ao Telegram!")
    else:
        print(f"❌ Erro ao enviar Telegram: {r.text}")

# --- Executar teste ---
if __name__ == "__main__":
    mensagem_teste = "🚨 <b>Teste de notificação</b>\nEsta é uma mensagem de teste do sistema de alertas."
    enviar_telegram(mensagem_teste)
