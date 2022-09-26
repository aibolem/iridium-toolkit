#!/usr/bin/env python3
# vim: set ts=4 sw=4 tw=0 et pm=:

import sys
import datetime
import re
import struct
import math
import os
import socket
from copy import deepcopy
from util import fmt_iritime, to_ascii, slice_extra

from .base import *
from ..config import config, outfile

class ReassemblePPM(Reassemble):
    def __init__(self):
        self.idx=None
        self.sv_pos = {}
        self.deltas = []
        self.dist_min = None
        pass

    #https://stackoverflow.com/questions/30307311/python-pyproj-convert-ecef-to-lla
    import pyproj
    import numpy
    ecef = pyproj.Proj(proj='geocent', ellps='WGS84', datum='WGS84')
    lla = pyproj.Proj(proj='latlong', ellps='WGS84', datum='WGS84')

    to_ecef = pyproj.Transformer.from_proj(lla, ecef)

    # https://www.koordinaten-umrechner.de/decimal/48.153543,11.560702?karte=OpenStreetMap&zoom=19
    lat=48.153543
    lon=11.560702
    alt=542
    ox, oy, oz = to_ecef.transform(lon, lat, alt, radians=False)

    r1=re.compile(r'.* slot:(\d)')
    r2=re.compile(r'.* time:([0-9:T-]+(\.\d+)?)Z')
    r3=re.compile(r'.* sat:(\d+)')
    ri=re.compile(r'sat:(\d+) beam:(\d+) xyz=\((-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+)\) pos=\(([+-][0-9.]+)/([+-][0-9.]+)\) alt=(-?[0-9]+) .* bc_sb:\d+(?: (.*))?')


    def filter(self,line):
        q=super().filter(line)
        if q==None: return None

        if q.typ == "IRA:":
            m=self.ri.match(q.data)
            if m:
                if int(m.group(8)) > 700:
                    x = int(m.group(3)) * 4000.
                    y = int(m.group(4)) * 4000.
                    z = int(m.group(5)) * 4000.
                    self.sv_pos[int(m.group(1))] = {'x': x, 'y': y, 'z': z, 'mstime': float(q.mstime)}

        if q.typ!="IBC:": return None

        q.enrich()
        if q.confidence<95: return None

        if 'perfect' in config.args:
            if not q.perfect: return None

        m=self.r1.match(q.data)
        if not m: return
        q.slot=int(m.group(1))

        m=self.r2.match(q.data)
        if not m: return
        if m.group(2):
            q.itime = datetime.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S.%f')
        else:
            q.itime = datetime.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S')

        m=self.r3.match(q.data)
        if not m: return
        q.sat=int(m.group(1))

        if q.sat not in self.sv_pos: return None
        # Only accept IBC with a very recent position update via IRA
        dt = float(q.mstime) - self.sv_pos[q.sat]['mstime']
        if dt > 90: return None

        return q

    def process(self,q):
        q.uxtime=datetime.datetime.utcfromtimestamp(q.time)

        # correct for slot:
        # 1st vs. 4th slot is 3 * (downlink + guard)
        q.itime+=datetime.timedelta(seconds=q.slot*(3 * float(8.28 + 0.1))/1000)

        # correct to beginning of frame:
        # guard + simplex + guard + 4*(uplink + guard) + extra_guard
        q.itime+=datetime.timedelta(seconds=(1 + 20.32 + 1.24 + 4 * float(8.28 + 0.22) + 0.02)/1000)

        # correct to beginning of signal:
        # our timestamp is "the middle of the first symbol of the 12-symbol BPSK Iridium sync word"
        # so correct for 64 symbols preamble & one half symbol.
        q.itime+=datetime.timedelta(seconds=(64.5/25000))

        # correction for signal travel time: ~ 2.6ms-10ms (780-3000 km)
        sv_pos = self.sv_pos[q.sat]
        sx = sv_pos['x']
        sy = sv_pos['y']
        sz = sv_pos['z']

        d_m = math.sqrt((sx-ox)**2 + (sy-oy)**2 + (sz-oz)**2)
        if not self.dist_min or d_m < self.dist_min:
            self.dist_min = d_m
            self.t_min = q.itime
            self.delta_min = (q.uxtime - q.itime).total_seconds()

        d_s = d_m / 299792458.
        q.itime+=datetime.timedelta(seconds=d_s)

        return [[q.uxtime,q.itime,q.starttime]]

    ini=None
    def consume(self, data):
        tdelta=(data[0]-data[1]).total_seconds()
        self.deltas.append(tdelta*1e6)
        if self.ini is None: # First PKT
            self.idx=0
            self.ini=[data]
            self.fin=[data]
            self.cur=data
            self.tmin=tdelta
            self.tmax=tdelta
        if data[2]!=self.ini[self.idx][2]: # New Recording
            self.idx += 1
            self.ini.append(data)
            self.fin.append(data)
            self.cur=data
        self.fin[-1]=data

        if tdelta < self.tmin:
            self.tmin=tdelta
        if tdelta > self.tmax:
            self.tmax=tdelta
        if 'tdelta' in config.args:
            print("tdelta %sZ %f"%(data[0].isoformat(),tdelta))

        # "interactive" statistics per INVTL(600)
        if (data[1]-self.cur[1]).total_seconds() > 600:
            (irun,toff,ppm)=self.onedelta(self.cur,data, verbose=False)
            if 'grafana' in config.args:
                print("iridium.live.ppm %.5f %d"%(ppm,(data[1]-datetime.datetime.fromtimestamp(0)).total_seconds()))
                sys.stdout.flush()
            else:
                print("@ %s: ppm: % 6.3f ds: % 9.6f "%(data[1],ppm,(data[1]-data[0]).total_seconds())
            self.cur=data
        elif (data[1]-self.cur[1]).total_seconds() <0:
            self.cur=data

    def onedelta(self, start, end, verbose=False):
        irun=(end[1]-start[1]).total_seconds()
        urun=(end[0]-start[0]).total_seconds()
        toff=urun-irun
        if irun==0: return (0,0,0)
        ppm=toff/irun*1000000
        if verbose:
            print("Blob:")
            print("- Start Itime  : %s"%(start[1]))
            print("- End   Itime  : %s"%(end[1]))
            print("- Start Utime  : %s"%(start[0]))
            print("- End   Utime  : %s"%(end[0]))
            print("- Runtime      : %s"%(str(datetime.timedelta(seconds=int(irun)))))
            print("- PPM          : %.3f"%(ppm))
        return (irun,toff,ppm)

    def end(self):
        alltime=0
        delta=0
        if self.idx is None: return
        for ppms in range(1+self.idx):
            (irun,toff,ppm)=self.onedelta(self.ini[ppms],self.fin[ppms], verbose=True)
            alltime += irun
            delta += toff
        print("rec.tmin %f"%(self.tmin))
        print("rec.tmax %f"%(self.tmax))
        print("rec.ppm %.3f"%(delta/alltime*1000000))

        print("dist_min:", self.dist_min)
        print("t_min:", self.t_min)
        print("delta_min:", self.delta_min)


        print("median", numpy.median(self.deltas))
        print("average", numpy.median(self.deltas))

        if False:
            import matplotlib.pyplot as plt
            plt.hist(self.deltas, bins=100)
            plt.show()


modes=[
["ppm",        ReassemblePPM,         ('perfect','grafana','tdelta') ],
]
