
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
    response=session.get(URL,auth=(Agent_id, Agent_secret))
    print(response.status_code,response.text)
    if response.status_code == 200:
        try:
            ENO_CSRF_TOKEN = response.json()["csrf"]["value"]
        except:
            print("La respuesta no tiene contenid, raw csrf response",response.text)
    else:
        print("Codigo de respuesta",response.status_code)
        print("Error en la respuesta al obtener el CSRF")
        print("Raw response:",response.text)
    return ENO_CSRF_TOKEN

