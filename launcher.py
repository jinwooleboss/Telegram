import os
import sys
import time
import subprocess
import atexit

BOT_FILE = "bot.py"
RESTART_DELAY = 5


# Garde le CPU éveillé dans Termux
try:
    subprocess.run(
        ["termux-wake-lock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("🔋 Wake Lock activé")
except Exception:
    pass


# Libère le Wake Lock à l'arrêt
def cleanup():
    try:
        subprocess.run(
            ["termux-wake-unlock"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


atexit.register(cleanup)


print("🚀 Lanceur démarré")

while True:
    print(f"▶️ Démarrage de {BOT_FILE}...")

    try:
        process = subprocess.run(
            [sys.executable, BOT_FILE],
            cwd=os.path.dirname(os.path.abspath(__file__))
        )

        print(
            f"⚠️ {BOT_FILE} s'est arrêté "
            f"(code {process.returncode})"
        )

    except KeyboardInterrupt:
        print("\n🛑 Arrêt manuel.")
        break

    except Exception as e:
        print(f"❌ Erreur du lanceur : {e}")

    print(f"🔄 Redémarrage dans {RESTART_DELAY} secondes...")
    time.sleep(RESTART_DELAY)