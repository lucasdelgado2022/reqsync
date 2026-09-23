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

def create_requirements(session,CSRF,titles:list[str]):
    #maximo de a 10
    URL = FullURL("/dsreq:Requirement")
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    idmap = {}
    items=[]
    for title in titles:
        items.append(
                {
                    "type":"Requirement",
                    "attributes": {
                        "title": title
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

def getconfig_requirement(session,id):
    URL = FullURL("/dsreq:Requirement/"+id)
    headers = _get_headers(security_context=SecurityContext)
    params2=params
    params2.update(
        {
            "$mask":"dsreq:RequirementPublicMask.Details"
        }
    )
    response = session.get(URL,params=params2,headers=headers)
    
        
    return response

def expand(session,CSRF,id,depth):
    URL = FullURL("/dsreq:RequirementSpecification/"+id+"/expand")
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    payload = {
        "expandDepth":depth,
        "withPath": true
    }
    response=session.post(URL,params=params,headers=headers,json=payload)
    return response
def assign_child(session,CSRF,parent,childs:list[str]):
    #maximo de a 10
    URL = FullURL("/dsreq:Requirement/"+parent+"/dsreq:SubRequirementUsage")
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    instances=[]
    for child in childs:
        instances.append(
                {
                    "referencedObject":{
                        "id":child,
                        "type":"Requirement",
                        "source": logindata.get("SPACE_URL"),
                        "relativePath":"/resources/v1/modeler/dsreq/dsreq:Requirement/"+child
                    }
                })
    

    payload = {"instances":instances}
    params2=params
    params2.update({
        "$mask":"dsreq:SubRequirementUsageMask.Filterable"}
    )
    response = session.post(URL,params=params2,headers=headers,json=payload)
        
    return response

def delete_child(session,CSRF,parent,child):
    #de a 1
    URL = FullURL("/dsreq:Requirement/"+parent+"/dsreq:SubRequirementUsage/"+child)
    headers = _get_headers(security_context=SecurityContext,eno_csrf_token=CSRF)
    
    
    response = session.delete(URL,params=params,headers=headers)
        
    return response

