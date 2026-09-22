from auth.csrf import getcsrf  as getcsrf
from Requirements.requirementswebcalls import *
from Lifecycle.lifecyclewebservice import *
import requests


session=requests.Session()

ENO_CSRF_TOKEN=getcsrf(session)

# response,idmap=create_requirement(session,ENO_CSRF_TOKEN,["req 2","req3"],["prueba de req automatico 2","prueba de req automatico 3"])
# response,idmap = create_requirement(session,ENO_CSRF_TOKEN,["req test 1","req test 2"])
# print(response.text)

# response = edit_requirement(session,ENO_CSRF_TOKEN,idmap["req test 1"],"Descripcion de requisito 1")
response = delete_child(session,ENO_CSRF_TOKEN,"A6D79EDF1E9213006AB283B7000001ED","8FD603DC920B1C006AB289C600003546")
# response = get_requirement_data(session,"A6D79EDF1E9213006AB283B7000001ED")
print(response.text)