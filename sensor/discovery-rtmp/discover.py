#!/usr/bin/python3

from signal import SIGTERM, signal
from db_query import DBQuery
from db_ingest import DBIngest
from probe import probe
from srsapi import SRSAPI
from configuration import env
import traceback
import socket
import time
import json
import requests

service_interval = float(env.get("SERVICE_INTERVAL","30"))
office = list(map(float,env["OFFICE"].split(","))) if "OFFICE" in env else None
dbhost= env.get("DBHOST",None)
rtmp_host= env.get("RTMP_HOST",None)

def quit_service(signum, sigframe):
    exit(143)

signal(SIGTERM, quit_service)

dbi=None
dbs=None
dbp=None
if dbhost and office:
    dbi=DBIngest(index="sensors",office=office,host=dbhost)
    dbs=DBQuery(index="sensors",office=office,host=dbhost)
    dbp=DBQuery(index="provisions",office=office,host=dbhost)
    dbp.wait()
  
def probe_info(rtmpid):
    if office and dbhost:
        r=list(dbp.search("rtmpid='"+rtmpid+"'",size=1))
        if r:
            dinfo={ k:r[0]["_source"][k] for k in ["manufacturer","model","serial"] if k in r[0]["_source"] }
            return dinfo
    return {}

srsapi=SRSAPI(rtmp_host)

while True:
    streams={}
    options=[]
    try:
        streams={item["name"]: item for item in srsapi.list_stream()}
    except:
        print(traceback.format_exc(), flush=True)
        continue

    if dbp:
        try:
            r=dbp.bucketize("rtmpuri:* or rtmpid:*",["rtmpuri","rtmpid"],size=1000)
            if r:
                options=[{"rtmpid": item.split("/")[-1],"rtmpuri": item} for item in list(r["rtmpuri"].keys())]
        except:
            print(traceback.format_exc(), flush=True)
            continue
        
    for item in options:
        rtmpid = item["rtmpid"]
        rtmpuri = item["rtmpuri"]
        sinfo=streams[rtmpid] if rtmpid in streams else None
        if sinfo==None:
            print("Skipping as {} is not active.".format(rtmpid), flush=True)
            continue

        print("Probing "+rtmpuri, sinfo["name"],sinfo["publish"],flush=True)
        try:
            dinfo=probe_info(rtmpid)
        except:
            print(traceback.format_exc(), flush=True)
            continue

        sinfo.update({
            "duration": 0.0,
            "start_time": float(sinfo["live_ms"]),
            "resolution": {
                "width": int(sinfo["video"]["width"]),
                "height": int(sinfo["video"]["height"]),
            },
            "bandwidth": float(sinfo["kbps"]["send_30s"]),
        })

        r=None
        if dbhost:
            try:
                r=list(dbs.search("url='{}'".format(rtmpuri),size=1))
                if r:
                    if r[0]["_source"]["status"]!="disconnected":
                        print("Skipping {}:{}".format(rtmpid,r[0]["_source"]["status"]),flush=True)
                        continue
            except:
                print(traceback.format_exc(), flush=True)
                continue
            
        if sinfo["publish"]["active"]=="false":
            print("{} is not active".format(rtmpid), flush=True)
            continue

        sinfo.update(dinfo)
        sinfo.update({
            'type': 'camera',
            'subtype': 'ip_camera',
            'url': rtmpuri,
            'status': 'idle',
        })

        if not dbhost: continue

        camids=[("rtmpid",rtmpid)]
        try:
            if not r: # new camera
                template=list(dbp.search(" or ".join(['{}="{}"'.format(id1[0],id1[1]) for id1 in camids]),size=1))
                print("Searching for template", template, flush=True)
                if template:
                    print("Ingesting", flush=True)
                    record=template[0]["_source"]
                    record.update(sinfo)
                    record.pop('passcode',None)
                    dbi.ingest(record,refresh="wait_for")
                else:
                    print("Template not found", flush=True)
            else: # camera re-connect
                dbs.update(r[0]["_id"],sinfo)

        except Exception as e:
            print(traceback.format_exc(), flush=True)
            continue

    if not dbhost: break
    time.sleep(service_interval)
