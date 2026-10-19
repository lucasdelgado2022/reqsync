
from auth.login import getlogdata
logindata=getlogdata()

BaseURL = logindata.get("SPACE_URL")
SecurityContext = logindata.get("SECURITY_CONTEXT")
Tenant = logindata.get("TENANT")
Agent_id=logindata.get("AGENTID")
Agent_secret=logindata.get("AGENTSECRET")

def FullURL(path):
    URL = BaseURL + path
    return URL


def getcsrf(session):
    URL = FullURL("/resources/v1/application/CSRF")

    if not BaseURL or not Agent_id or not Agent_secret:
        return None

    response = session.get(URL, auth=(Agent_id, Agent_secret), timeout=30)
    if response.status_code == 200:
        try:
            payload = response.json()
            token = payload.get("csrf", {}).get("value")
            if token:
                return token
            token = payload.get("value")
            if token:
                return token
        except ValueError:
            print("La respuesta no tiene contenido válido, raw csrf response", response.text)
    else:
        print("Codigo de respuesta", response.status_code)
        print("Error en la respuesta al obtener el CSRF")
        print("Raw response:", response.text)
    return None

