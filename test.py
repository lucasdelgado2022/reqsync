from auth.csrf import getcsrf  as getcsrf
from Requirements.requirementswebcalls import *
from Lifecycle.lifecyclewebservice import *
import requests


session=requests.Session()

ENO_CSRF_TOKEN=getcsrf(session)

# response,idmap=create_requirement(session,ENO_CSRF_TOKEN,["req 2","req3"],["prueba de req automatico 2","prueba de req automatico 3"])
response = revise(session,ENO_CSRF_TOKEN,["8FD603DC920B1C006AB272B100000165","8FD603DC920B1C006AB272B200000167"])

print(response.text)
# print(idmap)

