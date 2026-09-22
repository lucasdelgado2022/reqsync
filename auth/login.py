import os
from dotenv import load_dotenv

load_dotenv()
def getlogdata():
    logdata  ={
    "AGENTID": os.getenv("AGENTID"),
    "AGENTSECRET": os.getenv("AGENTSECRET"),
    "PASSPORT_URL": os.getenv("PASSPORT_URL"),
    "SPACE_URL": os.getenv("SPACE_URL"),
    "TENANT":os.getenv("TENANT"),
    "SECURITY_CONTEXT":os.getenv("SECURITY_CONTEXT")
    }
    return logdata