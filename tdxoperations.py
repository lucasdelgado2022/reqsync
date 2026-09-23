from auth.csrf import getcsrf  as getcsrf
from Requirements.requirementswebcalls import *
from Lifecycle.lifecyclewebservice import *
import requests
import time

session=requests.Session()


ENO_CSRF_TOKEN=getcsrf(session)

def create_several_reqs(titles:list[str],contents:list[str]):
    global ENO_CSRF_TOKEN
    if not len(titles)==len(contents):
        raise Exception("Longitud de titulo y contenido no coincide, deben coincidir y corresponderse indice a indice")
    
    count=0
    titlesreq=[]
    idmap = {}
    for title in titles:
        
        if count < 10:
            titlesreq.append(title)
        else:
            response,idmap_this = create_requirements(session,ENO_CSRF_TOKEN,titlesreq)
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response,idmap_this = create_requirements(session,ENO_CSRF_TOKEN,titlesreq)
            if not response.status_code == 200:
                raise Exception("Error al subir los requerimientos",titlesreq)
            idmap.update(idmap_this)
            count=0
            titlesreq=[title]
            
        count+=1
    
    if not count==0:
        response,idmap_this = create_requirements(session,ENO_CSRF_TOKEN,titlesreq)
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response,idmap_this = create_requirements(session,ENO_CSRF_TOKEN,titlesreq)
        if not response.status_code == 200:
            raise Exception("Error al subir los requerimientos",titlesreq)
        idmap.update(idmap_this)
        count=0

    for index in range(len(titles)):
        response = edit_requirement(session,ENO_CSRF_TOKEN,idmap[titles[index]],contents[index])
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = edit_requirement(session,ENO_CSRF_TOKEN,idmap[titles[index]],contents[index])
        if not response.status_code == 200:
            raise Exception("Error al actualizar la descripcion de",titles[index])

    return idmap

def create_spec(title):
    id = create_specification(session,ENO_CSRF_TOKEN,title)
    return id

def release_serveral_reqs(ids:list[str]):
    global ENO_CSRF_TOKEN
    
    count=0
    idsreq=[]
    for id in ids:
        
        if count < 100:
            idsreq.append(id)
        else:
            response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Frozen")
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Frozen")
            if not response.status_code == 200:
                raise Exception("Error al congelar",idsreq)
            response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Release")
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Release")
            if not response.status_code == 200:
                raise Exception("Error al liberar",idsreq)      
            count=0
            idsreq=[id]
            
        count+=1
    
    if not count==0:
        response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Frozen")
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Frozen")
        if not response.status_code == 200:
            raise Exception("Error al congelar",idsreq)
        response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Release")
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = changeState(session,ENO_CSRF_TOKEN,idsreq,"Release")
        if not response.status_code == 200:
            raise Exception("Error al liberar",idsreq)      
        count=0

def revise_several_reqs(ids:list[str],changes:list[str]):
    global ENO_CSRF_TOKEN
    
    count=0
    idsreq=[]
    revisionmap={}
    for id in ids:
        
        if count < 100:
            idsreq.append(id)
        else:
            response = revise(session,ENO_CSRF_TOKEN,idsreq)
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = revise(session,ENO_CSRF_TOKEN,idsreq)
            if not response.status_code == 200:
                raise Exception("Error al congelar",idsreq)
            for item in response.json().get("results"):
                revisionmap.update({item.get("derivedFrom"):item.get("id")})   
            count=0
            idsreq=[id]
            
        count+=1
    
    if not count==0:
        response = revise(session,ENO_CSRF_TOKEN,idsreq)
        print(response.text)
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = revise(session,ENO_CSRF_TOKEN,idsreq)
        if not response.status_code == 200:
            raise Exception("Error al congelar",idsreq)     
        for item in response.json().get("results"):
            revisionmap.update({item.get("derivedFrom"):item.get("id")})   
        count=0

    for index,id in enumerate(ids):
        if changes[index] is not None:
            response = edit_requirement(session,ENO_CSRF_TOKEN,revisionmap[id],changes[index])
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = edit_requirement(session,ENO_CSRF_TOKEN,revisionmap[id],changes[index])
            if not response.status_code == 200:
                raise Exception("Error al actualizar la descripcion de",ids[index])


    return revisionmap

def relate_several_elements(parents:list[str],childslists:list[list[str]]):
    global ENO_CSRF_TOKEN
    if not len(parents)==len(childslists):
        raise Exception("no coinicde la cantidad de padres, y listas de hijos")
    idmap={}
    for index, parent in enumerate(parents):
        count=0
        child2inst = {}
        for child in childslists[index]:
            response = assign_child(session,ENO_CSRF_TOKEN,parent,[child])
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = assign_child(session,ENO_CSRF_TOKEN,parent,[child])
            if not response.status_code == 200:
                raise Exception("Error al asignar subrequerimientos",child)
            child2inst.update({child:response.json().get("member","")[0].get("id","")})
        idmap.update({parent:child2inst})
    
    return idmap   

def relate_several_elements_spec(parents:list[str],childslists:list[list[str]]):
    global ENO_CSRF_TOKEN
    if not len(parents)==len(childslists):
        raise Exception("no coinicde la cantidad de padres, y listas de hijos")
    idmap={}
    for index, parent in enumerate(parents):
        count=0
        child2inst = {}
        for child in childslists[index]:
            response = assign_child_spec(session,ENO_CSRF_TOKEN,parent,[child])
            if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
                ENO_CSRF_TOKEN=getcsrf(session)
                response = assign_child_spec(session,ENO_CSRF_TOKEN,parent,[child])
            if not response.status_code == 200:
                raise Exception("Error al asignar subrequerimientos",child)
            child2inst.update({child:response.json().get("member","")[0].get("id","")})
        idmap.update({parent:child2inst})
    
    return idmap                
       

def delete_several_relations(parents:list[str],relids:list[str]):
    global ENO_CSRF_TOKEN
    if not len(parents)==len(relids):
        raise Exception("Longitud de padres y relaciones no coinciden")
    
    for index in range(len(parents)):
        response=delete_child(session,ENO_CSRF_TOKEN,parents[index],relids[index])
        print(response.text)
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = delete_child(session,ENO_CSRF_TOKEN,idsreq)
        if not response.status_code == 200:
            raise Exception("Error al eliminar relaciones",parents[index],relids[index])

def delete_several_relations_spec(parents:list[str],relids:list[str]):
    global ENO_CSRF_TOKEN
    if not len(parents)==len(relids):
        raise Exception("Longitud de padres y relaciones no coinciden")
    
    for index in range(len(parents)):
        response=delete_child_spec(session,ENO_CSRF_TOKEN,parents[index],relids[index])
        print(response.text)
        if not response.status_code == 200 and "ENO_CSRF_TOKEN" in response.json().get("message",""):
            ENO_CSRF_TOKEN=getcsrf(session)
            response = delete_child_spec(session,ENO_CSRF_TOKEN,parents[index],relids[index])
        if not response.status_code == 200:
            raise Exception("Error al eliminar relaciones",parents[index],relids[index])
    
    
def get_parent_structure(specificationid: str) -> dict[tuple[str, str], dict[str, str]]:
    """
    Queries 3DX for the given parent's active children using the expand endpoint.
    Returns a dictionary mapping (parent_3dx_id, child_3dx_id) to connection info:
    {
        ("parent_id", "child_id"): {
            "connectionID": "connection_3dx_id",
            "type": "req-req"  # or "spec-req"
        }
    }
    """
    global ENO_CSRF_TOKEN
    time.sleep(80)
    response = expand(session, ENO_CSRF_TOKEN, specificationid, 10)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching structure: {response.text}")
        
    members = response.json().get("member", [])
    
    # Identify the types based on your usage logic
    SpecificationUsages = {m.get("id") for m in members if m.get("type") == "Specification Structure"}
    SubRequirementUsages = {m.get("id") for m in members if m.get("type") == "Sub Requirement"}
    Paths = [m.get("Path") for m in members if m.get("Path")]
    
    tree_map = {}
    
    for path in Paths:
        for index, item_id in enumerate(path):
            if item_id in SpecificationUsages or item_id in SubRequirementUsages:
                # In 3DX, the connection object is between the parent and the child
                parent_id = path[index - 1]
                child_id = path[index + 1]
                
                if item_id in SpecificationUsages:
                    conn_type = "spec-req"
                else:
                    conn_type = "req-req"
                    
                tree_map[(parent_id, child_id)] = {
                    "connectionID": item_id,
                    "type": conn_type
                }

    return tree_map