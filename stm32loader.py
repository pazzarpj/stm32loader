#!/usr/bin/env python

# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:si:et:enc=utf-8

# Author: Ivan A-R <ivan@tuxotronic.org>
# Project page: http://tuxotronic.org/wiki/projects/stm32loader
#
# This file is part of stm32loader.
#
# stm32loader is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 3, or (at your option) any later
# version.
#
# stm32loader is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with stm32loader; see the file COPYING3.  If not see
# <http://www.gnu.org/licenses/>.
from __future__ import print_function
import sys
import getopt
import serial
import time
from functools import reduce

try:
    from progressbar import *

    usepbar = 1
except:
    usepbar = 0

# Verbose level
QUIET = 20

# these come from AN2606
chip_ids = {
    0x412: "STM32 Low-density",
    0x410: "STM32 Medium-density",
    0x414: "STM32 High-density",
    0x420: "STM32 Medium-density value line",
    0x428: "STM32 High-density value line",
    0x430: "STM32 XL-density",
    0x416: "STM32 Medium-density ultralow power line",
    0x411: "STM32F2xx",
    0x413: "STM32F4xx",
}


def mdebug(level, message):
    if (QUIET >= level):
        print(message, file=sys.stderr)


class CmdException(Exception):
    pass


class CommandInterface:
    extended_erase = 0

    def open(self, aport='/dev/tty.usbserial-ftCYPMYJ', abaudrate=115200, boot0="RTS", rst="DTR"):
        """
        Set up com port and boot0 and rst configuration.
        :param aport:
        :param abaudrate:
        :param boot0:
         "RTS" or "DTR"
        :param rst:
         "RTS" or "DTR"
        :return:
        """
        self.sp = serial.Serial(
            port=aport,
            baudrate=abaudrate,  # baudrate
            bytesize=8,  # number of databits
            parity=serial.PARITY_EVEN,
            stopbits=1,
            xonxoff=0,  # don't enable software flow control
            rtscts=0,  # don't enable RTS/CTS flow control
            timeout=5  # set a timeout value, None for waiting forever
        )
        self._boot0 = boot0.upper()
        self._rst = rst.upper()
        if self._boot0 == self._rst:
            raise ValueError("boot0 and rst cannot be connected to the same pin")
        if self._boot0 not in ["RTS", "DTR"] or self._rst not in ["RTS", "DTR"]:
            raise ValueError("Please select RTS or DTR for boot0 and rst")
        self._dtr_pol = False
        self._rts_pol = False

    def dtr_polarity(self, invert=False):
        self._dtr_pol = invert

    def rts_polarity(self, invert=False):
        self._rts_pol = invert

    def boot0(self, state):
        """
        :param state:
        state = 1 is on
        state = 0 is off
        state is xor-ed with the connected dtr or rts polarity
        :return:
        """
        if self._boot0 == "RTS":
            self.sp.setRTS(state ^ self._rts_pol)
        else:
            self.sp.setDTR(state ^ self._dtr_pol)

    def rst(self, state):
        """
        :param state:
        state = 1 is on
        state = 0 is off
        state is xor-ed with the connected dtr or rts polarity
        :param state:
        :return:
        """
        if self._rst == "RTS":
            self.sp.setRTS(state ^ self._rts_pol)
        else:
            self.sp.setDTR(state ^ self._dtr_pol)

    def _wait_for_ask(self, info=u""):
        # wait for ask
        try:
            ask = bytearray(self.sp.read())[0]
        except:
            raise CmdException("Can't read port or timeout")
        else:
            if ask == 0x79:
                # ACK
                return 1
            else:
                if ask == 0x1F:
                    # NACK
                    raise CmdException(u"NACK {}".format(info))
                else:
                    # Unknown responce
                    raise CmdException(u"Unknown response. {}: {}".format(info, ask))

    def reset(self):
        self.rst(0)
        # self.sp.setDTR(0)
        time.sleep(0.1)
        self.rst(1)
        # self.sp.setDTR(1)
        time.sleep(0.5)

    def initChip(self):
        # Set boot
        self.boot0(0)
        # self.sp.setRTS(0)
        self.reset()

        self.sp.write(u"\x7F".encode('utf-8'))  # Syncro
        return self._wait_for_ask(u"Syncro")

    def releaseChip(self):
        self.boot0(1)
        # self.sp.setRTS(1)
        self.reset()

    def cmdGeneric(self, cmd):
        self.sp.write(bytearray([cmd]))
        self.sp.write(bytearray([cmd ^ 0xFF]))  # Control byte
        return self._wait_for_ask(u"{:X}".format(cmd))

    def cmdGet(self):
        if self.cmdGeneric(0x00):
            mdebug(10, "*** Get command")
            len = bytearray(self.sp.read())[0]
            version = bytearray(self.sp.read())[0]
            mdebug(10, "    Bootloader version: {}".format(version))
            dat = bytearray(self.sp.read(len))
            if 0x44 in dat:
                self.extended_erase = 1
            mdebug(10, "    Available commands: " + ", ".join(["0x{:02X}".format(datum) for datum in dat]))
            self._wait_for_ask(u"0x00 end")
            return version
        else:
            raise CmdException("Get (0x00) failed")

    def cmdGetVersion(self):
        if self.cmdGeneric(0x01):
            mdebug(10, "*** GetVersion command")
            version = self.sp.read()[0].decode('utf-8')
            self.sp.read(2)
            self._wait_for_ask(u"0x01 end")
            mdebug(10, "    Bootloader version: {:X}".format(ord(version)))
            return version
        else:
            raise CmdException("GetVersion (0x01) failed")

    def cmdGetID(self):
        if self.cmdGeneric(0x02):
            mdebug(10, "*** GetID command")
            len = self.sp.read()[0].decode('utf-8')
            id = self.sp.read(ord(len) + 1).decode('utf-8')
            self._wait_for_ask(u"0x02 end")
            return reduce(lambda x, y: x * 0x100 + y, ord(id))
        else:
            raise CmdException("GetID (0x02) failed")

    def _encode_addr(self, addr):
        byte3 = (addr >> 0) & 0xFF
        byte2 = (addr >> 8) & 0xFF
        byte1 = (addr >> 16) & 0xFF
        byte0 = (addr >> 24) & 0xFF
        crc = byte0 ^ byte1 ^ byte2 ^ byte3
        return bytearray([byte0, byte1, byte2, byte3, crc])

    def cmdReadMemory(self, addr, lng):
        assert (lng <= 256)
        if self.cmdGeneric(0x11):
            mdebug(10, "*** ReadMemory command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask(u"0x11 address failed")
            N = (lng - 1) & 0xFF
            crc = N ^ 0xFF
            self.sp.write(bytearray([N, crc]))
            self._wait_for_ask(u"0x11 length failed")
            return self.sp.read(lng)
        else:
            raise CmdException("ReadMemory (0x11) failed")

    def cmdGo(self, addr):
        if self.cmdGeneric(0x21):
            mdebug(10, "*** Go command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask(u"0x21 go failed")
        else:
            raise CmdException("Go (0x21) failed")

    def cmdWriteMemory(self, addr, data):
        assert (len(data) <= 256)
        if self.cmdGeneric(0x31):
            mdebug(10, "*** Write memory command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask(u"0x31 address failed")
            # map(lambda c: hex(ord(c)), data)
            lng = (len(data) - 1) & 0xFF
            mdebug(10, "    %s bytes to write" % [lng + 1])
            self.sp.write(bytearray([lng]))  # len really
            crc = 0xFF
            for c in data:
                crc = crc ^ c
                self.sp.write(bytearray([c]))
            self.sp.write(bytearray([crc]))
            self._wait_for_ask("0x31 programming failed")
            mdebug(10, "    Write memory done")
        else:
            raise CmdException("Write memory (0x31) failed")

    def cmdEraseMemory(self, sectors=None):
        if self.extended_erase:
            return self.cmdExtendedEraseMemory(sectors=sectors)

        if self.cmdGeneric(0x43):
            mdebug(10, "*** Erase memory command")
            if sectors is None:
                # Global erase
                self.sp.write(bytearray([0xFF]))
                self.sp.write(bytearray([0x00]))
            else:
                # Sectors erase
                self.sp.write(bytearray([(len(sectors) - 1) & 0xFF]))
                crc = 0xFF
                for c in sectors:
                    crc = crc ^ c
                    self.sp.write(bytearray([c]))
                self.sp.write(bytearray([crc]))
            self._wait_for_ask("0x43 erasing failed")
            mdebug(10, "    Erase memory done")
        else:
            raise CmdException("Erase memory (0x43) failed")

    def cmdExtendedEraseMemory(self, sectors):
        if self.cmdGeneric(0x44):
            mdebug(10, "*** Extended Erase memory command")
            if sectors is None:
                # Global mass erase
                self.sp.write(bytearray([0xFF]))
                self.sp.write(bytearray([0xFF]))
                # Checksum
                self.sp.write(bytearray([0x00]))
                tmp = self.sp.timeout
                self.sp.timeout = 30
                print("Extended erase (0x44), this can take ten seconds or more")
                self._wait_for_ask(u"0x44 erasing failed")
                self.sp.timeout = tmp
                mdebug(10, "    Extended Erase memory done")
            else:
                # Sectors erase
                # self.sp.write = print
                sec_len = self._cast_to_two_bytes(len(sectors) - 1)
                crc = 0x00
                crc = crc ^ sec_len[0]
                crc = crc ^ sec_len[1]
                self.sp.write(sec_len)
                for c in sectors:
                    page = self._cast_to_two_bytes(c)
                    crc = crc ^ page[0]
                    crc = crc ^ page[1]
                    self.sp.write(page)
                self.sp.write(bytearray([crc]))
                self._wait_for_ask(u"0x44 sector erasing failed")

        else:
            raise CmdException("Extended Erase memory (0x44) failed")

    def _cast_to_two_bytes(self, value):
        return bytearray([value >> 8, value & 0xff])

    def cmdWriteProtect(self, sectors):
        if self.cmdGeneric(0x63):
            mdebug(10, "*** Write protect command")
            self.sp.write(bytearray([(len(sectors) - 1) & 0xFF]))
            crc = 0xFF
            for c in sectors:
                crc = crc ^ c
                self.sp.write(bytearray([c]))
            self.sp.write(bytearray([crc]))
            self._wait_for_ask("0x63 write protect failed")
            mdebug(10, "    Write protect done")
        else:
            raise CmdException("Write Protect memory (0x63) failed")

    def cmdWriteUnprotect(self):
        if self.cmdGeneric(0x73):
            mdebug(10, "*** Write Unprotect command")
            self._wait_for_ask(u"0x73 write unprotect failed")
            self._wait_for_ask(u"0x73 write unprotect 2 failed")
            mdebug(10, "    Write Unprotect done")
        else:
            raise CmdException("Write Unprotect (0x73) failed")

    def cmdReadoutProtect(self):
        if self.cmdGeneric(0x82):
            mdebug(10, "*** Readout protect command")
            self._wait_for_ask(u"0x82 readout protect failed")
            self._wait_for_ask(u"0x82 readout protect 2 failed")
            mdebug(10, "    Read protect done")
        else:
            raise CmdException("Readout protect (0x82) failed")

    def cmdReadoutUnprotect(self):
        if self.cmdGeneric(0x92):
            mdebug(10, "*** Readout Unprotect command")
            self._wait_for_ask(u"0x92 readout unprotect failed")
            self._wait_for_ask(u"0x92 readout unprotect 2 failed")
            mdebug(10, "    Read Unprotect done")
        else:
            raise CmdException("Readout unprotect (0x92) failed")


            # Complex commands section

    def readMemory(self, addr, lng):
        data = bytearray()
        if usepbar:
            widgets = ['Reading: ', Percentage(), ', ', ETA(), ' ', Bar()]
            pbar = ProgressBar(widgets=widgets, maxval=lng, term_width=79).start()

        while lng > 256:
            if usepbar:
                pbar.update(pbar.maxval - lng)
            else:
                mdebug(5, "Read %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
            data = data + self.cmdReadMemory(addr, 256)
            addr = addr + 256
            lng = lng - 256
        if usepbar:
            pbar.update(pbar.maxval - lng)
            pbar.finish()
        else:
            mdebug(5, "Read %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
        data = data + self.cmdReadMemory(addr, lng)
        return data

    def writeMemory(self, addr, data):
        lng = len(data)
        if usepbar:
            widgets = ['Writing: ', Percentage(), ' ', ETA(), ' ', Bar()]
            pbar = ProgressBar(widgets=widgets, maxval=lng, term_width=79).start()

        offs = 0
        while lng > 256:
            if usepbar:
                pbar.update(pbar.maxval - lng)
            else:
                mdebug(5, "Write %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
            self.cmdWriteMemory(addr, data[offs:offs + 256])
            offs = offs + 256
            addr = addr + 256
            lng = lng - 256
        if usepbar:
            pbar.update(pbar.maxval - lng)
            pbar.finish()
        else:
            mdebug(5, "Write %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
        data.extend([0xFF] * (256 - lng))
        self.cmdWriteMemory(addr, data[offs:offs + 256])

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.releaseChip()


def usage():
    print("""Usage: %s [-hqVewvr] [-l length] [-p port] [-b baud] [-a addr] [-g addr] [file.bin]
    -h          This help
    -q          Quiet
    -V          Verbose
    -e          Erase
    -w          Write
    -v          Verify
    -r          Read
    -l length   Length of read
    -p port     Serial port (default: /dev/tty.usbserial-ftCYPMYJ)
    -b baud     Baud speed (default: 115200)
    -a addr     Target address
    -g addr     Address to start running at (0x08000000, usually)

    ./stm32loader.py -e -w -v example/main.bin

    """ % sys.argv[0])


if __name__ == "__main__":

    # Import Psyco if available
    try:
        import psyco

        psyco.full()
        print("Using Psyco...")
    except ImportError:
        pass

    conf = {
        'port': '/dev/tty.usbserial-ftCYPMYJ',
        'baud': 115200,
        'address': 0x08000000,
        'erase': 0,
        'write': 0,
        'verify': 0,
        'read': 0,
        'go_addr': -1,
    }

    # http://www.python.org/doc/2.5.2/lib/module-getopt.html

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hqVewvrp:b:a:l:g:")
    except getopt.GetoptError as err:
        # print help information and exit:
        print(str(err))  # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    QUIET = 5

    for o, a in opts:
        if o == '-V':
            QUIET = 10
        elif o == '-q':
            QUIET = 0
        elif o == '-h':
            usage()
            sys.exit(0)
        elif o == '-e':
            conf['erase'] = 1
        elif o == '-w':
            conf['write'] = 1
        elif o == '-v':
            conf['verify'] = 1
        elif o == '-r':
            conf['read'] = 1
        elif o == '-p':
            conf['port'] = a
        elif o == '-b':
            conf['baud'] = eval(a)
        elif o == '-a':
            conf['address'] = eval(a)
        elif o == '-g':
            conf['go_addr'] = eval(a)
        elif o == '-l':
            conf['len'] = eval(a)
        else:
            assert False, "unhandled option"

    cmd = CommandInterface()
    cmd.open(conf['port'], conf['baud'])
    mdebug(10, "Open port %(port)s, baud %(baud)d" % {'port': conf['port'], 'baud': conf['baud']})
    try:
        try:
            cmd.initChip()
        except:
            print("Can't init. Ensure that BOOT0 is enabled and reset device")

        bootversion = cmd.cmdGet()
        mdebug(0, "Bootloader version %X" % bootversion)
        id = cmd.cmdGetID()
        mdebug(0, "Chip id: 0x%x (%s)" % (id, chip_ids.get(id, "Unknown")))
        #    cmd.cmdGetVersion()
        #    cmd.cmdGetID()
        #    cmd.cmdReadoutUnprotect()
        #    cmd.cmdWriteUnprotect()
        #    cmd.cmdWriteProtect([0, 1])

        if (conf['write'] or conf['verify']):
            data = open(args[0], 'rb').read()

        if conf['erase']:
            cmd.cmdEraseMemory()

        if conf['write']:
            cmd.writeMemory(conf['address'], data)

        if conf['verify']:
            verify = cmd.readMemory(conf['address'], len(data))
            if (data == verify):
                print("Verification OK")
            else:
                print("Verification FAILED")
                print(str(len(data)) + ' vs ' + str(len(verify)))
                for i in range(0, len(data)):
                    if data[i] != verify[i]:
                        print(hex(i) + ': ' + hex(data[i]) + ' vs ' + hex(verify[i]))

        if not conf['write'] and conf['read']:
            rdata = cmd.readMemory(conf['address'], conf['len'])
            open(args[0], 'wb').write(b''.join(bytes(rdata)))

        if conf['go_addr'] != -1:
            cmd.cmdGo(conf['go_addr'])

    finally:
        cmd.releaseChip()
