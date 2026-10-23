import os
from dotenv import load_dotenv
import pyotp


load_dotenv()

# Load the TOTP secret from the .env file
totp_secret = os.getenv("TOTP_SECRET")

if not totp_secret:
    raise RuntimeError("TOTP_SECRET is not set in the environment")

def generate_2fa_code():
    totp = pyotp.TOTP(totp_secret)
    return totp.now()

