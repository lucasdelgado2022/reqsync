import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)
from auth.login import getlogdata
logindata=getlogdata()

BaseURL = logindata.get("SPACE_URL") + '/resources/v1/modeler/dslc'
SecurityContext = logindata.get("SECURITY_CONTEXT")
Tenant = logindata.get("TENANT")
Agent_id=logindata.get("AGENTID")
Agent_secret=logindata.get("AGENTSECRET")

def FullURL(path):
    URL = BaseURL + path
    return URL

params = {
    "tenant":Tenant
}

def _get_headers(security_context=None, accept_language=None, eno_csrf_token=None):
    headers = {}
    ctx = security_context if security_context is not None else globals().get("SecurityContext")
    if ctx:
        headers["SecurityContext"] = ctx
    if accept_language:
        headers["Accept-Language"] = accept_language
    if eno_csrf_token:
        headers["ENO_CSRF_TOKEN"] = eno_csrf_token
    return headers

def getNextStates(session,CSRF,id):
    URL = FullURL("/maturity/getNextStates")
    headers=_get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    payload= {
        "data": [
            {
                "id":id,
                "identifier":id,
                "type":"Requirement",
                "source": logindata.get("SPACE_URL"),
                "relativePath":"/resources/v1/modeler/dsreq/dsreq:Requirement/"+id
            }
        ]
    }
    response = session.post(URL,headers=headers,params=params,json=payload)
    return response

def revise(session,CSRF,ids:list[str]):
    #maximo 100
    URL = FullURL("/version/create")
    headers=_get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    data = []
    for id in ids:
        data.append(
            {
                "id":id,
                "identifier":id,
                "type":"Requirement",
                "source": logindata.get("SPACE_URL"),
                "relativePath":"/resources/v1/modeler/dsreq/dsreq:Requirement/"+id
            })
    payload = {
        "edgeType": "Revision",
        "data":data
    }
    params2=params
    params2.update({
        "$include":"instances"
    })
    response = session.post(URL,headers=headers,params=params2,json=payload)
    return response

def changeState(session,CSRF,ids:list[str],nextstate):
    #maximo 100
    URL = FullURL("/maturity/changeState")
    headers=_get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    data = []
    for id in ids:
        data.append(
            {
                "id":id,
                "identifier":id,
                "type":"Requirement",
                "source": logindata.get("SPACE_URL"),
                "relativePath":"/resources/v1/modeler/dsreq/dsreq:Requirement/"+id,
                "nextState":nextstate
            })
    payload = {
        "data":data
    }
    response = session.post(URL,headers=headers,params=params,json=payload)
    return response