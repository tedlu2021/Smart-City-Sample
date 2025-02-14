#!/usr/bin/python3

from db_ingest import DBIngest
from db_query import DBQuery
from signal import signal, SIGTERM
from rec2db import Rec2DB
from runva import RunVA
from language import text
from threading import Event
from configuration import env
import traceback

scenario = env["SCENARIO"]
office = list(map(float, env["OFFICE"].split(",")))
dbhost = env["DBHOST"]
every_nth_frame = int(env["EVERY_NTH_FRAME"])
va_mode=env.get("VA_MODE","analytics")

stop=Event()
myAlgorithm=""
version=0

def connect(sensor, location, uri, algorithm, algorithmName):
    try:
        rec2db=Rec2DB(sensor)
        rec2db.start()

        runva=RunVA("object_detection", version, stop=stop)
        runva.loop(sensor, location, uri, algorithm, algorithmName, mode=va_mode)

        rec2db.stop()
        raise Exception("VA exited. This should not happen.")

    except:
        print(traceback.format_exc(), flush=True)

def quit_service(signum, sigframe):
    stop.set()

signal(SIGTERM, quit_service)
dba=DBIngest(host=dbhost, index="algorithms", office=office)
dbs=DBQuery(host=dbhost, index="sensors", office=office)

if scenario=="traffic":
    version = 1
    myAlgorithm="object-detection"
if scenario=="stadium":
    version = 2
    myAlgorithm="svcq-counting"

# register algorithm (while waiting for db to startup)
dba.wait(stop)
algorithm=dba.ingest({
    "name": text[myAlgorithm],
    "office": {
        "lat": office[0],
        "lon": office[1],
    },
    "status": "processing",
    "skip": every_nth_frame,
})["_id"]

# compete for a sensor connection
while not stop.is_set():
    try:
        print("Searching...", flush=True)
        for sensor in dbs.search("type:'camera' and status:'idle' and algorithm='"+myAlgorithm+"' and office:["+str(office[0])+","+str(office[1])+"] and url:*"):
            try:
                # compete (with other va instances) for a sensor
                r=dbs.update(sensor["_id"],{"status":"streaming"},seq_no=sensor["_seq_no"],primary_term=sensor["_primary_term"])

                if sensor["_source"]["url"].split(":")[0] == "rtmp":
                    if scenario=="traffic": version = 3
                    if scenario=="stadium": version = 4

                # stream from the sensor
                print("Connected to "+sensor["_id"]+"...",flush=True)
                connect(sensor["_id"],sensor["_source"]["location"],sensor["_source"]["url"],algorithm,sensor["_source"]["algorithm"])

                # if exit, there is somehting wrong
                r=dbs.update(sensor["_id"],{"status":"disconnected"})
                if stop.is_set(): break

            except Exception as e:
                print("Exception: "+str(e), flush=True)

    except Exception as e:
        print("Exception: "+str(e), flush=True)

    stop.wait(10)

# delete the algorithm instance
dba.delete(algorithm)

