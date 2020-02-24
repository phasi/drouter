#!/usr/bin/env python3
DROUTER_VERSION="0.1-beta"
import socket
import http.client
import sys
import json
import time
import haproxy
import os
import threading
import queue
import logging

# Create loggers
logger = logging.getLogger('drouter.main')
updater_service_logger = logging.getLogger('drouter.updaterService')
e_collector_logger = logging.getLogger('drouter.eventCollector')
drouter_logger = logging.getLogger('drouter.DRouter()')

# Set default loglevel
DROUTER_LOGLEVEL="INFO"
# Try to read loglevel from ENVIRONMENT
try:
    DROUTER_LOGLEVEL=os.environ["DROUTER_LOGLEVEL"]
except:
    pass
# Finally set loglevel based on either the default or the environment var.
finally:
    if DROUTER_LOGLEVEL == "INFO":
        LOGLEVEL=logging.INFO
    elif DROUTER_LOGLEVEL == "DEBUG":
        LOGLEVEL=logging.DEBUG
    elif DROUTER_LOGLEVEL == "WARNING":
        LOGLEVEL=logging.WARNING
    elif DROUTER_LOGLEVEL == "ERROR":
        LOGLEVEL=logging.ERROR
    elif DROUTER_LOGLEVEL == "FATAL":
        LOGLEVEL=logging.FATAL
    
# Set loggers loglevels
logger.setLevel(LOGLEVEL)
updater_service_logger.setLevel(LOGLEVEL)
e_collector_logger.setLevel(LOGLEVEL)
drouter_logger.setLevel(LOGLEVEL)

# create console log handler and set its level
ch = logging.StreamHandler()
ch.setLevel(LOGLEVEL)
# create log formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# add formatter to console handler
ch.setFormatter(formatter)

# add console handler to loggers
logger.addHandler(ch)
updater_service_logger.addHandler(ch)
e_collector_logger.addHandler(ch)
drouter_logger.addHandler(ch)

#### START PROGRAM ####

logger.info("Starting DRouter Daemon")
logger.debug("DRouter version: {}".format(DROUTER_VERSION))

DROUTER_DOCKER_SOCKET="/var/run/docker.sock"
try:
    DROUTER_DOCKER_SOCKET=os.environ["DROUTER_DOCKER_SOCKET"]
    logger.debug("Set DROUTER_DOCKER_SOCKET={}".format(DROUTER_DOCKER_SOCKET))
except:
    logger.debug("DROUTER_DOCKER_SOCKET is set to default -> {} (If you want to change this set DROUTER_DOCKER_SOCKET as an environment variable".format(DROUTER_DOCKER_SOCKET))

class UnixStreamHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
        self.sock.connect(self.host)

class newRequest():
    
    def __init__(self):
        pass
    
    def request(self, method, url, body=None):
        client=UnixStreamHTTPConnection(DROUTER_DOCKER_SOCKET)
        if method == "GET":
            client.request(method, url)
        elif method == "POST":
            headers={"Content-Type": "application/json"}
            client.request(method, url, bytes(json.dumps(body), "utf-8"), headers)
        try:
            response = json.loads(client.getresponse().read())
            client.close()
            return response
        except json.JSONDecodeError:
            return True
        except:
            return False



# Determine HAProxy config path
HAPROXY_CONFIG_PATH = "../haproxy"
try:
    HAPROXY_CONFIG_PATH = os.environ["HAPROXY_CONFIG_PATH"]
    logger.debug("Set HAPROXY_CONFIG_PATH={}".format(HAPROXY_CONFIG_PATH))
except:
    logger.debug("HAPROXY_CONFIG_PATH is set to default -> {} (If you want to change this set HAPROXY_CONFIG_PATH as an environment variable".format(HAPROXY_CONFIG_PATH))

HAPROXY_TEMPLATE="{}/haproxy.cfg.template-http".format(HAPROXY_CONFIG_PATH)
try:
    HAPROXY_TEMPLATE = "{}".format(os.environ["HAPROXY_TEMPLATE"])
    logger.debug("Set HAPROXY_TEMPLATE={}".format(HAPROXY_TEMPLATE))
except:
    logger.debug("HAPROXY_TEMPLATE is set to default -> {} (If you want to change this set HAPROXY_TEMPLATE as an environment variable".format(HAPROXY_TEMPLATE))

# Determine network for the containers
DROUTER_DOCKER_VNET = "loadbalancer"
try:
    DROUTER_DOCKER_VNET = os.environ["DROUTER_DOCKER_VNET"]
    logger.debug("Set DROUTER_DOCKER_VNET={}".format(DROUTER_DOCKER_VNET))
except:
    logger.debug("DROUTER_DOCKER_VNET is set to default -> {} (If you want to change this set DROUTER_DOCKER_VNET as an environment variable".format(DROUTER_DOCKER_VNET))
DROUTER_DOCKER_VNET_ID = None
try:
    DROUTER_DOCKER_VNET_ID = os.environ["DROUTER_DOCKER_VNET_ID"]
except:
    pass
VNET = None
if DROUTER_DOCKER_VNET_ID:
    VNET = DROUTER_DOCKER_VNET_ID
else:
    client=newRequest()
    for net in client.request("GET", "http://v1.40/networks"):
        if net.get("Name") == DROUTER_DOCKER_VNET:
            VNET = net.get("Id")

class DRouter():
    def __init__(self):
        pass

    def writeHAProxyConfigs(self, services):
        haproxy.HAPROXY_CONFIGS=HAPROXY_CONFIG_PATH
        haproxy.HAPROXY_TEMPLATE=HAPROXY_TEMPLATE
        conf = haproxy.Config()
        drouter_logger.debug("Writing HAProxy configurations")
        services=conf.arrangeConfigs(services)
        for s in services:
            if len(s.upstream_servers) > 0:
                conf.createLBConfig(s)
        conf.writeConfigs()

    def checkServices(self):
        services = []
        client = newRequest()
        drouter_logger.debug("Checking docker swarm services with labels 'drouter.host'")
        for r in client.request("GET", "http://v1.40/services"):
            if r.get("Spec").get("Labels").get("drouter.host") or r.get("Spec").get("Labels").get("drouter.path"):
                services.append(r)
        return services

    def collectTasks(self):
        SERVICES=[]
        client=newRequest()
        drouter_logger.debug("Getting docker swarm tasks")
        tasks=client.request("GET", "http://v1.40/tasks")
        services=self.checkServices()
        for s in services:
            ssl=None
            try:
                ssl=s.get("Spec").get("Labels").get("drouter.ssl")
            except:
                pass
            cut_path=None
            try:
                cut_path=s.get("Spec").get("Labels").get("drouter.cut_path")
            except:
                pass
            srv=haproxy.Service(service_id=s.get("ID"), service_name=s.get("Spec").get("Name"), upstream_servers=[], domain=s.get("Spec").get("Labels").get("drouter.host"), path=(s.get("Spec").get("Labels").get("drouter.path") or "/"), port=80, ssl=ssl, cut_path=cut_path)
            if len(s.get("Endpoint").get("Ports")) == 1:
                srv.port = s.get("Endpoint").get("Ports")[0].get("TargetPort")
            else:
                srv.port = s.get("Spec").get("Labels").get("drouter.port") or 80

            for t in tasks:
                if t.get("ServiceID") == srv.id:
                    if t.get("Status").get("State") == "running" or t.get("Status").get("State") == "starting":
                        for n in t.get("NetworksAttachments"):
                            if n.get("Network").get("Spec").get("Name") == DROUTER_DOCKER_VNET:
                                for a in n.get("Addresses"):
                                    addr=a.split("/")[0]
                                    srv.upstream_servers.append("{}:{}".format(addr, srv.port))

            SERVICES.append(srv)
        return SERVICES

    def getLoadBalancerServiceID(self):
        LB_SERVICE_ID=None
        client = newRequest()
        drouter_logger.debug("Getting HAProxy service id")
        for r in client.request("GET", "http://v1.40/services"):
            if r.get("Spec").get("Labels").get("drouter.auto_update") == "true":
                LB_SERVICE_ID=r.get("ID")
        drouter_logger.debug("HAProxy docker service id: {}".format(LB_SERVICE_ID))
        return LB_SERVICE_ID
    
    def IsLoadBalancer(self, container_id):
        client=newRequest()
        resp=client.request("GET", "http://v1.40/containers/{}/json".format(container_id))
        try:
            if resp.get("Config").get("Labels").get("com.docker.swarm.service.id") == self.getLoadBalancerServiceID():
                return True
            else:
                return False
        except:
            drouter_logger.warning("Could not check if the service that joined was the load balancer.")
            return None


    def updateHAProxy(self):
        client=newRequest()
        lb_id=self.getLoadBalancerServiceID()
        resp=client.request("GET", "http://v1.40/services/{}".format(lb_id))
        try:
            version=resp["Version"]["Index"]
            resp["Spec"]["TaskTemplate"]["ForceUpdate"] = 1
            resp["Spec"]["ForceUpdate"] = 1
            drouter_logger.debug("Updating HAProxy docker service")
            spec=resp.get("Spec")
            if resp.get("PreviousSpec"):
                spec = resp.get("PreviousSpec")
            return client.request("POST", "http://v1.40/services/{}/update?version={}".format(lb_id, version), spec )
        except:
            drouter_logger.error("Could not update HAProxy docker service")
            return False


##### SERVICES #####

# Extend queue to clearable queue
class ClearableQueue(queue.Queue):

    def clear(self):
        try:
            while True:
                self.get_nowait()
        except queue.Empty:
            pass

# Create new queue
q=ClearableQueue()

# Updater service
def updaterService(msg_queue):
    while True:
        while not msg_queue.empty():
            msg=msg_queue.get()
            if msg == "update" or msg == "autoupdate":
                updater_service_logger.info("Starting updater service")
                if not msg == "autoupdate":
                    updater_service_logger.debug("Waiting for 15 seconds for Docker to start/stop services.")
                    time.sleep(15)
                dr=DRouter()
                time.sleep(1)
                dr.writeHAProxyConfigs(dr.collectTasks())
                time.sleep(1)
                docker_response=dr.updateHAProxy()
                updater_service_logger.debug("Docker response: {}".format(docker_response))
                time.sleep(1)
                updater_service_logger.debug("Clearing queue from overlapping jobs")
                msg_queue.clear()
                updater_service_logger.info("Stopping updater service")

# Updater service thread
thread_updater_service=threading.Thread(target=updaterService, args=(q,), daemon=True)

## Event collector
def eventCollector(msg_queue):
    client=UnixStreamHTTPConnection(DROUTER_DOCKER_SOCKET)
    while True:
        client.request("GET", "http://v1.40/events")
        response= client.getresponse()
        while True:
            data=response.readline()
            event=json.loads(data, encoding="utf-8")
            action=event.get("Action")
            # Check network
            if event.get("Type") == "network":
                if event.get("Actor").get("Attributes").get("name") == DROUTER_DOCKER_VNET:
                    e_collector_logger.info("There was a change in the network '{}'".format(DROUTER_DOCKER_VNET))
                    e_collector_logger.debug(event)
                    dr=DRouter()
                    is_lb=dr.IsLoadBalancer(event.get("Actor").get("Attributes").get("container"))
                    if is_lb == True or is_lb == None:
                        if not action == "connect":
                            e_collector_logger.info("Loadbalancer (HAProxy) disconnects from the network")
                        else:
                            e_collector_logger.info("Loadbalancer (HAProxy) joins/rejoins the network")
                    else:
                        if msg_queue.empty():
                            e_collector_logger.debug("Adding a job to the queue")
                            msg_queue.put("update")
            if not response:
                break

try:

    thread_updater_service.start()
    eventCollector(q)
except (KeyboardInterrupt, SystemExit):
    sys.exit(0)
