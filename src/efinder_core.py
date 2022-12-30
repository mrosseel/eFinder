#!/usr/bin/python3

# Program to implement an eFinder (electronic finder) on motorised Alt Az telescopes
# Copyright (C) 2022 Keith Venables.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# This variant is customised for ZWO ASI ccds as camera, Nexus DSC as telescope interface
# It requires astrometry.net installed

import time
import os
import math
from PIL import Image
import psutil
import threading
import logging
from pathlib import Path
import fitsio
from Coordinates import Coordinates
from platesolve import PlateSolve
from common import Common, ParamData
from handpad import HandPad
from common import CameraData, CLIData, AstroData, OffsetData
from typing import Dict


class EFinder():

    def __init__(self, handpad: HandPad, common: Common, coordinates: Coordinates,
                 camera_data: CameraData, cli_data: CLIData,
                 astro_data: AstroData, offset_data: OffsetData,
                 param_data: ParamData):
        self.handpad = handpad
        self.camera_data = camera_data
        self.cli_data = cli_data
        self.astro_data = astro_data
        self.offset_data = offset_data
        self.cwd_path = Path.cwd()
        self.param = param_data
        self.common = common
        self.coordinates = coordinates
        self.version = self.common.get_version()
        self.platesolve = PlateSolve(
            camera_data.pix_scale, self.cli_data.images_path)
        _, _, dxstr, dystr = self.common.dxdy2pixel(
            float(self.param.d_x), float(self.param.d_y)
        )
        self.offset_data.offset_str = dxstr + "," + dystr
        scan = threading.Thread(target=self.reader)
        scan.daemon = True
        scan.start()

    def align(self, nexus, offset_flag=False):
        # global align_count, solve, sync_count, param, offset_flag, arr
        output = self.handpad.display
        nexus_ra, nexus_dec, is_aligned, _ = nexus.read_altAz()
        self.handpad.set_lines(self.handpad.nex_pos,
                               f"Nex: RA {nexus_ra}", f"   Dec {nexus_dec}", None)
        if is_aligned:
            self.handpad.set_lines(self.handpad.aligns_pos,
                                   "'Select' syncs",
                                   "Nexus is aligned", None)

        self.capture(offset_flag)
        self.imgDisplay()
        self.solveImage(offset_flag)
        cmd = self.handpad.get_current_cmd()
        if not self.astro_data.solved:
            output.display(cmd.line1, "Solved Failed", cmd.line3)
            return
        align_ra = ":Sr" + \
            self.coordinates.dd2dms((self.astro_data.solved_radec)[0]) + "#"
        align_dec = ":Sd" + \
            self.coordinates.dd2aligndms(
                (self.astro_data.solved_radec)[1]) + "#"
        nexus_response = nexus.get(align_ra)
        logging.info(align_ra)
        if nexus_response == "0":
            logging.info("invalid position")
            output.display(cmd.line1, "Invalid position", cmd.line3)
            return
        nexus_response = nexus.get(align_dec)
        logging.info(align_dec)
        if nexus_response == "0":
            logging.info("invalid position")
            output.display(cmd.line1, "Invalid position", cmd.line3)
            return
        reply = nexus.get(":CM#")
        logging.info(f"reply: {reply}")
        p = nexus.get(":GW#")
        logging.info(f"Align status reply: {p}")
        self.astro_data.align_count += 1
        if p != "AT2":
            output.display(
                "'select' aligns",
                "align count: " + str(self.astro_data.align_count),
                "Nexus reply: " + p[0:3],
            )
        else:
            if p == "AT2":
                self.astro_data.sync_count += 1
                output.display(
                    "'select' syncs",
                    "Sync count " + str(self.astro_data.align_count),
                    "Nexus reply " + p[0:3],
                )
                self.astro_data.nexus.set_aligned(True)
        return

    def capture(self, offset_flag=False):
        extras = {}
        if self.param.test_mode == "1":
            if offset_flag:
                extras['testimage'] = 'polaris'
            else:
                extras['testimage'] = 'm13'
        radec = self.astro_data.nexus.get_short()
        self.camera_data.camera.capture(
            int(float(self.param.exposure) * 1000000),
            int(float(self.param.gain)),
            radec,
            extras
        )
        # TODO call gui.image_show

    def imgDisplay(self):  # displays the captured image on the Pi desktop.
        for proc in psutil.process_iter():
            if proc.name() == "display":
                proc.kill()  # delete any previous image display
        im = Image.open(self.cli_data.images_path / "capture.jpg")
        im.show()

    def solveImage(self, offset_flag=False):
        output = self.handpad.display
        nexus = self.astro_data.nexus
        output.display("Started solving", "", "")
        has_solved, has_star, star_name, _, elapsed_time = self.platesolve.solve_image(
            offset_flag)
        self.astro_data.solved = has_solved
        if not has_solved:
            logging.info("Bad Luck - Solve Failed")
            output.display("Not Solved", "", "")
            return
        if offset_flag and has_star:
            table, _ = fitsio.read(self.cwd_path / "capture.axy", header=True)
            self.offset_data.offset = table[0][0], table[0][1]
            self.offset_data.offset_star_name = star_name
        solvedPos = self.common.applyOffset(self.astro_data.nexus,
                                            self.offset_data.offset)
        ra, dec, d = solvedPos.apparent().radec(self.coordinates.get_ts().now())
        solved_radec = ra.hours, dec.degrees
        solved_altaz = self.coordinates.conv_altaz(
            nexus.long, nexus.lat, *(solved_radec))
        self.astro_data.solved_radec = solved_radec
        self.astro_data.solved_altaz = solved_altaz
        nexus.set_scope_alt(solved_altaz[0] * math.pi / 180.0)
        self.handpad.set_lines(self.handpad.sol_pos,
                               "Sol: RA " +
                               self.coordinates.hh2dms(solved_radec[0]),
                               "   Dec " +
                               self.coordinates.dd2dms(solved_radec[1]),
                               "time: " + str(elapsed_time)[0:4] + " s"
                               )
        self.deltaCalc(elapsed_time)

    def deltaCalc(self, elapsed_time):
        deltaAz, deltaAlt = self.common.deltaCalc(
            self.astro_data.nexus.get_altAz(), self.astro_data.solved_altaz,
            self.astro_data.nexus.get_scope_alt(), self.astro_data.deltaAz,
            self.astro_data.deltaAlt)
        deltaXstr = "{: .2f}".format(float(deltaAz))
        deltaYstr = "{: .2f}".format(float(deltaAlt))
        self.handpad.set_lines(self.handpad.delta_pos,
                               "Delta: x= " + deltaXstr,
                               "       y= " + deltaYstr,
                               "time: " + str(elapsed_time)[0:4] + " s"
                               )

    def measure_offset(self):
        output = self.handpad.display
        offset_flag = True
        output.display("started capture", "", "")
        self.capture(offset_flag)
        self.imgDisplay()
        self.solveImage(offset_flag)
        if not self.astro_data.solved:
            output.display("solve failed", "", "")
            return
        scope_x = self.offset_data.offset[0]
        scope_y = self.offset_data.offset[1]
        d_x, d_y, dxstr, dystr = self.common.pixel2dxdy(scope_x, scope_y)
        self.param.d_x = d_x
        self.param.d_y = d_y
        EFinder.save_param(self.cwd_path, self.param)
        self.offset_data.offset_str = dxstr + "," + dystr
        self.handpad.set_lines(self.handpad.polar_pos,
                               None, f"new {self.offset_data.offset_str}", None)
        self.handpad.set_lines(self.handpad.reset_pos,
                               None, f"new {self.offset_data.offset_str}", None)
        cmd = self.handpad.get_cmd(self.handpad.polar_pos)
        output.display(cmd.line1, cmd.line2,
                       f"{self.offset_data.offset_star_name} found")

    def go_solve(self):
        output = self.handpad.display
        nexus_ra, nexus_dec, is_aligned, _ = self.astro_data.nexus.read_altAz()
        self.handpad.set_lines(
            self.handpad.nex_pos, f"Nex: RA {nexus_ra}",
            f"   Dec {nexus_dec}", None)
        output.display("Image capture", "", "")
        self.capture()
        self.imgDisplay()
        output.display("Plate solving", "", "")
        self.solveImage()
        if self.astro_data.solved:
            output.display("Solved", "", "")
        else:
            output.display("Not Solved", "", "")
            return
        self.handpad.set_pos(self.handpad.delta_pos)
        self.handpad.display_array()

    def goto(self):
        output = self.handpad.display
        nexus = self.astro_data.nexus
        output.display("Attempting", "GoTo++", "")
        goto_ra = nexus.get(":Gr#")
        if (
            goto_ra[0:2] == "00" and goto_ra[3:5] == "00"
        ):  # not a valid goto target set yet.
            logging.info("no GoTo target")
            return
        goto_dec = nexus.get(":Gd#")
        logging.info(f"Target goto RA & Dec {goto_ra} {goto_dec}")
        self.align(nexus)
        if not self.astro_data.solved:
            output.display("problem", "solving", "")
            return
        nexus.write(":Sr" + goto_ra + "#")
        nexus.write(":Sd" + goto_dec + "#")
        nexus.get(":MS#")
        output.display("Performing", " GoTo++", "")
        time.sleep(5)  # replace with a check on goto progress
        self.go_solve()

    def reset_offset(self):
        # global param, arr
        self.param.d_x = 0
        self.param.d_y = 0
        self.offset_data.offset_str = "0,0"
        self.handpad.set_lines(self.handpad.polar_pos, None,
                               f"new {self.offset_data.offset_str}", None)
        self.handpad.set_lines(self.handpad.reset_pos, None,
                               f"new {self.offset_data.offset_str}", None)
        self.handpad.display_array()
        EFinder.save_param(self.cwd_path, self.param)

    @staticmethod
    def get_param(cwd_path: Path) -> ParamData:
        param = dict()
        # global param, self.offset_data.offset_str
        if os.path.exists(cwd_path / "eFinder.config"):
            with open(cwd_path / "eFinder.config") as h:
                for line in h:
                    line = line.strip("\n").split(":")
                    param[line[0]] = str(line[1])
        return ParamData(param)

    @staticmethod
    def save_param(cwd_path: Path, param_data: ParamData):
        param = param_data.get_dict()
        # global param
        with open(cwd_path / "eFinder.config", "w") as h:
            for key, value in param.items():
                # logging.info("%s:%s\n" % (key, value))
                h.write("%s:%s\n" % (key, value))

    def reader(self):
        while True:
            button = self.handpad.display.get_button_press()
            if button:
                nexus_tuple = self.astro_data.nexus.get_nexus_link(), str(
                    self.astro_data.nexus.is_aligned())
                result = self.handpad.on_button(
                    button, self.param, self.offset_data.offset_str, nexus_tuple)
                if result:
                    exec(result)
            time.sleep(0.1)

