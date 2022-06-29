from gnmi_config import MDT
import yaml
import os
from threading import Event
from time import ctime
from cerberus import Validator
import json
from grpc import FutureTimeoutError


DELAY = 10
LOCAL_IP = "127.0.0.1"
CONFIG_PATH = "../config/config.yaml"

try:
    config = yaml.load(open(os.path.join(os.path.dirname(__file__), CONFIG_PATH), "r"), Loader=yaml.Loader)
except FileNotFoundError as err:
    print('config.yaml could not be found')
    raise err


def validate_config():
    with open("schema.json") as f:
        schema = json.load(f)
    
    v = Validator(schema)
    if not v.validate(config):
        print(v.errors)
        raise RuntimeError("config.yaml formatted improperly")


def setup():
    """
        Creates a destination group for each collector in config.yaml
        Creates all sensor groups defined in config.yaml
    """
    try:
        router = config["router"]
        with MDT(LOCAL_IP, router["port"], router["username"], router["password"]) as router_config:

            for collector in config["collectors"]:
                dg = collector["destination-group"]
                router_config.create_destination(dg["destination-id"], dg["ip"], dg["port"], dg["encoding"], dg["protocol"])

            for sensor_group in config["sensor-groups"]:
                for sensor_path in sensor_group["sensor-paths"]:
                    router_config.create_sensor_path(sensor_group["sensor-group-id"], sensor_path)
    except FutureTimeoutError as err:
        print('Failed to connect to host. Check grpc configuration on host or username/password in config.yaml')
        raise err

def check():
    """
        Checks connectivity to collectors in config.yaml and updates router telemetry configuration to highest priority
        
        :return: The index of the current active collector in the priority list
        :rtyp: int 
    """

    try:
        router = config["router"]
        with MDT(LOCAL_IP, router["port"], router["username"], router["password"]) as router_config:

            for collector in config["collectors"]:
                # If the collector does not yet have a subscription, create it
                if router_config.read_subscription(collector["subscription"]["subscription-id"]) == None:
                    for sensor_group in config["sensor-groups"]:
                        router_config.create_subscription(collector["subscription"]["subscription-id"], sensor_group["sensor-group-id"], collector["destination-group"]["destination-id"], collector["subscription"]["interval"])

                # Check the state of the subscription, if it is active, delete all subsequent subscriptions
                if router_config.check_connection(collector["subscription"]["subscription-id"]):
                    index = config["collectors"].index(collector)
                    for backup in config["collectors"][index + 1:]:
                        if router_config.read_subscription(backup["subscription"]["subscription-id"]) != None:
                            router_config.delete_subscription(backup["subscription"]["subscription-id"])
                    return index
    except FutureTimeoutError as err:
        print('Failed to connect to host. Check grpc configuration on host or username/password in config.yaml')
        raise err
        
    return -1

if __name__ == "__main__":
    event = Event()
    validate_config()
    setup()
    
    while True:
        collector = check()
        if collector == -1:
            print("NO COLLECTORS ACTIVE: ", ctime())
            event.wait(DELAY)
        else:
            event.wait(config["collectors"][collector]["subscription"]["interval"]/1000)