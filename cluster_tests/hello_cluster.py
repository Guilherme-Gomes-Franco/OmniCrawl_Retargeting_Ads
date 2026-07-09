import socket
import datetime

# Get some info about the node we are running on
hostname = socket.gethostname()
now = datetime.datetime.now()

print(f"Hello from the FCT UNL Cluster!")
print(f"Running on Node: {hostname}")
print(f"Current Time: {now}")