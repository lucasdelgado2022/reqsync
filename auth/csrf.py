
from auth.login import getlogdata
from auth.auth import login
logindata=getlogdata()

BaseURL = logindata.get("SPACE_URL")
SecurityContext = logindata.get("SECURITY_CONTEXT")
Tenant = logindata.get("TENANT")
username=logindata.get("DASSAULT_USERNAME")
password=logindata.get("DASSAULT_PASSWORD")


def FullURL(path):
    URL = BaseURL + path
    return URL


def getcsrf(session):

    csrf = login(session)
    return csrf

