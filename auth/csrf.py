
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
    try:
        ENO_CSRF_TOKEN = response.json()["csrf"]["value"]
    except:
        raise Exception("Error getting the CSRF token")
    
    return ENO_CSRF_TOKEN

