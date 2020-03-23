#!/usr/bin/env python3
DROUTER_VERSION="dev"
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
updater_service_logger = logging.getLogger('drouter.updaterService()')
e_collector_logger = logging.getLogger('drouter.eventCollector()')
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

logger.info("Starting DRouter")
logger.debug("DRouter version: {}".format(DROUTER_VERSION))

DROUTER_DOCKER_SOCKET="/var/run/docker.sock"
try:
    DROUTER_DOCKER_SOCKET=os.environ["DROUTER_DOCKER_SOCKET"]
    logger.debug("Set DROUTER_DOCKER_SOCKET={}".format(DROUTER_DOCKER_SOCKET))
except:
    logger.debug("DROUTER_DOCKER_SOCKET not set. Using default: {}".format(DROUTER_DOCKER_SOCKET))

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
    logger.debug("HAPROXY_CONFIG_PATH not set. Using default: {}".format(HAPROXY_CONFIG_PATH))

HAPROXY_TEMPLATE="{}/haproxy.cfg.template-http".format(HAPROXY_CONFIG_PATH)
try:
    HAPROXY_TEMPLATE = "{}".format(os.environ["HAPROXY_TEMPLATE"])
    logger.debug("Set HAPROXY_TEMPLATE={}".format(HAPROXY_TEMPLATE))
except:
    logger.debug("HAPROXY_TEMPLATE not set. Using default: {}".format(HAPROXY_TEMPLATE))

class DRouter():
    def __init__(self):
        pass

    def writeHAProxyConfigs(self, services):
        haproxy.HAPROXY_CONFIGS=HAPROXY_CONFIG_PATH
        haproxy.HAPROXY_TEMPLATE=HAPROXY_TEMPLATE
        conf = haproxy.Config()
        drouter_logger.info("Writing HAProxy configurations")
        services=conf.arrangeConfigs(services)
        for s in services:
            if len(s.upstream_servers) > 0:
                drouter_logger.debug("Writing a service {} ({})".format(s.service_name,s))
                conf.createLBConfig(s)
        conf.writeConfigs()

    def checkServices(self):
        services = []
        client = newRequest()
        for r in client.request("GET", "http://v1.40/services"):
            if r.get("Spec").get("Labels").get("drouter.host") or r.get("Spec").get("Labels").get("drouter.path"):
                services.append(r)
        return services

    def collectTasks(self):
        SERVICES=[]
        client=newRequest()
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
                            if n.get("Network").get("ID") in self.getNetworks():
                                for a in n.get("Addresses"):
                                    addr=a.split("/")[0]
                                    srv.upstream_servers.append("{}:{}".format(addr, srv.port))

            SERVICES.append(srv)
        return SERVICES
    

    def getLoadBalancerServiceID(self):
        LB_SERVICE_ID=None
        client = newRequest()
        for r in client.request("GET", "http://v1.40/services"):
            if r.get("Spec").get("Labels").get("drouter.auto_update") == "true":
                LB_SERVICE_ID=r.get("ID")
        return LB_SERVICE_ID

    def isLoadBalancer(self, service_id):
        client=newRequest()
        resp=client.request("GET", "http://v1.40/services/{}".format(service_id))
        if "drouter.auto_update" in resp.get("Spec").get("Labels").keys():
            return True
        else:
            return False

    def isDRouterService(self, service_id):
        client=newRequest()
        resp=client.request("GET", "http://v1.40/services/{}".format(service_id))
        if "drouter.host" in resp.get("Spec").get("Labels").keys():
            return True
        else:
            return False

    def updateHAProxyNetwork(self, networks=None):
        client=newRequest()
        lb_id=self.getLoadBalancerServiceID()
        resp=client.request("GET", "http://v1.40/services/{}".format(lb_id))
        try:
            version=resp["Version"]["Index"]
            if "PreviousSpec" in resp.keys():
                spec=resp.get("PreviousSpec")
            else:
                spec=resp.get("Spec")
            # meta_dates=(resp.get("CreatedAt"), resp.get("UpdatedAt"))
            # drouter_logger.debug(meta_dates)
            # replicas=spec.get("Mode").get("Replicated").get("Replicas")
            if len(networks.get("joinable_nets")) > 0:
                    drouter_logger.debug("Found new networks: {}".format(networks.get("joinable_nets")))
                    for n in networks.get("joinable_nets"):
                        net={"Target": n}
                        spec["TaskTemplate"]["Networks"].append(net)
                    drouter_logger.info("Adding loadbalancer to networks: {}".format(networks.get("joinable_nets")))
                    drouter_logger.debug(spec["TaskTemplate"]["Networks"])
            else:
                drouter_logger.info("No new networks for loadbalancer to join.")
            spec["TaskTemplate"]["ForceUpdate"] = 1
            spec["ForceUpdate"] = 1
            if "drouter.revision" in spec["Labels"]:
                spec["Labels"]["drouter.revision"] = int(spec["Labels"]["drouter.revision"])
                spec["Labels"]["drouter.revision"] += 1
                spec["Labels"]["drouter.revision"] = str(spec["Labels"]["drouter.revision"])
            else:
                spec["Labels"]["drouter.revision"] = 0
                spec["Labels"]["drouter.revision"] = str(spec["Labels"]["drouter.revision"])
            drouter_logger.debug("DRouter revision {}".format(spec["Labels"]["drouter.revision"]))
            drouter_logger.info("Restart loadbalancer")
            drouter_logger.debug(spec)
            update_status=client.request("POST", "http://v1.40/services/{}/update?version={}".format(lb_id, version), spec )
            drouter_logger.debug(update_status)
            return True
        except Exception as e:
            drouter_logger.error(str(e))
            drouter_logger.error("Could not restart HAProxy")
            return False

    # Return networks that have DRouter labeled services
    def getNetworks(self):
        services=self.checkServices()
        VIPs=[]
        for x in services:
            for net in x.get("Endpoint").get("VirtualIPs"):
                VIPs.append(net.get("NetworkID"))
        VIPs = list(dict.fromkeys(VIPs))
        return VIPs
    
    # Join loadbalancer to all new networks
    def getJoinableNetworks(self):
        # Get lb (HAProxy) service id
        lb=self.getLoadBalancerServiceID()
        # Prepare request
        client=newRequest()
        # Get lb service
        lb_srv=client.request("GET", "http://v1.40/services/{}".format(lb))
        # Create list for lb networks
        lb_networks=[]
        # collect lb networks in list
        for net in lb_srv.get("Endpoint").get("VirtualIPs"):
            lb_networks.append(net.get("NetworkID"))

        # Get list of joinable networks
        joinableNetworks=self.getNetworks()

        # Check if lb can be added to a network
        # Create final network list
        net_list=[]
        for net in joinableNetworks:
            # Append all new networks
            if net not in lb_networks:
                net_list.append(net)
        response={
            "lb_nets": lb_networks,
            "joinable_nets": net_list,
            "all_nets": list(set(lb_networks + net_list))
        }
        return response

    # Leave networks that don't have DRouter services    
    def leaveOldNetworks(self):
        pass

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

# def networkMonitor(msg_queue):
#     while True:
#         pass

# Updater service
def updaterService(msg_queue):
    while True:
        # Go easy on the CPU
        time.sleep(1)
        while not msg_queue.empty():
            msg=msg_queue.get()
            if msg == "update" or msg == "autoupdate":
                updater_service_logger.info("Starting updater service")
                if not msg == "autoupdate":
                    updater_service_logger.debug("Waiting for 5 seconds for Docker to start/stop services.")
                    time.sleep(5)
                dr=DRouter()
                updater_service_logger.info("Ready to start updating")
                dr.writeHAProxyConfigs(dr.collectTasks())
                time.sleep(1)
                dr.updateHAProxyNetwork(dr.getJoinableNetworks())
                time.sleep(1)
                updater_service_logger.debug("Clearing queue from overlapping jobs")
                msg_queue.clear()
                updater_service_logger.info("Stopping updater service")

# Updater service thread
thread_updater_service=threading.Thread(target=updaterService, args=(q,), daemon=True)

## Event collector
def eventCollector(msg_queue):
    e_collector_logger.info("Starting event collector")
    client=UnixStreamHTTPConnection(DROUTER_DOCKER_SOCKET)
    while True:
        client.request("GET", "http://v1.40/events")
        response= client.getresponse()
        while True:
            data=response.readline()
            event=json.loads(data, encoding="utf-8")
            # Go easy on the CPU
            time.sleep(1)
            action=event.get("Action")

            # Check if service has drouter labels
            if event.get("Type") == "service":
                dr=DRouter()
                if action == "create" or action == "update":
                    if dr.isDRouterService(event.get("Actor").get("ID")):
                        e_collector_logger.info("There was a change in a drouter labeled service")
                        if msg_queue.empty():
                            e_collector_logger.debug("Adding a job to queue")
                            msg_queue.put("update")
                elif action == "remove":
                    if msg_queue.empty():
                        e_collector_logger.debug("Adding a job to queue")
            if not response:
                break

try:

    thread_updater_service.start()
    eventCollector(q)
except (KeyboardInterrupt, SystemExit):
    sys.exit(0)