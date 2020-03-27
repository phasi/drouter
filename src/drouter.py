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
scheduler_logger = logging.getLogger('drouter.schedulerService()')
md_collector_logger = logging.getLogger('drouter.swarmMetadataCollectorService()')
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
scheduler_logger.setLevel(LOGLEVEL)
md_collector_logger.setLevel(LOGLEVEL)

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
scheduler_logger.addHandler(ch)
md_collector_logger.addHandler(ch)
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

class DockerClient():
    
    def __init__(self, DROUTER_DOCKER_SOCKET):
        self.docker_socket=DROUTER_DOCKER_SOCKET
    
    def request(self, method, url, body=None):
        client=UnixStreamHTTPConnection(self.docker_socket)
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

    def getServices(self):
        return self.request("GET", "http://v1.40/services")

    def getTasks(self):
        return self.request("GET", "http://v1.40/tasks")

    def getNetworks(self):
        return self.request("GET", "http://v1.40/networks")



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

# Check if stats enabled
DROUTER_STATS=False
try:
    if "DROUTER_STATS" in os.environ.keys():
        DROUTER_STATS=True
    else:
        pass
except:
    pass

class DRouter():
    def __init__(self, data):
        self.data=data
        self.d_services=data["services"]
        self.d_tasks=data["tasks"]
        self.d_networks=data["networks"]

    def writeHAProxyConfigs(self, services):
        haproxy.HAPROXY_CONFIGS=HAPROXY_CONFIG_PATH
        haproxy.HAPROXY_TEMPLATE=HAPROXY_TEMPLATE
        conf = haproxy.Config()
        services=conf.arrangeConfigs(services)
        for s in services:
            if len(s.upstream_servers) > 0:
                # drouter_logger.debug("Writing a service {} ({})".format(s.service_name,s))
                conf.createLBConfig(s)
        conf.writeConfigs()

    def checkServices(self):
        services = []
        for r in self.d_services:
            if r.get("Spec").get("Labels").get("drouter.host") or r.get("Spec").get("Labels").get("drouter.path"):
                services.append(r)
        return services

    def collectLabels(self, services):
        SERVICES=[]
        tasks=self.d_tasks
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
        for r in self.d_services:
            if r.get("Spec").get("Labels").get("drouter.auto_update") == "true":
                LB_SERVICE_ID=r.get("ID")
        return LB_SERVICE_ID
    
    def getLoadBalancer(self, service_id):
        for r in self.d_services:
            if r.get("ID") == self.getLoadBalancerServiceID():
                return r

    def isLoadBalancer(self, service_id):
        for x in self.d_services:
            if x.get("ID") == service_id:
                if "drouter.auto_update" in x.get("Spec").get("Labels").keys():
                    return True
        return False

    def isDRouterService(self, service_id):
        for x in self.d_services:
            if x.get("ID") == service_id:
                if "drouter.host" in x.get("Spec").get("Labels").keys():
                    return True
        return False

    def updateHAProxyNetwork(self, networks=None):
        client=DockerClient(DROUTER_DOCKER_SOCKET)
        lb=self.getLoadBalancer(self.getLoadBalancerServiceID())
        try:
            version=lb["Version"]["Index"]
            spec=lb.get("Spec")
            if len(networks.get("joinable_nets")) > 0:
                drouter_logger.debug("Found new networks: {}".format(networks.get("joinable_nets")))
                spec["TaskTemplate"]["Networks"]=[]
                for n in networks.get("all_nets"):
                    net={"Target": n}
                    spec["TaskTemplate"]["Networks"].append(net)
                drouter_logger.info("Adding loadbalancer to networks: {}".format(networks.get("joinable_nets")))
            else:
                drouter_logger.info("No new networks for loadbalancer to join.")
                # if "PreviousSpec" in lb.keys():
                #     spec=lb.get("PreviousSpec")
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
            update_status=client.request("POST", "http://v1.40/services/{}/update?version={}".format(self.getLoadBalancerServiceID(), version), spec )
            drouter_logger.debug(update_status)
            return True
        except Exception as e:
            drouter_logger.error(str(e))
            drouter_logger.error("Could not restart HAProxy")
            return False


    def getNetworkID(self, name):
        for net in self.d_networks:
            if net.get("Name") == name:
                return net.get("Id")

    # Return networks that have DRouter labeled services
    def getNetworks(self):
        services=self.d_services
        VIPs=[]
        for x in services:
            for net in x.get("Endpoint").get("VirtualIPs"):
                VIPs.append(net.get("NetworkID"))
        VIPs = list(dict.fromkeys(VIPs))
        return VIPs
    
    # Join loadbalancer to all new networks
    def getJoinableNetworks(self):
        # Get docker ingress network id
        ingress=self.getNetworkID("ingress")
        # Get lb service
        lb_srv=self.getLoadBalancer(self.getLoadBalancerServiceID())
        # Create list for lb networks
        lb_networks=[]
        # collect lb networks in list
        for net in lb_srv.get("Endpoint").get("VirtualIPs"):
            if net.get("NetworkID") != ingress:
                lb_networks.append(net.get("NetworkID"))

        # Get list of joinable networks
        joinableNetworks=self.getNetworks()

        # Check if lb can be added to a network
        # Create final network list
        net_list=[]
        for net in joinableNetworks:
            # Append all new networks
            if net not in lb_networks:
                if net != ingress:
                    net_list.append(net)
        response={
            "lb_nets": lb_networks,
            "joinable_nets": net_list,
            "all_nets": list(set(lb_networks + net_list))
        }
        return response


##### SERVICES #####

# Extend queue to clearable queue
class ClearableQueue(queue.Queue):

    def clear(self):
        try:
            while True:
                self.get_nowait()
        except queue.Empty:
            pass

# Create queues
q_scheduler_msg=ClearableQueue()
q_event=ClearableQueue()
q_md_collector=ClearableQueue()
q_metadata=ClearableQueue()
q_updater=ClearableQueue()

# Initialize stats counter
STATSCOUNTER=10

# Swarm Metadata Collector Service
# Keeps swarm metadata updated, controls getting the metadata instead of all functions getting same data separately and repeatedly!!
def swarmMetadataCollectorService(q_md_collector, q_metadata, q_updater, q_scheduler_msg):
    STATS_COUNTER=STATSCOUNTER
    COOLDOWN=10
    def updateData():
        md_collector_logger.info("Downloading Docker metadata")
        data={}
        dc=DockerClient(DROUTER_DOCKER_SOCKET)
        data["services"]=dc.getServices()
        data["tasks"]=dc.getTasks()
        data["networks"]=dc.getNetworks()
        return data
    METADATA_DOWNLOADS=0
    DATA_REQ=False
    CHECKABLE_EVENT={}
    while True:
        if (DATA_REQ and COOLDOWN == 0):
            data=updateData()
            dr=DRouter(data)
            if "Actor" in CHECKABLE_EVENT.keys():
                ID=CHECKABLE_EVENT.get("Actor").get("ID")
                IS_ACCEPTED=dr.isDRouterService(ID)
                if IS_ACCEPTED:
                    md_collector_logger.debug("Labels accepted.")
                    q_metadata.put(data)
                else:
                    DATA_REQ=False
            METADATA_DOWNLOADS +=1
            if COOLDOWN == 0 and IS_ACCEPTED:
                q_updater.put("")
                DATA_REQ=False
        time.sleep(1)
        if not q_md_collector.empty():
            msg=q_md_collector.get()
            if msg[0] == "data_req":
                CHECKABLE_EVENT=msg[1]
                DATA_REQ=True
                if COOLDOWN < 4:
                    COOLDOWN += 2
        if STATS_COUNTER == 0:
            # lock=threading.Lock()
            # with lock:
            q_scheduler_msg.put(("stats:md_collector", {"metadata_downloads": METADATA_DOWNLOADS}))
            STATS_COUNTER=STATSCOUNTER
        else:
            STATS_COUNTER -= 1
        if COOLDOWN == 0:
            COOLDOWN = 10
        COOLDOWN -= 1

# Swarm Metadata Collector Service thread
thread_md_c_service=threading.Thread(target=swarmMetadataCollectorService, args=(q_md_collector, q_metadata, q_updater, q_scheduler_msg), daemon=True)

# Updater service
# Writes HAProxy configurations to disk when ordered
def updaterService(q_updater, q_metadata, q_scheduler_msg):
    HAPROXY_UPDATES=0
    STATS_COUNTER=STATSCOUNTER
    while True:
        # Go easy on the CPU
        time.sleep(1)
        if not q_updater.empty():
            q_updater.clear()
            # Update HAProxy here
            data=q_metadata.get()
            dr=DRouter(data)
            updater_service_logger.debug("update HAProxy")
            lock=threading.Lock()
            with lock:
                dr.writeHAProxyConfigs(dr.collectLabels(dr.checkServices()))
            time.sleep(1)
            with lock:
                dr.updateHAProxyNetwork(dr.getJoinableNetworks())
            HAPROXY_UPDATES += 1
        if STATS_COUNTER == 0:
            # lock=threading.Lock()
            # with lock:
            q_scheduler_msg.put(("stats:updater_service", {"times_haproxy_updated": HAPROXY_UPDATES}))
            STATS_COUNTER=STATSCOUNTER
        else:
            STATS_COUNTER -= 1

# Updater service thread
thread_updater_service=threading.Thread(target=updaterService, args=(q_updater, q_metadata, q_scheduler_msg), daemon=True)

# Event collector
# Collects events from Docker's API and forwards them to schedulerService
def eventCollector(q_event, q_metadata, q_scheduler_msg, q_md_collector):
    client=UnixStreamHTTPConnection(DROUTER_DOCKER_SOCKET)
    # while q_metadata.empty():
    #     time.sleep(3)
    # data=q_metadata.get()
    # dr=DRouter(data)
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
                if action == "create" or action == "update" or action == "remove":
                    # if dr.isDRouterService(event.get("Actor").get("ID")):
                    if q_event.empty():
                        e_collector_logger.debug("Notifying scheduler about a change in the Swarm")
                        q_event.put(event)
            if not response:
                break

# scheduler Service thread
thread_event_collector=threading.Thread(target=eventCollector, args=(q_event, q_metadata, q_scheduler_msg, q_md_collector), daemon=True)





# Threads
logger.info("Starting Event Collector")
thread_event_collector.start()
logger.info("Starting Swarm Metadata Collector Service")
thread_md_c_service.start()
logger.info("Starting Updater Service")
thread_updater_service.start()


# Scheduler service
# Distributes messages/tasks.
def schedulerService(q_event, q_md_collector, q_updater, q_scheduler_msg):
    STATS_COUNTER=STATSCOUNTER+15
    STATS={
        "events": 0
    }
    EVENTS_NEW=0
    EVENTS_OLD=0
    NEW_EVENTS=False
    while True:
        # Go easy on the CPU
        time.sleep(1)
        EVENTS_OLD=EVENTS_NEW
        if not q_event.empty():
           EVENTS_NEW += 1
           event=q_event.get()
           scheduler_logger.debug(event)
           STATS["events"] = EVENTS_NEW
           q_md_collector.put(("data_req", event))
        lock=threading.Lock()
        with lock:
            while not q_scheduler_msg.empty():
                msg=q_scheduler_msg.get()
                if msg[0].startswith("stats"):
                    component=msg[0].split(":")[1]
                    STATS[component] = msg[1]

        if STATS_COUNTER == 0:
            if DROUTER_STATS==True:
                scheduler_logger.info(("stats", STATS))
            STATS_COUNTER=STATSCOUNTER+10
        else:
            STATS_COUNTER -= 1
        

try:

    # Main
    logger.info("Starting Scheduler")
    schedulerService(q_event, q_md_collector, q_updater, q_scheduler_msg)

except (KeyboardInterrupt, SystemExit):
    sys.exit(0)