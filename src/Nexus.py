import serial
import time
import socket
from datetime import datetime, timedelta
import os
import math
import re
from Display import Display
import Coordinates
import logging


class Nexus:
    """The Nexus utility class"""

    def __init__(self, display: Display, coordinates: Coordinates) -> None:
        """Initializes the Nexus DSC

        Parameters:
        handpad (Display): The handpad that is connected to the eFinder
        coordinates (Coordinates): The coordinates utility class to be used in the eFinder
        """
        self.display = display
        self.aligned = False
        self.nexus_link = "none"
        self.coordinates = coordinates
        self.NexStr = "not connected"
        self.short = "no RADec"
        self.long = 0
        self.lat = 0

        try:
            self.ser = serial.Serial("/dev/ttyS0", baudrate=9600)
            self.ser.write(b":P#")
            time.sleep(0.1)
            p = str(self.ser.read(self.ser.in_waiting), "ascii")
            if p[0] == "L":
                self.ser.write(b":U#")
            self.ser.write(b":P#")
            time.sleep(0.1)
            logging.info(
                f"Connected to Nexus in{str(self.ser.read(self.ser.in_waiting)} ascii via USB"
            )
            self.NexStr = "connected"
            self.display.display("Found Nexus", "via USB", "")
            time.sleep(1)
            self.nexus_link = "USB"
        except:
            self.HOST = "10.0.0.1"
            self.PORT = 4060
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((self.HOST, self.PORT))
                    s.send(b":P#")
                    time.sleep(0.1)
                    p = str(s.recv(15), "ascii")
                    if p[0] == "L":
                        s.send(b":U#")
                    s.send(b":P#")
                    time.sleep(0.1)
                    logging.info(f"Connected to Nexus in {str(s.recv(15)} ascii via wifi")
                    self.NexStr = "connected"
                    self.display.display("Found Nexus", "via WiFi", "")
                    time.sleep(1)
                    self.nexus_link = "Wifi"
            except:
                logging.info("no USB or Wifi link to Nexus")
                self.display.display("Nexus not found", "", "")

    def write(self, txt: str) -> None:
        """Write a message to the Nexus DSC

        Parameters:
        txt (str): The text to send to the Nexus DSC
        """
        # print('write',flag)
        if self.nexus_link == "USB":
            self.ser.write(bytes(txt.encode("ascii")))
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.HOST, self.PORT))
                s.send(bytes(txt.encode("ascii")))
        logging.info(f"sent {txt} to Nexus")

    def get(self, txt: str) -> str:
        """Receive a message from the Nexus DSC

        Parameters:
        txt (str): The string to send (to tell the Nexus DSC what you want to receive)

        Returns:
        str:  The requested information from the DSC
        """
        if self.nexus_link == "USB":
            self.ser.write(bytes(txt.encode("ascii")))
            time.sleep(0.1)
            res = str(self.ser.read(self.ser.in_waiting).decode("ascii")).strip("#")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.HOST, self.PORT))
                s.send(bytes(txt.encode("ascii")))
                time.sleep(0.1)
                res = str(s.recv(16).decode("ascii")).strip("#")
        logging.info(f"sent {txt} got {res} from Nexus")
        return res

    def read(self) -> None:
        """Establishes that Nexus DSC is talking to us and get observer location and time data"""
        Lt = self.get(":Gt#")[0:6].split("*")
        self.lat = float(Lt[0] + "." + Lt[1])
        Lg = self.get(":Gg#")[0:7].split("*")
        self.long = -1 * float(Lg[0] + "." + Lg[1])
        self.location = self.coordinates.get_earth() + wgs84.latlon(self.lat, self.long)
        local_time = self.get(":GL#")
        local_date = self.get(":GC#")
        local_offset = float(self.get(":GG#"))
        logging.info(f
            "Nexus reports: local datetime as {local_date=}, {local_time=}, {loca_offset=}"
        )
        date_parts = local_date.split("/")
        local_date = date_parts[0] + "/" + date_parts[1] + "/20" + date_parts[2]
        dt_str = local_date + " " + local_time
        format = "%m/%d/%Y %H:%M:%S"
        local_dt = datetime.strptime(dt_str, format)
        new_dt = local_dt + timedelta(hours=local_offset)
        logging.info(f"Calculated UTC {new_dt}")
        print("setting pi clock to:", end=" ")
        os.system('sudo date -u --set "%s"' % new_dt + ".000Z")
        p = self.get(":GW#")
        if p != "AT2#":
            self.display.display("Nexus reports", "not aligned yet", "")
        else:
            self.display.display("eFinder ready", "Nexus reports" + p, "")
            self.aligned = True
        time.sleep(1)

    def read_altAz(self):
        """Read the RA and declination from the Nexus DSC and convert them to altitude and azimuth

        Parameters:

        Returns:
        ra, dec and is_aligned
        """
        ra = self.get(":GR#").split(":")
        dec = re.split(r"[:*]", self.get(":GD#"))
        self.radec = (
            float(ra[0]) + float(ra[1]) / 60 + float(ra[2]) / 3600
        ), math.copysign(
            abs(abs(float(dec[0])) + float(dec[1]) / 60 + float(dec[2]) / 3600),
            float(dec[0]),
        )
        self.altaz = self.coordinates.conv_altaz(self, *(self.radec))
        self.scope_alt = self.altaz[0] * math.pi / 180
        self.short = ra[0] + ra[1] + dec[0] + dec[1]
        nexus_ra = self.coordinates.hh2dms(self.radec[0])
        nexus_dec = self.coordinates.dd2dms(self.radec[1])

        logging.debug(f"Nexus RA: {nexus_ra}, Dec: {nexus_dec}")
        if arr is not None:
            arr[0, 1][0] = "Nex: RA " + nexus_ra
            arr[0, 1][1] = "   Dec " + nexus_dec
        is_aligned = False
        p = self.get(":GW#")
        if p == "AT2#":
            is_aligned = True
            if arr is not None:
                arr[0, 4][1] = "Nexus is aligned"
                arr[0, 4][0] = "'Select' syncs"

        return nexus_ra, nexus_dec, is_aligned, p

    def get_short(self):
        """Returns a summary of RA & Dec for file labelling

        Returns:
        short: RADec
        """
        return self.short

    def get_location(self):
        """Returns the location on earth of the observer

        Returns:
        location: The location
        """
        return self.location

    def get_long(self):
        """Returns the longitude of the observer

        Returns:
        long: The longitude
        """
        return self.long

    def get_lat(self):
        """Returns the latitude of the observer

        Returns:
        lat: The latitude
        """
        return self.lat

    def get_scope_alt(self):
        """Returns the altitude the telescope is pointing to

        Returns:
        The altitude
        """
        return self.scope_alt

    def get_altAz(self):
        """Returns the altitude and azimuth the telescope is pointing to

        Returns:
        The altitude and the azimuth
        """
        return self.altaz

    def get_radec(self):
        """Returns the RA and declination the telescope is pointing to

        Returns:
        The RA and declination
        """
        return self.radec

    def get_nexus_link(self) -> str:
        """Returns how the Nexus DSC is connected to the eFinder

        Returns:
        str: How the Nexus DSC is connected to the eFidner
        """
        return self.nexus_link

    def get_nex_str(self) -> str:
        """Returns if the Nexus DSC is connected to the eFinder

        Returns:
        str: "connected" or "not connected"
        """
        return self.NexStr

    def is_aligned(self) -> bool:
        """Returns if the Nexus DSC is connected to the eFinder

        Returns:
        bool: True if the Nexus DSC is connected to the eFidner, False otherwise.
        """
        return self.aligned

    def set_aligned(self, aligned: bool) -> None:
        """Set the connection status

        Parameters:
        bool: True if connected, False if not connected."""
        self.aligned = aligned

    def set_scope_alt(self, scope_alt) -> None:
        """Set the altitude of the telescope.

        Parameters:
        scope_alt: The altitude of the telescope"""
        self.scope_alt = scope_alt
