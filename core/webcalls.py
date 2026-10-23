import os
import requests

def revgraph(id,csrf,space_cookies): #permite obtener el titulo del ensamble o parte padre
    serviceURL=f"{space_url}/resources/v1/modeler/dslc/version/getGraph"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ENO_CSRF_TOKEN": csrf
    }
    params = {
        "tenant": tenant,
    }
    
    data='{"data":[{"id": "'+id+'"}]}'
    response=requests.post(serviceURL,data=data,headers=headers,params=params,cookies=space_cookies)
    
    return response

def release(id,csrf,space_cookies): #permite obtener el titulo del ensamble o parte padre
    serviceURL=f"{space_url}/resources/v1/modeler/dslc/maturity/changeState"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ENO_CSRF_TOKEN": csrf
    }
    params = {
        "tenant": tenant,
    }
    
    data='{"data":[{"id": "'+id+'","nextState":"RELEASED"}]}'
    response=requests.post(serviceURL,data=data,headers=headers,params=params,cookies=space_cookies)
    
    return response

def unlock(instanceid,csrf,space_cookies):
    serviceURL=f"{space_url}/resources/v1/modeler/dslc/reservation/unreserve"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ENO_CSRF_TOKEN": csrf
    }
    params = {
        "tenant": tenant,
    }
    
    data='{"data":[{"id": "'+instanceid+'","identifier": "'+instanceid+'","type":"VPMInstance"}]}'
    print(data)
    response=requests.post(serviceURL,data=data,headers=headers,params=params,cookies=space_cookies)
    
    return response

def engitem(id,space_cookies): #permite obtener el titulo del ensamble o parte padre
    serviceURL=f"{space_url}/resources/v1/modeler/dseng/dseng:EngItem/{id}"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {
        "tenant": tenant,
        "$mask":"dsmveng:EngItemMask.Details"
    }
    
    
    response=requests.get(serviceURL,headers=headers,params=params,cookies=space_cookies)
    
    return response


def parent(id,csrf,space_cookies): #permite obtener el id de los ensambles padre, para los embibidos es uno solo
    serviceURL=f"{space_url}/resources/v1/modeler/dseng/dseng:EngItem/locate"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ENO_CSRF_TOKEN": csrf
    }
    params = {
        "tenant": tenant,
        "$nextPage": ""
    }
    payload = '{"referencedObjects":[{"source":"'+space_url+'","type":"dseng:EngItem","identifier":"'+id+'","relativePath":"/resources/v1/modeler/dseng/dseng:EngItem/'+id+'"}],"navigateTo":["dseng:EngItem"]}'

    jsoned=[]
    response=requests.post(serviceURL,headers=headers,params=params,cookies=space_cookies,data=payload)
    jsoned.append(response.json())
    nresponses=1
    while response.status_code==207:
        params = {
            "tenant": tenant,
            "$nextPage": response.json()["nextPage"]
        }
        response=requests.post(serviceURL,headers=headers,params=params,cookies=space_cookies,data=payload)
        jsoned.append(response.json())
        nresponses+=1
    return jsoned,nresponses

def replace(instanceid,parentid,newid,iname,idescrp,csrf,space_cookies): #permite obtener el id de los ensambles padre, para los embibidos es uno solo
    serviceURL=f"{space_url}/resources/v1/modeler/dseng/dseng:EngItem/{parentid}/dseng:EngInstance/{instanceid}/replace"
    headers = {
        "SecurityContext": seccontext,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ENO_CSRF_TOKEN": csrf
    }
    params = {
        "tenant": tenant,
    }
    payload = '{"referencedObject":{"source":"'+space_url+'","type":"dseng:EngItem","identifier":"'+newid+'","relativePath":"/resources/v1/modeler/dseng/dseng:EngItem/'+newid+'"},"attributes":{"name":"'+ iname +'","description":"'+idescrp+'"}}'
    

    response=requests.post(serviceURL,headers=headers,params=params,cookies=space_cookies,data=payload)
    
    return response


path_config= os.path.dirname(os.path.abspath(__file__)) + '/configuration/config.txt'
with open(path_config, 'r') as file:
    config = {}
    for line in file:
        key, value = line.strip().split('=')
        config[key] = value



passport_url = config['PASSPORT_URL']
space_url = config['SPACE_URL']
tenant = config['TENANT']
seccontext = config['SECURITYCONTEXT']

