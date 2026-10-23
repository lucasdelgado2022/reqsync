import os
from dotenv import load_dotenv, dotenv_values
from auth.passport_auth import generate_2fa_code
import time
load_dotenv()

def getlogdata():
    return dict(dotenv_values())

def get_safe_2fa_code():
    """
    Verifica el tiempo de vida del código TOTP actual. 
    Si está por expirar (menos de 5 segundos), espera al siguiente ciclo.
    """
    # Obtenemos el tiempo actual en segundos
    current_time = int(time.time())
    
    # Calculamos cuántos segundos quedan en la ventana actual de 30 segundos
    remaining_time = 30 - (current_time % 30)
    
    # Si quedan menos de 5 segundos, es demasiado arriesgado enviarlo
    if remaining_time < 5:
        print(f"[AUTH] ⏳ El código 2FA expira en {remaining_time}s. Esperando un código fresco...")
        # Esperamos el tiempo restante + 1 segundo de margen para asegurar que rotó
        time.sleep(remaining_time + 1)
        print("[AUTH] 🔄 Nuevo ciclo 2FA iniciado.")
    
    # Ahora sí, llamamos a tu script generador original de forma segura
    return generate_2fa_code()