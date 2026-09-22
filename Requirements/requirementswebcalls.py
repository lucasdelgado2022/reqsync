import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)
from auth.login import getlogdata
logindata=getlogdata()

BaseURL = logindata.get("SPACE_URL") + '/resources/v1/modeler/dsreq'
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

def create_requirement(session,CSRF,title:list[str],content:list[str]):
    URL = FullURL("/dsreq:Requirement")
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    idmap = {}
    items=[]
    for index in range(len(title)):
        items.append(
                {
                    "type":"Requirement",
                    "attributes": {
                        "title": title[index],
                        "description": content[index]
                    }
                })
    

    payload = {"items":items}
    response = session.post(URL,params=params,headers=headers,json=payload)
    for result in response.json().get("member",""):
        idmap.update({
            result.get("title",""):result.get("id","")
        })
        
    return response,idmap


def edit_requirement(session,CSRF,id,content):
    URL = FullURL("/dsreq:Requirement/"+id)
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    payload = {"contentData":content}
    response = session.patch(URL,params=params,headers=headers,json=payload)
    
        
    return response