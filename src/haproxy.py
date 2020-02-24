#!/usr/bin/env python3

HAPROXY_CONFIGS="./"

LB_CONFIG_FRONTEND_HOST="""
	acl host_{server_name_formatted} hdr(host) -i {server_name}"""
LB_CONFIG_FRONTEND_ACL_PATH="""
	acl {upstream_name}_path path_beg -i {server_path}"""
LB_CONFIG_FRONTEND_TO_BACKEND="""
	use_backend {upstream_name} if host_{server_name_formatted} {upstream_name}_path"""

LB_CONFIG_BACKEND="""

backend {upstream_name}
	# Stick on source
	stick-table type ip size 5000k expire 10m store conn_cur
	stick on src
    # Backends"""

LB_CONFIG_BACKEND_SERVER="""
    server {upstream_name}_{id} {upstream_server} {ssl} cookie c_{upstream_name}_{id}"""

LB_CONFIG_BACKEND_CUT_PATH="""
    http-request replace-path ^([^\\ ]*\\ /){server_path_without_slash}[/]?(.*)     \\1\\2"""

LB_CONFIG_SSL_VERIFY_NONE="ssl verify none"
LB_CONFIG_SSL="ssl"

COMMENT="""
# Reverse proxy configurations are automatically generated under this line. Do not modify them by hand.
# 
# Tip: Use labels for Docker services instead.
#      For example: drouter.host="www.domain.com" drouter.path="/backend"
"""

class Files():
    def __init__(self):
        pass
    def write(self, filepath, data):
        try:
            f=open(filepath, "a")
            f.write(data)
            f.close()
            return True
        except:
            return False

    def overwrite(self, filepath, data):
        try:
            f=open(filepath, "w")
            f.write(data)
            f.close()
            return True
        except:
            return False
    def read(self, filepath):
        try:
            f=open(filepath, "r")
            data=f.read()
            f.close()
            return data
        except:
            return False

class Service():
    def __init__(self, service_id, service_name, upstream_servers, domain, path, port, ssl=None, cut_path=None):
        self.id=service_id
        self.service_name=service_name
        self.upstream_servers=upstream_servers
        self.domain=domain
        self.haproxy_host=self.domain.replace(".", "_")
        self.path=path
        self.port=port
        self.ssl=None
        if ssl == "noverify":
            self.ssl=LB_CONFIG_SSL_VERIFY_NONE
        elif ssl == "verify":
            self.ssl=LB_CONFIG_SSL
        elif ssl == None:
            self.ssl=""
        self.cut_path=None
        if not cut_path == None:
            self.cut_path = self.path.replace("/", "")

class Config():
    def __init__(self):
        self.domains={}
    
    def arrangeConfigs(self, services):
        import operator
        # arranged_list=[]
        services.sort(key=operator.attrgetter("path"), reverse=True)
        return services
    
    def createLBConfig(self, srv):

        frontend_host=LB_CONFIG_FRONTEND_HOST.format(server_name_formatted=srv.haproxy_host, server_name=srv.domain)
        frontend_acl_path=LB_CONFIG_FRONTEND_ACL_PATH.format(upstream_name=srv.service_name, server_path=srv.path)
        frontend_to_backend=LB_CONFIG_FRONTEND_TO_BACKEND.format(upstream_name=srv.service_name, server_name_formatted=srv.haproxy_host)


        def createBackendConfigs():
            backend_configs=[]
            backend=LB_CONFIG_BACKEND.format(upstream_name=srv.service_name)
            backend_configs.append(backend)
            if not srv.cut_path == None:
                cut_path_conf = LB_CONFIG_BACKEND_CUT_PATH.format(server_path_without_slash=srv.cut_path)
                backend_configs.append(cut_path_conf)
            for s in srv.upstream_servers:
                server=LB_CONFIG_BACKEND_SERVER.format(upstream_name=srv.service_name, id=srv.upstream_servers.index(s), upstream_server=s, ssl=srv.ssl)
                backend_configs.append(server)
            return backend_configs

        try:
            if self.domains[srv.domain]:
                self.domains[srv.domain]["frontend_acl_path"].append(frontend_acl_path)
                self.domains[srv.domain]["frontend_to_backend"].append(frontend_to_backend)
                self.domains[srv.domain]["backend_configs"].append(createBackendConfigs())
        except:
                self.domains[srv.domain] = {
                    "frontend_host": frontend_host
                }
                self.domains[srv.domain]["frontend_acl_path"] = []
                self.domains[srv.domain]["frontend_acl_path"].append(frontend_acl_path)
                self.domains[srv.domain]["frontend_to_backend"] = []
                self.domains[srv.domain]["frontend_to_backend"].append(frontend_to_backend)
                self.domains[srv.domain]["backend_configs"] = []
                self.domains[srv.domain]["backend_configs"].append(createBackendConfigs())

    def writeConfigs(self):
        files=Files()
        FPATH="{}/haproxy.cfg".format(HAPROXY_CONFIGS)
        files.overwrite(FPATH, COMMENT)
        files.write(FPATH, files.read("{}/haproxy.cfg.template-http".format(HAPROXY_CONFIGS)))
        data=""
        for x in self.domains:
            data=data+self.domains[x].get("frontend_host")
            for path in self.domains[x].get("frontend_acl_path"):
                data=data+path
            for clause in self.domains[x].get("frontend_to_backend"):
                data=data+clause
        
        for x in self.domains:
            for backend in self.domains[x].get("backend_configs"):
                for l in backend:
                    data=data+l
        files.write(FPATH, data)
# ## Testing
if __name__=="__main__":
    print(LB_CONFIG_BACKEND_CUT_PATH)