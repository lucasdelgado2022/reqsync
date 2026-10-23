from urllib.parse import quote
import os
import sys
import re
import requests
from auth.login import get_safe_2fa_code, getlogdata



def login(session):
    
    passport_lt, login_cookies = get_login_ticket(session)
    cas_auth(passport_lt, login_cookies,username,password,session)
    csrf = log_3dspace(session)
    return csrf

def get_login_ticket(session): #login ticket web services
    lt_url = f"{passport_url}/login?action=get_auth_params"
    response = session.get(lt_url)
    if response.status_code == 200:
        passport_lt = (response.json()).get("lt")
        passport_cookie = response.cookies
        return passport_lt, passport_cookie
    else:
        sys.exit(0)

def cas_auth(passport_lt, login_cookies,username,password,session): #authenticacion cas web service
    cas_auth_url=f"{passport_url}/login"
    url2 = f"{passport_url}/login/totp"
    data = {
        "lt": passport_lt,
        "username": username,
        "password": password,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
     }
    
    response = session.post(cas_auth_url, data=data)
    csrf_token_value = re.search(
        r'configData\.csrfTokenValue\s*=\s*["\']([^"\']*)["\']', response.text
    ).group(1)
    csrf_token_name = re.search(
        r'configData\.csrfTokenName\s*=\s*["\']([^"\']*)["\']', response.text
    ).group(1)

    
    data = {
        "data[code]": get_safe_2fa_code(),
        csrf_token_name: csrf_token_value
        
    }
    
    response = session.post(url2, data=data)

def log_3dspace(session):
    
    SpaceLoginURL=f"{space_url}/resources/v1/application/CSRF/?tenant={tenant}"
    SpaceLoginURL = quote(SpaceLoginURL)
    PassportloginURL = f"{passport_url}/login?service={SpaceLoginURL}"
    response = session.get(PassportloginURL)
    if response.status_code == 200:
        try:
            csrf = response.json()["csrf"]["value"]
            session.get(
                space_url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            return csrf
        except:
            sys.exit(0)
    else:
        sys.exit(0)

def logout(cookies):
    logouturl=f"{passport_url}/logout"
    requests.get(logouturl,cookies=cookies)
    







config = getlogdata()
passport_url = config['PASSPORT_URL']
space_url = config['SPACE_URL']
tenant = config['TENANT']
seccontext = config['SECURITY_CONTEXT']
username = config['DASSAULT_USERNAME']
password = config['DASSAULT_PASSWORD']


